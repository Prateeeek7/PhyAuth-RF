# PhyAuth-RF — Audit & Implementation Plan

Target hardware (from `Remaining_Work.txt`):

| Role | Board | RF module |
|---|---|---|
| Receiver / verifier | ESP32-WROOM-32 DevKit (30-pin, CP2102) | SRX882 superhet 433.92 MHz RX |
| Genuine transmitter A | EV1527 433 MHz key fob | (built in) |
| Attacker / clone node | ESP32-S3 DevKitC (N16R8) | STX882 433.92 MHz TX |

---

## Part 1 — Audit: what is missing or broken

### A. Firmware (ESP32 receiver)
1. **Race condition**: the ISR keeps writing into `intervals[]` while `loop()` prints it, so packets get corrupted. There is no double buffering.
2. **Timing resolution**: `micros()` gives 1 µs resolution, plus jitter from the Arduino `attachInterrupt` dispatcher. The fingerprint lives at sub-µs level, so this throws away the signal we want to measure.
3. **Frames are cut at a fixed 64 slots and zero-padded**: they don't line up with protocol frames. The recorded data proves it: most "packets" carry only 12–25 non-zero values, mixed with 130–280 µs noise glitches.
4. No glitch filter. The 50 µs squelch only drops pulses; it doesn't merge them, so a dropped glitch corrupts both neighbouring widths.
5. The level of the first interval (HIGH or LOW) is never recorded, so features computed with `[0::2]` = HIGH can be wrong.
6. Inter-frame gap and frame timestamp are discarded. That loses the most precise clock-skew measurement available (frame repetition period).
7. Hard-coded `deviceLabel = "DEV_A"` is printed in every packet.
8. At 115200 baud the link can't keep up with a key fob's ~25 frames/s.
9. The `.ino` copies and `src/main.cpp` have diverged (the TX `.ino` uses GPIO12, a strapping pin that can break boot; `main.cpp` uses GPIO4).
10. **No TinyML or edge authentication exists**, although the report promises it. There are no LEDs, no relay, no standalone mode.

### B. Firmware (ESP32-S3 transmitter)
1. Sends a meaningless alternating pattern, not a real protocol, so it can't act as a realistic clone or replay attacker.
2. `delayMicroseconds` bit-banging is unstable when interrupts fire.
3. No serial control (code, timing, mode), so the backend can't drive an attack experiment.

### C. Signal processing / features (the core research flaw)
1. **The model can't see clock skew.** `PulseTimingDataset` z-normalises every vector (`(x-mean)/std`). That erases absolute timing, i.e. the oscillator period, which is the single strongest fingerprint for RC-oscillator fobs such as the EV1527.
2. **The "clock skew" metric is wrong.** `mean(highs) - mean(lows)` is duty-cycle/code dependent, and "SNR" is computed from timing variance.
3. No protocol decoding, so the system can't tell what code was sent from who sent it.
4. **Code leakage.** Raw interval sequences encode the payload bits. A CNN on them learns the code, not the hardware: 100 % accuracy that collapses against a clone sending the same code.
5. The IQ-based DSP modules (`cfo`, IQ imbalance, CUSUM) and the RTL-SDR manager are dead code for this hardware.

### D. ML pipeline
1. **Training can never find data.** `filename.split("_",1)` turns `session01_DEV_A_20260919_011957.jsonl` into device `DEV_A_20260919_011957`, which never matches the device map, so the dataset comes out empty.
2. The embedding is not L2-normalised, but the triplet loss assumes unit vectors. The authenticator normalises queries but not calibration data, so thresholds are inconsistent.
3. Thresholds are calibrated on the validation set the checkpoint was selected on, and there is no test-set evaluation (no confusion matrix, ROC, EER or FAR/FRR).
4. Random file split with fewer than 3 sessions: near-duplicate frames from one button press leak between train and test.
5. Profiles are stored with `pickle`, which is unsafe to load.
6. `tests/test_ml.py` imports classes that no longer exist, so the suite fails at collection.

### E. Backend
1. The recording task calls `esp32_manager.stop()` when it finishes, which **kills the live telemetry stream**. Record callbacks are never removed (leak).
2. Inference runs at 10 FPS on the *same* held packet, writing ~15 duplicate auth rows per real packet.
3. The "claimed" device equals the predicted device, so authentication can never detect a spoof.
4. Default serial port `/dev/ttyUSB0` in `ExperimentConfig` (wrong on macOS). Serial port is fixed in `config.py`, with no port discovery and no connect/disconnect.
5. Fake IQ/FFT/constellation data from the simulated SDR is shown as RF data.
6. `uvicorn.run("main:app")` path is wrong. `on_event` is deprecated. Adding columns to `Device` needs migrations.
7. Per-client WebSocket pipelines: every open browser tab runs its own inference.

### F. Frontend
1. Uses port **8005** while the backend runs on **8000**.
2. The record form posts SigMF fields (`center_frequency`, `gain`, `duration_seconds`) and omits `serial_port`.
3. Many buttons do nothing (New Project, Save State, Export…). The FFT, waterfall and constellation panels show synthetic data.
4. Metadata still says "RTL-SDR".

---

## Part 2 — Target architecture

```
 EV1527 fob ─┐                                   ┌─► LEDs / buzzer / relay (edge decision)
 Clone node ─┼─433.92 MHz─► SRX882 ─► ESP32 RX ──┤
 (ESP32-S3)  ┘              GPIO14   ISR+CCOUNT  └─► USB 921600 JSONL ─► FastAPI hub
                                     (4.17 ns)                            │
     ┌────────────────────────────────────────────────────────────────────┘
     ▼
 frame parser ─► pulse DSP (glitch merge, LS clock fit, decode, quality) ─► features
     ─► FingerprintNet (seq-ResNet ⊕ feature-MLP) ─► embedding ─► Mahalanobis vs CLAIMED device
     ─► burst-level evidence fusion ─► decision {AUTHENTIC, SPOOF, UNKNOWN, LOW_QUALITY}
     ─► SQLite events + WebSocket broadcast ─► Next.js console
 Training ─► evaluation report (confusion, ROC, EER, cross-session, ablation)
          ─► edge export: C header (scaler + MLP + profiles) ─► flashed to ESP32 RX
```

### Key design decisions
* **Claim and verify are separate.** The *claim* is the decoded protocol code (what the packet says). The *verification* is the physical fingerprint (who actually sent it). A clone that replays the right code gets flagged as `SPOOF_SUSPECTED`. Fobs without a stable code (rolling code) fall back to identify-then-verify.
* **Physically meaningful, code-invariant features**:
  - Clock period T from bit-pair periods (H+L), which cancels slicer and duty distortion and is channel-invariant.
  - Clock offset in ppm.
  - Oscillator jitter (pair-period residual σ).
  - Edge/duty bias for short and long symbols.
  - Turn-on transient (first-pulse residual).
  - Intra-frame drift (oscillator warm-up chirp).
  - Sync-gap ratio.
  - Frame repetition period.
* **The same feature extractor in C and Python**, with a host-side parity test (compile the C with clang, call it via ctypes).
* **A physics-based virtual hardware simulator** emitting the exact firmware serial protocol. It models RC-oscillator fobs, a crystal clone, the channel and slicer, receiver ISR jitter and SRX882 noise. The full stack runs and is testable without boards. The UI always labels it **SIMULATED**.
* **Burst-level evidence fusion**: one button press gives 5–20 frames; distances are averaged before deciding, which cuts FAR and FRR.

---

## Part 3 — Implementation steps

| # | Work package | Files |
|---|---|---|
| 0 | Backup of current state | `_backup_pre_v2.tar.gz` |
| 1 | Pulse DSP library (Python): glitch merge, clock LS fit, decoder, quality gate, features, code-invariant sequence | `dsp/pulse_dsp.py` |
| 2 | Shared C DSP + feature extractor + edge MLP inference | `firmware/esp32_receiver/src/phyauth_dsp.{h,c}` |
| 3 | RX firmware v2: IDF GPIO ISR + CCOUNT timestamps, lock-free ring buffer, gap segmentation, glitch merge, 921600 baud, hello/frame/stats/auth lines, serial commands, edge auth + LED/buzzer/relay | `firmware/esp32_receiver/src/main.cpp` |
| 4 | TX firmware v2 (ESP32-S3): RMT-timed EV1527 encoder, serial commands (`CLONE`, `PROFILE`, `JITTER`, `AUTO`, `STOP`), BOOT-button "fob press" | `firmware/esp32_transmitter/src/main.cpp` |
| 5 | Virtual hardware simulator (scenarios: enroll, genuine, clone attack, unknown fob, distance sweep) | `sim/rf_simulator.py` |
| 6 | Acquisition: protocol-v2 + legacy parser, serial manager with port discovery, reconnect and TX-side writer, single broadcast hub | `acquisition/*` |
| 7 | ML: per-record labels, burst-grouped temporal split, FingerprintNet fusion + EdgeMLP, L2 embeddings, calibration on held-out data, JSON/NPZ profiles | `ml/*` |
| 8 | Evaluation: confusion, ROC/EER, FAR/FRR, cross-session, clone-rejection rate, feature permutation importance, ablation | `ml/evaluate.py` |
| 9 | Edge export: `phyauth_model.h` generator + parity check | `ml/export_edge.py` |
| 10 | Backend: hardware/connect/status, recording jobs (non-destructive), enrollment of codes, auth engine (once per frame), events DB, reports, attack-lab TX control, lightweight DB migration, lifespan | `backend/*` |
| 11 | Frontend rewrite: Live console, Capture & Enroll, Signal Analysis (pulse train, width histogram, residuals, clock-ppm trend), Model Lab (train, metrics, ROC, confusion, embedding map), Edge Deploy, Attack Lab, Devices, Hardware | `frontend/src/*` |
| 12 | CLI tools: capture, synthetic dataset, train, evaluate, export | `tools/*.py` |
| 13 | Tests: DSP, C parity, simulator, ML smoke, API, end-to-end sim | `tests/*` |
| 14 | Docs: README, hardware guide (BOM, wiring, antenna, calibration, experiment protocol, troubleshooting) | `README.md`, `docs/HARDWARE.md` |

Legacy SDR/IQ code moves to `legacy/` (not deleted).

### Optional low-cost hardware add-ons (recommended)
| Add-on | ≈ Cost | Why |
|---|---|---|
| 2–3 more **identical** EV1527 fobs | ₹160 each | The only credible test of *same-model* discrimination |
| 17.3 cm solid-core wire (¼-λ antenna) | ₹5 | Better SNR than the spring coil, so a cleaner slicer |
| Green + red LED, 2 × 220 Ω, active buzzer | ₹30 | Standalone accept/reject indication |
| 5 V relay module (1-ch) | ₹60 | Door-lock demo driven by on-chip auth |

---

## v2.1: fitted to the real kit (2 × ESP32, SRX882, STX882, one remote)

* **Boards either way round.** Both firmwares build for the classic ESP32 (`-e esp32dev`)
  and the ESP32-S3 (`-e esp32s3`). Same data pins (RX GPIO14, TX GPIO4); on the S3 the
  protocol is mirrored on the native USB port. Verdicts use the on-board LED (GPIO2 / RGB),
  so no extra parts are needed. The firmware reports `board` in its hello line, and the
  edge export prints the matching flash command.
* **Transmitter fixes.** Jitter now follows the RC random walk (σ ∝ √units, it was
  units^1.5). AUTO is off at boot, PING was added, and the LED lights while sending.
* **One-remote lab.** The simulator now mirrors the kit: FOB_A, plus one ESP32/STX882 node
  that plays EMU_1/EMU_2 (enrolled helpers), CLONE_A (attacker) and EMU_3 (unknown). The
  clone copies the code and T to 0.01 µs. The Capture tab drives the node
  (profile + auto, clone + auto, auto-stop).
* **Liveness (new).** A per-press cold-start clock drift check (`ml/liveness.py`), learned
  per device and active only where the training data shows it. It runs in training,
  evaluation (fingerprint-only and combined numbers), the live engine, the DB and the
  firmware (`LIVE ON|OFF`, exported `PA_LIVE_*`).
* **Fixes.** The exporter wrote invalid C literals (`0f`) for integer-valued floats.
  `next dev` (Turbopack) deadlocked on this path, so `npm run dev` now uses webpack.
* **Tools and docs.** `tools/train.py`, `tools/export_edge.py`, `README.md`,
  `docs/HARDWARE.md`, `requirements.txt` (pyserial, httpx; pyrtlsdr removed).

## v2.2: first real hardware capture

* The receiver is a classic ESP32 (D0WD-V3, CP2102). The SRX882 on GPIO14 was verified
  with a pin scan and a pull-up/pull-down test.
* The remote decodes as EV1527 with T = 334.9 µs and sync 31.07 T. The SRX882 shortens
  HIGHs by 0.32 T, and the old clock estimator locked onto 2T/3. The fix is
  `two_symbol_clock` (n = 2P/(P−ΔH)), mirrored in C, plus a regression test on the real frames.
* Real start-up drift is about −530 ± 200 ppm. The simulator's fob warm-up and turn-on
  transient are now calibrated to that. Liveness activation now requires the
  accept window to exclude zero drift (no fixed threshold).
* A 1 kHz interferer produces junk codes, so decisions now need ≥ 3 consistent frames
  (host, evaluation and firmware).
* Transmitter bug: one `rmt_write_items()` per frame left ~2.2 ms of driver latency in
  the last LOW of every frame. That corrupted codes ending in a 1 bit and left a
  software artifact on every clone. Each press is now one continuous RMT waveform
  with a closing sync HIGH. The clone then matches the remote's T to 0.01 µs.
* The simulator's edge bias is calibrated to real hardware: remote −100 µs, STX882 −24 µs.
* Real captures live in `tests/data/` (remote; node profiles and clone over the air).
