# PhyAuth-RF

Physical-layer authentication of 433 MHz remotes with two ESP32 boards, an
SRX882 receiver and an STX882 transmitter.

A fixed-code remote can be recorded and replayed by anyone. PhyAuth-RF treats
the decoded code only as a *claim*. It accepts the press only if the
**physical fingerprint** of the transmitter matches, with a per-press
**liveness** check on top:

* **Fingerprint**: 11 code-independent timing impairments measured at 4.17 ns
  resolution: clock period, per-bit jitter, PA edge asymmetry and duty
  distortion, turn-on transient, in-frame drift. These are embedded by a tiny
  MLP and compared with a Mahalanobis profile per device.
* **Liveness**: a battery remote starts from cold on every press, so its clock
  drifts over the first frames. An always-on crystal transmitter (the clone)
  does not. The check is learned per device and switches on only where the data shows it.
* Verdicts per press: **AUTHENTIC**, **SPOOF SUSPECTED** (right code, wrong
  hardware), **UNKNOWN DEVICE**.
* The same decision runs **on the ESP32 itself** after a one-click export
  (about 7 KB of weights), with the verdict on the on-board LED.

```
remote / ESP32+STX882 ──433 MHz──► SRX882 ─► ESP32 receiver ──USB 921600──► FastAPI ──WS──► Next.js dashboard
                                             (edge decision + LED)          (DSP, ML, DB)
```

## Hardware

Two ESP32 boards (classic or S3, either way round), one SRX882, one STX882 and
one fixed-code 433 MHz remote. See **[docs/HARDWARE.md](docs/HARDWARE.md)**
for wiring, flashing order, the one-remote lab protocol and troubleshooting.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

```bash
python -m backend.main
```

```bash
npm --prefix frontend install
```

```bash
npm --prefix frontend run dev
```

Open http://localhost:3000. With no receiver plugged in, the backend starts a
**virtual RF lab** that mirrors the real kit (FOB_A, EMU_1..3, CLONE_A). Its
data is clearly labelled SIMULATED everywhere. Plug in the receiver and connect
it in the Hardware tab to switch to real data.

Flash the receiver first (it shows your remote's frames on its own), then the transmitter:

```bash
cd firmware/esp32_receiver && pio run -e esp32s3 -t upload
```

```bash
cd firmware/esp32_transmitter && pio run -e esp32dev -t upload
```

(Swap `esp32s3` / `esp32dev` to match which chip carries which radio.)

## Dashboard

| Tab | What it does |
|---|---|
| Live | Per-press verdict, score, start-up drift, decoded pulse train and residuals |
| Capture | Code-locked recording; buttons that drive the ESP32 transmitter node |
| Signal analysis | Live pulse-width histogram, clock period per frame, decoded frame, fingerprint features |
| Model lab | Train both models; held-out ROC/EER/FAR/FRR, attacks, liveness, feature importance, embedding map |
| Edge deploy | Export the model to `phyauth_model.h`, flash command, on-chip decisions |
| Attack lab | Clone/replay attack through the transmitter node |
| Devices | Registry: enrolled, emulated, attacker and unknown devices |
| Hardware | Port discovery, receiver statistics, firmware settings, wiring |

## Command line

```bash
python -m tools.make_synthetic_dataset --out data/sim
```

```bash
python -m tools.train
```

```bash
python -m tools.export_edge
```

```bash
python -m pytest
```

The 24 tests cover the DSP, C↔Python parity of the firmware DSP, the ML pipeline end to end, liveness, the API, and decoding of the real captured frames (remote and over-the-air node).

## Layout

```
firmware/esp32_receiver     ISR edge timing, framing, JSON protocol, on-chip auth (C mirror of dsp/)
firmware/esp32_transmitter  RMT EV1527 encoder: profiles, clone, auto-press
dsp/pulse_dsp.py            clock fit, EV1527 decode, quality gate, 11 features
ml/                         data/splits, models, authenticator, liveness, train, evaluate, export
backend/                    FastAPI hub, routers, SQLite (auto-migrating)
sim/rf_simulator.py         physics-based virtual kit with the identical serial protocol
frontend/                   Next.js dashboard
legacy/                     the earlier SDR pipeline, kept for reference
```

## Results and honesty

**Real session s01 (2026-10-17, one day):** QC5681 EV1527 remote (ON button, code
`936768`), plus the ESP32-S3 + STX882 node as EMU_1/2/3 and a clone of the remote,
recorded from the same spots at 0.75 / 1.0 / 1.25 m. The remote gave 30 presses; each node
device gave 30 presses and 210 clean frames.
* Held-out, time-based split (one session), edge model: **60 of 60 attacker presses
  rejected** (30 clone, 30 unknown), 0 false accepts in 204 impostor comparisons.
  The genuine test was only 4 presses per device, so no FRR is quoted yet.
* Live: remote 9/10 presses AUTHENTIC (one false reject, score 1.14). Clone 6/6
  SPOOF_SUSPECTED, scores 4.4–5.6, even with the clock copied from the remote's live
  measurement. On-chip decisions match the host's exactly (same verdicts and scores).
* Liveness: the remote drifts about −2,300 ppm per press, but with ±980 ppm spread, so the
  check correctly stays off.
* Usable link window: about 0.75–1.25 m. Closer saturates the SRX882; at 1.5 m and beyond,
  the short pulses are lost.
* Still needed before claiming generalisation: a second session (s02) on another day,
  which enables the cross-session split.

**First real capture** (classic ESP32 + SRX882, one EV1527 remote, 5 presses;
kept as a regression test in `tests/data/`):
* The remote decodes as a fixed 24-bit code, with **T = 334.9 µs** and a sync gap of
  exactly **31.07 T**, textbook EV1527.
* The SRX882 shortens every HIGH by about 107 µs (0.32 T). This exposed and fixed a
  clock-estimation bug: the decoder now uses a distortion-invariant estimator,
  in Python and in the firmware.
* Start-up drift is real but small, about **−530 ± 200 ppm** per press, against
  the simulator's earlier assumption of about 11,000 ppm. The simulator is now
  calibrated to this. With so weak a drift the liveness check will likely stay off for
  this remote, and the fingerprint decides alone.
* **Over the air (ESP32-S3 + STX882 → SRX882):** every firmware profile decodes
  80/80 frames with the programmed code and T. The clone reproduces the remote's
  code and clock to 0.01 µs (clock separation 0.2σ). The two still differ in pulse
  distortion: the remote's HIGHs arrive ~104 µs short, the STX882's ~24 µs short
  (19–29σ apart). A fob keys its oscillator per pulse, and it needs time to start.
  *Caveat:* the two were captured at different positions, and signal strength also
  shifts SRX882 distortion. Confirm with alternating recordings from the same spot.
* A 1 kHz crystal-timed interferer (T = 1.000 ms, likely USB or the laptop) shows up
  as junk codes. Code-lock and the 3-consistent-frames rule keep it out of
  recordings and decisions.

* All numbers produced so far come from the **simulator**. On the simulated kit
  the edge model rejects 100% of clone and unknown-device presses with 0% false
  rejects of the genuine remote. The simulator models the effects the detector
  looks for, so this shows that the pipeline works end to end, **not** that the
  hardware will behave this way. Quote only results from real recordings in
  the report (the dashboard marks simulated reports).
* The liveness check switches on only if a device's drift window excludes zero
  (what a crystal transmitter shows). Model Lab shows the learned values.
* The SRX882 outputs only digital edges, so amplitude, carrier offset and
  rise-time shape are invisible. Everything the system uses is timing. A
  capable adversary who can measure and reproduce a victim's timing statistics
  is outside what a timing-only receiver can guarantee to stop. State this as
  a limitation; an SDR front end would be the next step.
* The two ESP32-emulated enrolled devices share one physical STX882. They give
  training its classes, but they are not independent hardware. A second real
  remote is the cheapest upgrade.

`About.txt`, `about.md` and `Remaining_Work.txt` are the original proposal and
notes. `PLAN.md` is the audit and work plan behind this version.
