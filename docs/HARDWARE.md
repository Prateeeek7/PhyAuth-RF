# PhyAuth-RF hardware guide

This guide covers the exact kit the project is built around:

| Part | Role | Approx. cost |
|---|---|---|
| ESP32 board #1 + **SRX882** (4-pin superhet receiver) | **Receiver / verifier node** | ₹350–800 + ₹150–250 |
| ESP32 board #2 + **STX882** (3-pin transmitter) | **Transmitter node**: emulated devices and the clone attacker | ₹350–800 + ₹100–200 |
| One 433 MHz remote (EV1527 / PT2262-style, fixed code) | **The genuine device** (FOB_A) | ₹100–200 |
| 2 × spring antennas (supplied) or 2 × 17.3 cm wire | ¼-wave antennas at 433.92 MHz | — |

No extra LEDs, buzzer or relay are needed. Both firmwares use the board's
on-board LED. Optional extras are listed at the end.

Both firmwares build for **either** chip (classic ESP32-WROOM-32 or ESP32-S3),
so it does not matter which board carries which radio. Pick the matching
PlatformIO environment: `-e esp32dev` for a classic ESP32, `-e esp32s3` for an ESP32-S3.

> How to tell the boards apart: the ESP32-S3 DevKitC is marked *ESP32-S3* on
> the metal can and usually has USB-C. Classic ESP32 DevKits are marked
> *ESP32-WROOM-32* and often have micro-USB. If you pick the wrong environment,
> the upload stops harmlessly with *"This chip is ESP32, not ESP32-S3"* (or the
> reverse). Switch the `-e` and upload again. After flashing, the dashboard's
> Hardware tab shows `board` from the firmware's hello line.

---

## 1. Wiring

### Receiver node: ESP32 + SRX882

| SRX882 pin | ESP32 pin | Notes |
|---|---|---|
| VCC | **3V3** | Never 5 V: DATA swings to VCC and ESP32 inputs are 3.3 V only |
| GND | GND | |
| DATA | **GPIO14** | Other pin: add `-DRX_PIN_NUM=<gpio>` to `build_flags` |
| CS | **3V3** | CS low = receiver asleep, which gives *no data at all* (most common mistake) |
| ANT | spring or 17.3 cm wire | Keep it vertical, away from the USB cable |

Same pins on both chips. GPIO14 is free on the ESP32 and on the ESP32-S3 N16R8.

### Transmitter node: ESP32 + STX882

| STX882 pin | ESP32 pin | Notes |
|---|---|---|
| VCC | **5V / VIN** | More RF power. DATA still accepts 3.3 V logic |
| GND | GND | |
| DATA | **GPIO4** | Other pin: `-DTX_PIN_NUM=<gpio>` |
| ANT | spring or 17.3 cm wire | |

The BOOT button on the transmitter board sends one button press. The on-board
LED lights while it transmits.

### Placement

* Keep transmitter and receiver **at least 50 cm apart**. The SRX882 saturates
  when closer, and saturated edges destroy the fingerprint.
* Record at **1 m, 3 m and 5 m**, and at 0° and 90° orientation, so the model
  learns hardware rather than channel.
* Keep the receiver antenna away from the laptop, USB hubs and chargers
  (433 MHz noise).

---

## 2. Flashing: receiver first

Flash the **receiver first**. It is useful on its own: with only the receiver
flashed you can already see your real remote's frames in the dashboard and
check the wiring before the second board is involved.

```bash
pip install platformio
```

**Receiver** (the board wired to the SRX882):

```bash
cd firmware/esp32_receiver
pio run -e esp32s3 -t upload        # ESP32-S3 board
pio run -e esp32dev -t upload       # classic ESP32 board
```

**Transmitter** (the board wired to the STX882):

```bash
cd firmware/esp32_transmitter
pio run -e esp32dev -t upload       # classic ESP32 board
pio run -e esp32s3 -t upload        # ESP32-S3 board
```

Arduino IDE alternative: open `esp32_receiver.ino` or `esp32_transmitter.ino`,
choose *ESP32 Dev Module* or *ESP32S3 Dev Module*, and upload.

If the upload hangs at `Connecting....`, hold **BOOT**, tap **EN/RST**, then
release BOOT.

### First check

```bash
pio device monitor -b 921600        # receiver
```

You should see a `{"type":"hello",...,"board":"esp32s3"}` line and a
`stats` line every 2 s. Press your remote near the antenna: `frame` lines
appear. If they don't, see *Troubleshooting*.

On an ESP32-S3 either USB-C port works: the firmware talks on the UART bridge
and the native USB port.

---

## 3. Lab protocol with one remote

One remote gives one genuine class, but training needs at least two classes to
learn what separates transmitters. The transmitter node fills that gap with
firmware **profiles**: the same physical STX882 with different programmed timing.

| Device ID | Hardware | Type in *Devices* | Enrolled |
|---|---|---|---|
| `FOB_A` | your remote | Genuine fob | **yes** |
| `EMU_1` | transmitter node, `PROFILE 1` | Emulated | **yes** |
| `EMU_2` | transmitter node, `PROFILE 2` | Emulated | **yes** |
| `CLONE_A` | transmitter node replaying FOB_A's code and clock | Attacker / clone | no |
| `EMU_3` | transmitter node, `PROFILE 3` | Unknown | no |

Steps (dashboard at http://localhost:3000):

1. **Hardware**: connect the receiver port at 921600 baud.
2. **Attack lab**: connect the transmitter node port at 115200 baud.
3. **Devices**: register the five devices above. Codes are learned automatically.
4. **Capture**, session `s01`, for each device:
   * `FOB_A`: keep the node silent (*Stop node*), then press the remote's
     **same button** about once a second. Release fully between presses (see the liveness section).
   * `EMU_1`, `EMU_2`, `EMU_3`: click *profile N + auto*. The node presses itself every 1.2 s.
   * `CLONE_A`: click *clone FOB_A + auto* (FOB_A must be recorded first so its code and clock are known).
   * Collect about 150 good frames per device, at 1 m, 3 m and 5 m.
5. Repeat on another day as session `s02`. Two sessions enable the
   cross-session test, which is the result worth quoting.
6. **Model lab**: train, then read the report.
7. **Live**: press the remote (expect AUTHENTIC), launch the clone from the
   Attack lab (expect SPOOF SUSPECTED), and run the `EMU_3` profile (expect UNKNOWN DEVICE).
8. **Edge deploy**: export the model, then reflash the receiver with the same
   command as in section 2. The ESP32 now decides on its own and shows the
   verdict on its LED, even on a power bank.

Command-line alternatives:

```bash
python -m tools.train
python -m tools.export_edge
```

### What the liveness check needs from you

A battery remote is unpowered until its button is pressed. Every press starts
its RC oscillator from cold, so its clock period drifts over the first frames.
The ESP32 node runs from an always-on crystal and shows no such drift. The
system learns this drift per device and rejects presses without it.

* Release the button between presses. Holding it continuously gives one long press.
* First real capture: about −530 ± 200 ppm per press, a real but weak effect.
* The check switches itself on only when a device's accept window (median ± 5 sd)
  excludes zero drift. The *Liveness* panel in Model Lab shows the learned value
  for your remote. If your remote shows little drift, the check stays off and
  the fingerprint alone decides. Report that honestly; it is a real result.

---

## 4. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| No `hello` line at all | Wrong port or baud (receiver 921600, transmitter 115200). On an ESP32-S3, try the other USB-C port. Press EN/RST. |
| `hello` but no frames when pressing the remote | SRX882 **CS not tied to 3V3**; VCC not connected; DATA not on GPIO14; no antenna. Note that an idle SRX882 can be almost silent (a few edges per second), which is normal. |
| Thousands of `noise_eps`, frames rejected `too_few_pulses` | Normal AGC noise between transmissions. Only a problem if real presses are also rejected. |
| Remote's frames rejected `timing_inconsistent` / `off_grid_pulse` every press | Too close (under 50 cm, saturation) or too far. Move to 1–3 m. |
| The code changes on every press | Rolling-code remote (KeeLoq/HCS301). Use a fixed-code EV1527/PT2262 remote. |
| Junk codes such as `0000/16` with T ≈ 1000 µs | 1 kHz interference from USB or the laptop. They are ignored, but keep the antenna away from the laptop and USB hub. |
| Code differs between recordings | Different button. Each button is a different code; use one. |
| Upload: *"This chip is ESP32 not ESP32-S3"* | Wrong environment. Use `-e esp32dev` (or the reverse). |
| Upload stuck at `Connecting...` | Hold BOOT, tap EN, release BOOT. Use a data USB cable, not a charge-only one. |
| Port missing on macOS | CP2102 or CH340 driver; try another cable. The ★ in the port list marks likely ESP32 bridges. |
| Clone not received | Transmitter node on 5V/VIN? Antenna fitted? `INFO` on the node shows the code and T it sends. |
| Dashboard dev server stuck on "Compiling /" | Use `npm run dev`, which runs webpack. `npm run dev:turbo` (Turbopack) hung on this project path. |

---

## 5. Optional add-ons

| Add-on | ESP32 pins | ESP32-S3 pins | Why |
|---|---|---|---|
| Green LED + 220 Ω | GPIO25 | GPIO5 | Separate *authentic* light |
| Red LED + 220 Ω | GPIO26 | GPIO6 | Separate *rejected* light |
| Active buzzer | GPIO27 | GPIO7 | 1 beep = authentic, 3 beeps = rejected |
| Relay module IN | GPIO33 | GPIO15 | Switch a real lock or gate on AUTHENTIC |
| A second fixed-code remote | — | — | A real (not emulated) second genuine class or unknown device |
| USB power bank | — | — | Run the receiver standalone after edge deploy |
