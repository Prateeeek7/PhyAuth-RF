"""
sim/rf_simulator.py
-------------------
Physics-based virtual hardware for PhyAuth-RF.

It produces *exactly* the JSON-lines protocol emitted by the ESP32 receiver
firmware (firmware/esp32_receiver/src/main.cpp), so the backend, ML pipeline and
UI run unchanged with or without boards attached. Everything produced here is
tagged as simulated in the UI; it is a development and test aid, not data.

Modelled effects
  Transmitter  : EV1527 frame structure (24 bits + 1T/31T sync), per-unit RC
                 oscillator period (+/-4 %), RC cycle jitter, PA rise/fall edge
                 asymmetry, turn-on transient, warm-up chirp, session drift
                 (temperature / battery).
  ESP32 node   : ONE physical ESP32 + STX882 (as in the real kit). Every device
                 it emulates (firmware PROFILE 1..3) and the clone share its
                 analog impairments (STX882 edge asymmetry, turn-on); only the
                 programmed timing differs. RMT timing at 100 ns ticks.
  Channel      : distance/orientation -> SNR -> slicer threshold bias, edge noise
                 and glitch probability.
  Receiver     : SRX882 AGC noise between transmissions, ISR latency jitter,
                 4.17 ns CCOUNT quantisation, firmware gap segmentation and
                 glitch merge.
"""

from __future__ import annotations

import json
import math
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional

import numpy as np

CPU_HZ = 240_000_000
TICK_NS = 1e9 / CPU_HZ

# Must match firmware defaults
FW_GAP_US = 4000
FW_GLITCH_US = 80
FW_MIN_PULSES = 16
FW_MAX_PULSES = 400


# ---------------------------------------------------------------------------
# Transmitter models
# ---------------------------------------------------------------------------

@dataclass
class TxModel:
    name: str
    code: int                       # 24-bit EV1527 code (20-bit address + 4 keys)
    t_ns: float                     # elementary period T
    cycle_jitter: float             # fractional std per period
    edge_bias_ns: float             # HIGH stretch from PA (fall delay - rise delay)
    edge_bias_long_ns: float        # extra stretch on long highs (PA heating)
    transient_ns: float             # extra width of the very first HIGH of a press
    warmup_frac: float              # fractional T offset at power-on, decays
    warmup_tau_ms: float
    session_sigma: float            # fractional T drift between sessions
    tick_ns: float = 0.0            # >0 for digitally-timed (RMT) transmitters
    kind: str = "rc_fob"
    frames_per_press: tuple = (6, 14)

    def frame_pulses(self, t_eff: float, rng: np.random.Generator,
                     first_frame: bool, t_since_on_ms: float) -> List[float]:
        """Return the ideal transmitted durations (ns) for one frame:
        [24 bits as H,L pairs] + [sync H] + [sync L]."""
        warm = 1.0 + self.warmup_frac * math.exp(-t_since_on_ms / self.warmup_tau_ms)
        units: List[int] = []
        for b in range(23, -1, -1):
            bit = (self.code >> b) & 1
            units += [3, 1] if bit else [1, 3]
        units += [1, 31]
        out: List[float] = []
        for i, u in enumerate(units):
            # integrate RC jitter per elementary cycle
            cyc = t_eff * warm * (u + rng.normal(0.0, self.cycle_jitter * math.sqrt(u)))
            if self.tick_ns > 0:
                cyc = round(cyc / self.tick_ns) * self.tick_ns + rng.normal(0, 12.5)
            if i % 2 == 0:  # HIGH: PA asymmetry
                cyc += self.edge_bias_ns + (self.edge_bias_long_ns if u >= 3 else 0.0)
                if first_frame and i == 0:
                    cyc += self.transient_ns
            else:
                cyc -= self.edge_bias_ns + (self.edge_bias_long_ns if units[i - 1] >= 3 else 0.0)
            out.append(max(cyc, 1000.0))
        return out


def make_fob(name: str, seed: int, code: Optional[int] = None) -> TxModel:
    r = np.random.default_rng(seed)
    return TxModel(
        name=name,
        code=code if code is not None else int(r.integers(0, 1 << 24)),
        t_ns=320_000.0 * (1.0 + r.normal(0, 0.04)),
        cycle_jitter=float(r.uniform(0.0015, 0.0045)),
        # Real EV1527 remote at the SRX882: HIGHs ~104 us short (oscillator keyed
        # per pulse needs time to start); varies fob to fob.
        edge_bias_ns=float(r.normal(-100_000, 15_000)),
        edge_bias_long_ns=float(r.normal(4_000, 2_500)),
        # Real remote: first HIGH distorted like all others (-0.33 T vs -0.31 T),
        # i.e. no visible turn-on stretch at SRX882 resolution.
        transient_ns=float(r.normal(-5_000, 5_000)),
        # Calibrated on a real EV1527 remote + SRX882 (5 presses): the period
        # grows by about 500 ppm over the first frames of a press.
        warmup_frac=float(r.normal(-0.0007, 0.0003)),
        warmup_tau_ms=float(r.uniform(40, 160)),
        session_sigma=0.0025,
        kind="rc_fob",
    )


class EspTxNode:
    """The single ESP32 + STX882 transmitter board. Its analog impairments are
    fixed by the hardware, whatever timing the firmware is told to send."""

    def __init__(self, seed: int = 99):
        r = np.random.default_rng(seed)
        # Real ESP32-S3 + STX882 at the SRX882: HIGHs ~24 us short.
        self.edge_bias_ns = float(r.normal(-24_000, 3_000))
        self.edge_bias_long_ns = float(r.normal(0, 800))
        self.transient_ns = float(r.uniform(5_000, 15_000))


# Firmware presets: firmware/esp32_transmitter/src/main.cpp apply_profile()
TX_PROFILES = {
    1: dict(code=0x5A3C91, t_us=318.0, jitter_ppm=2500, skew_us=18),
    2: dict(code=0x1E77C4, t_us=331.0, jitter_ppm=3500, skew_us=28),
    3: dict(code=0x9B0D2A, t_us=305.5, jitter_ppm=1800, skew_us=9),
}


def make_esp_device(name: str, node: EspTxNode, code: int, t_us: float, jitter_ppm: float = 0.0,
                    skew_us: float = 0.0, kind: str = "emulated") -> TxModel:
    """What the receiver sees when the ESP32 node runs with the given settings."""
    return TxModel(
        name=name,
        code=code,
        t_ns=round(t_us * 100.0) * 10.0,            # T is sent with 0.01 us precision
        cycle_jitter=max(jitter_ppm * 1e-6, 2e-5),  # crystal floor when JITTER 0
        edge_bias_ns=node.edge_bias_ns + skew_us * 1000.0,
        edge_bias_long_ns=node.edge_bias_long_ns,
        transient_ns=node.transient_ns,
        warmup_frac=0.0,
        warmup_tau_ms=100.0,
        session_sigma=0.00002,
        tick_ns=100.0,                              # RMT resolution
        kind=kind,
    )


def make_emulated(name: str, node: EspTxNode, profile: int) -> TxModel:
    return make_esp_device(name, node, **TX_PROFILES[profile], kind="emulated")


def make_clone(name: str, target: TxModel, node: Optional[EspTxNode] = None) -> TxModel:
    """The ESP32 node in attack mode (`CLONE <code> <T>`): the victim's code and
    its measured period, crystal-clean timing (PROFILE 0)."""
    return make_esp_device(name, node or EspTxNode(), target.code, round(target.t_ns / 1000.0, 2),
                           kind="crystal_clone")


# ---------------------------------------------------------------------------
# Channel + receiver
# ---------------------------------------------------------------------------

@dataclass
class Channel:
    distance_m: float = 1.0
    orientation_deg: float = 0.0

    @property
    def snr_db(self) -> float:
        loss = 20 * math.log10(max(self.distance_m, 0.2)) + 6.0 * abs(math.sin(math.radians(self.orientation_deg)))
        return 42.0 - loss

    def slicer_bias_ns(self) -> float:
        # weak signal -> data slicer threshold sits higher on the ramp -> HIGH shrinks
        return -18_000.0 * math.exp(-(self.snr_db - 8.0) / 9.0)

    def edge_noise_ns(self) -> float:
        return 1_200.0 * 10 ** (-(self.snr_db - 20.0) / 20.0)

    def glitch_prob(self) -> float:
        return float(min(0.05, 0.0015 * 10 ** (-(self.snr_db - 18.0) / 10.0)))


@dataclass
class VirtualReceiver:
    """Turns a stream of RF level segments into firmware JSON lines."""
    seed: int = 0
    gap_us: int = FW_GAP_US
    glitch_us: int = FW_GLITCH_US
    min_pulses: int = FW_MIN_PULSES
    clock_us: float = 0.0
    seq: int = 0
    edges: int = 0
    frames: int = 0
    rejected: int = 0
    rng: np.random.Generator = field(default=None)  # type: ignore

    def __post_init__(self):
        if self.rng is None:
            self.rng = np.random.default_rng(self.seed)

    # --- noise between transmissions -------------------------------------
    def idle_noise(self, duration_ms: float) -> List[float]:
        """SRX882 AGC at max gain toggles randomly. Return LOW/HIGH segments
        (starting LOW) covering `duration_ms`."""
        segs: List[float] = []
        total = 0.0
        level_low = True
        while total < duration_ms * 1e6:
            if self.rng.random() < 0.08:
                w = self.rng.uniform(4.5e6, 25e6) if level_low else self.rng.exponential(150e3)
            else:
                w = self.rng.exponential(260e3 if level_low else 140e3) + 20e3
            segs.append(w)
            total += w
            level_low = not level_low
        if len(segs) % 2 == 0:  # end on LOW
            segs.append(5e6)
        return segs

    def segment(self, segs_low_first: List[float]) -> List[Dict]:
        """Apply receiver ISR quantisation + firmware segmentation to a level
        timeline that starts LOW. Returns firmware 'frame' dicts."""
        out: List[Dict] = []
        gap_ns = self.gap_us * 1000
        glitch_ns = self.glitch_us * 1000
        cur: List[int] = []
        prev_gap = -1
        t_ns = self.clock_us * 1000.0
        frame_t_us = 0
        for i, w in enumerate(segs_low_first):
            lat = self.rng.normal(0.0, 110.0)  # ISR latency jitter (constant part cancels)
            w_meas = max(1.0, w + lat)
            w_meas = round(w_meas / TICK_NS) * TICK_NS
            self.edges += 1
            is_low = (i % 2 == 0)
            if is_low and w_meas >= gap_ns:
                if cur:
                    self._emit(cur, prev_gap, frame_t_us, out)
                    cur = []
                prev_gap = int(w_meas) if w_meas < 1e9 else -1
            else:
                if not cur:
                    if is_low:
                        t_ns += w
                        continue
                    frame_t_us = int(t_ns / 1000)
                wi = int(w_meas)
                if wi < glitch_ns and len(cur) >= 1:
                    cur[-1] += wi  # glitch: merge with neighbour (completed below)
                    cur.append(-1)  # marker: next pulse merges too
                else:
                    if cur and cur[-1] == -1:
                        cur.pop()
                        cur[-1] += wi
                    else:
                        cur.append(wi)
                if len(cur) > FW_MAX_PULSES:
                    cur = []
                    self.rejected += 1
            t_ns += w
        self.clock_us = t_ns / 1000.0
        return out

    def _emit(self, cur: List[int], prev_gap: int, t_us: int, out: List[Dict]):
        if cur and cur[-1] == -1:
            cur.pop()
        if len(cur) < self.min_pulses:
            self.rejected += 1
            return
        self.seq += 1
        self.frames += 1
        out.append({"type": "frame", "seq": self.seq, "t_us": t_us,
                    "g": prev_gap, "n": len(cur), "d": cur})


# ---------------------------------------------------------------------------
# Scenario engine
# ---------------------------------------------------------------------------

class RFWorld:
    """
    The real kit, virtualised: one EV1527 fob + one ESP32/STX882 node + one
    ESP32/SRX882 receiver.

      FOB_A    the genuine 433 MHz remote                 (enrolled)
      EMU_1/2  ESP32 node, firmware PROFILE 1 / 2         (enrolled helpers)
      CLONE_A  ESP32 node replaying FOB_A's code and T    (attacker)
      EMU_3    ESP32 node, PROFILE 3, never enrolled      (unknown device)
    """

    def __init__(self, seed: int = 7):
        self.rng = np.random.default_rng(seed)
        fob_a = make_fob("FOB_A", 101)
        node = EspTxNode(99)
        self.tx: Dict[str, TxModel] = {
            "FOB_A": fob_a,
            "EMU_1": make_emulated("EMU_1", node, 1),
            "EMU_2": make_emulated("EMU_2", node, 2),
            "CLONE_A": make_clone("CLONE_A", fob_a, node),
            "EMU_3": make_emulated("EMU_3", node, 3),
        }
        self.channel = Channel()
        self.rx = VirtualReceiver(seed=seed + 1)
        self.session_scale: Dict[str, float] = {}
        self.new_session()

    def new_session(self) -> None:
        """Re-draw slow drift (temperature, battery) for every transmitter."""
        for k, m in self.tx.items():
            self.session_scale[k] = 1.0 + self.rng.normal(0.0, m.session_sigma)

    def press(self, name: str, frames: Optional[int] = None,
              idle_before_ms: Optional[float] = None) -> List[Dict]:
        """Simulate one button press of transmitter `name` (preceded by
        0.4-1.5 s of receiver noise, i.e. a human pause between presses)."""
        m = self.tx[name]
        if idle_before_ms is None:
            idle_before_ms = float(self.rng.uniform(400, 1500))
        n = frames or int(self.rng.integers(*m.frames_per_press))
        t_eff = m.t_ns * self.session_scale[name]
        ch = self.channel
        segs = self.rx.idle_noise(idle_before_ms)  # starts LOW, ends LOW
        # The press: preamble sync (1T high + 31T low), then frames.
        segs.append(t_eff + m.transient_ns + m.edge_bias_ns)
        segs.append(31 * t_eff - m.edge_bias_ns)
        elapsed_ms = 32 * t_eff / 1e6
        for f in range(n):
            pulses = m.frame_pulses(t_eff, self.rng, first_frame=(f == 0), t_since_on_ms=elapsed_ms)
            for i, p in enumerate(pulses):
                bias = ch.slicer_bias_ns() * (1 if i % 2 == 0 else -1)
                p = p + bias + self.rng.normal(0, ch.edge_noise_ns())
                if self.rng.random() < ch.glitch_prob() and p > 200e3:
                    a = self.rng.uniform(0.2, 0.8) * p
                    g = self.rng.uniform(15e3, 60e3)
                    segs += [a, g, p - a - g]
                else:
                    segs.append(max(p, 1000.0))
            elapsed_ms += sum(pulses) / 1e6
        segs[-1] += 30e6  # release: long silence while AGC recovers
        segs = self._merge_low_runs(segs)
        return self.rx.segment(segs)

    @staticmethod
    def _merge_low_runs(segs: List[float]) -> List[float]:
        # idle_noise ends LOW and the press starts HIGH, so alternation holds.
        return segs

    def hello(self) -> Dict:
        return {"type": "hello", "fw": "phyauth-rx", "ver": "2.1.0-sim", "clk_hz": CPU_HZ, "board": "sim",
                "gap_us": self.rx.gap_us, "glitch_us": self.rx.glitch_us,
                "min_pulses": self.rx.min_pulses, "edge_model": 0, "sim": True}

    def stats(self) -> Dict:
        return {"type": "stats", "up_ms": int(self.rx.clock_us / 1000), "edges": self.rx.edges,
                "frames": self.rx.frames, "rejected": self.rx.rejected, "overflow": 0,
                "noise_eps": int(4000 + self.rng.normal(0, 300)), "sim": True}


class SimulatedSerialPort:
    """
    Real-time line source that mimics a pyserial port connected to the RX node.
    Thread-safe `trigger(name)` lets the UI press virtual buttons.
    """

    DEFAULT_SCHEDULE = ["FOB_A", "EMU_1", "FOB_A", "EMU_2", "CLONE_A", "FOB_A", "EMU_3"]

    def __init__(self, world: Optional[RFWorld] = None, autoplay: bool = True,
                 schedule: Optional[List[str]] = None, interval_s: float = 2.5):
        self.world = world or RFWorld()
        self.autoplay = autoplay
        self.schedule = schedule or list(self.DEFAULT_SCHEDULE)
        self.interval_s = interval_s
        self._lines: List[str] = [json.dumps(self.world.hello())]
        self._lock = threading.Lock()
        self._pending: List[str] = []
        self._next_auto = time.time() + 0.5
        self._next_stats = time.time() + 2.0
        self._idx = 0
        self.is_open = True
        self.last_pressed: Optional[str] = None

    def flush(self) -> None:
        """Drop queued lines and pending presses (e.g. when a recording starts)."""
        with self._lock:
            self._pending.clear()
        self._lines = [ln for ln in self._lines if '"type": "frame"' not in ln]

    def trigger(self, name: str) -> None:
        with self._lock:
            self._pending.append(name)

    def set_channel(self, distance_m: float, orientation_deg: float) -> None:
        self.world.channel = Channel(distance_m, orientation_deg)

    def _press_lines(self, name: str) -> List[str]:
        self.last_pressed = name
        frames = self.world.press(name)
        return [json.dumps(f) for f in frames]

    def readline(self) -> bytes:
        while self.is_open:
            if self._lines:
                return (self._lines.pop(0) + "\n").encode()
            now = time.time()
            with self._lock:
                pending = self._pending.pop(0) if self._pending else None
            if pending:
                self._lines += self._paced(self._press_lines(pending))
                continue
            if self.autoplay and now >= self._next_auto:
                name = self.schedule[self._idx % len(self.schedule)]
                self._idx += 1
                self._next_auto = now + self.interval_s
                self._lines += self._paced(self._press_lines(name))
                continue
            if now >= self._next_stats:
                self._next_stats = now + 2.0
                return (json.dumps(self.world.stats()) + "\n").encode()
            time.sleep(0.02)
        return b""

    @staticmethod
    def _paced(lines: List[str]) -> List[str]:
        # Frames of a real press arrive ~40 ms apart; a tiny sleep per frame in
        # readline would complicate shutdown, so the hub tolerates bursts.
        return lines

    def write(self, data: bytes) -> int:
        return len(data)

    def close(self) -> None:
        self.is_open = False


# ---------------------------------------------------------------------------
# Offline dataset generation
# ---------------------------------------------------------------------------

def generate_dataset_lines(device_names: List[str], presses_per_device: int,
                           sessions: int, seed: int = 7,
                           distances=(1.0, 3.0), orientations=(0.0, 90.0)) -> Iterator[Dict]:
    """Yield labelled records in the on-disk recording format."""
    world = RFWorld(seed=seed)
    for s in range(sessions):
        world.new_session()
        session_id = f"sim_s{s + 1:02d}"
        for name in device_names:
            for p in range(presses_per_device):
                d = distances[p % len(distances)]
                o = orientations[(p // len(distances)) % len(orientations)]
                world.channel = Channel(d, o)
                for fr in world.press(name):
                    yield {**fr, "device_id": name, "session_id": session_id,
                           "distance_m": d, "orientation_deg": o, "simulated": True}


if __name__ == "__main__":  # quick manual check
    w = RFWorld()
    for fr in w.press("FOB_A")[:3]:
        print(fr["n"], fr["g"], fr["d"][:8])
