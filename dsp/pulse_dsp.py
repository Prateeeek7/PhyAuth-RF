"""
dsp/pulse_dsp.py
----------------
Pulse-timing DSP for ASK/OOK transmitters received through an SRX882 + ESP32.

A *frame* is the list of HIGH/LOW durations (nanoseconds) captured between two
inter-frame gaps. It always starts with a HIGH pulse and alternates.

Pipeline
    merge_glitches -> estimate_clock -> decode bits -> quality gate
    -> code-invariant fingerprint features + per-bit residual sequence

Every numeric step here is mirrored 1:1 in firmware/esp32_receiver/src/phyauth_dsp.c
so that the ESP32 computes the exact same features on-chip. If you change an
algorithm here, change it there too (tests/test_c_parity.py enforces this).

Why these features
    * Bit-pair period (H+L)/(nH+nL) is invariant to slicer/duty distortion, so
      the clock estimate T is insensitive to distance and RSSI.
    * EV1527-class encoders run from an RC oscillator (+/- several %), so T and
      its cycle jitter differ strongly between units. A crystal-clocked clone
      can copy T but not RC jitter, PA edge asymmetry or warm-up drift.
    * None of the features depend on *which* bits were sent, so the model cannot
      cheat by learning the payload code (which a clone reproduces exactly).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

# ---------------------------------------------------------------------------
# Constants (keep in sync with phyauth_dsp.h)
# ---------------------------------------------------------------------------
GLITCH_NS_DEFAULT = 80_000          # pulses shorter than this are merged
MIN_PAIRS = 12                      # minimum valid H/L bit pairs per frame
MAX_DATA_UNITS = 8                  # a data pulse longer than 8T ends the data
SYNC_UNITS = 31                     # EV1527 / PT2262 sync LOW = 31 T
MAX_PAIR_RESID_RMS = 0.08           # rms of bit-pair period error (fraction of T)
MAX_PULSE_RESID = 0.45              # each data pulse within +/-0.45 T of n*T
SEQ_LEN = 32                        # bit pairs fed to the sequence model
MAX_PULSES = 400                    # longer frames are truncated (firmware limit)
SYNC_GAP_MAX_NS = 60_000_000        # gap longer than this is "silence", not sync

FEATURE_NAMES: List[str] = [
    "clock_T_us",          # 0 estimated elementary period T
    "pair_jitter_ppm",     # 1 std of bit-period error (oscillator cycle jitter)
    "duty_short_high",     # 2 mean (H - T)/T over short highs   (edge asymmetry)
    "duty_long_high",      # 3 mean (H - nT)/T over long highs
    "high_jitter",         # 4 std of high-pulse residuals (fraction of T)
    "first_edge_resid",    # 5 residual of first HIGH (turn-on / transient)
    "drift_ppm_per_bit",   # 6 slope of bit-period error vs bit index (warm-up chirp)
    "sync_ratio",          # 7 preceding sync gap / T
    "tail_high_resid",     # 8 residual of trailing lone HIGH (sync pulse)
    "duty_short_low",      # 9 mean (L - T)/T over short lows
    "duty_long_low",       # 10 mean (L - nT)/T over long lows
]
NUM_FEATURES = len(FEATURE_NAMES)
SEQ_CHANNELS = 3  # [bit-period error (per-mil), high residual, valid mask]


@dataclass
class FrameAnalysis:
    ok: bool
    reason: str
    pulses_ns: List[int]
    clock_t_ns: float = float("nan")
    units: List[int] = field(default_factory=list)
    residuals: List[float] = field(default_factory=list)   # (w - nT)/T per pulse
    n_pairs: int = 0
    bits: List[int] = field(default_factory=list)
    code_hex: str = ""
    pair_resid_rms: float = float("nan")
    features: np.ndarray = field(default_factory=lambda: np.full(NUM_FEATURES, np.nan))
    sequence: np.ndarray = field(default_factory=lambda: np.zeros((SEQ_CHANNELS, SEQ_LEN), np.float32))

    @property
    def code(self) -> str:
        return f"{self.code_hex}/{len(self.bits)}" if self.bits else ""

    def to_dict(self) -> Dict:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "clock_t_us": None if math.isnan(self.clock_t_ns) else self.clock_t_ns / 1000.0,
            "n_pairs": self.n_pairs,
            "code": self.code,
            "pair_resid_rms": None if math.isnan(self.pair_resid_rms) else self.pair_resid_rms,
            "units": self.units,
            "residuals": [round(r, 5) for r in self.residuals],
            "features": {k: (None if math.isnan(v) else float(v))
                         for k, v in zip(FEATURE_NAMES, self.features)},
        }


# ---------------------------------------------------------------------------
# Helpers (exactly mirrored in C)
# ---------------------------------------------------------------------------

def _percentile(sorted_vals: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile on pre-sorted data (numpy 'linear')."""
    n = len(sorted_vals)
    if n == 0:
        return float("nan")
    pos = q * (n - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def _median(sorted_vals: Sequence[float]) -> float:
    return _percentile(sorted_vals, 0.5)


def _mean(vals: Sequence[float]) -> float:
    return sum(vals) / len(vals) if vals else float("nan")


def _std(vals: Sequence[float]) -> float:
    """Population standard deviation (ddof=0)."""
    if len(vals) < 2:
        return float("nan")
    m = _mean(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals))


def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


# ---------------------------------------------------------------------------
# Stage 1: glitch merge
# ---------------------------------------------------------------------------

def merge_glitches(pulses_ns: Sequence[int], glitch_ns: int = GLITCH_NS_DEFAULT) -> List[int]:
    """
    Remove sub-threshold spikes while preserving HIGH/LOW alternation.

    A glitch in the middle of a pulse splits it into three pieces
    (A, glitch, B). They are merged back into a single pulse A+glitch+B.
    A leading glitch drops the glitch and the following pulse so the frame
    still starts on a HIGH. A trailing glitch is dropped together with the
    preceding pulse for the same reason.
    """
    out: List[int] = []
    i = 0
    n = len(pulses_ns)
    while i < n:
        w = int(pulses_ns[i])
        if w < glitch_ns:
            if out and i + 1 < n:
                out[-1] += w + int(pulses_ns[i + 1])
                i += 2
                continue
            if not out:
                i += 2  # leading glitch + its partner
                continue
            # trailing glitch: drop it and the pulse before it
            out.pop()
            i += 1
            continue
        out.append(w)
        i += 1
    return out


# ---------------------------------------------------------------------------
# Stage 2: clock estimation
# ---------------------------------------------------------------------------

def two_symbol_clock(pulses_ns: Sequence[int], gap_ns: int = -1) -> float:
    """
    Distortion-invariant T for encoders whose every bit is one short and one
    long symbol in a fixed period of n units (EV1527, PT2262, HT12E, ...).

    The receiver's slicer stretches every HIGH by d and shrinks every LOW by d.
    With strong signals d reaches a third of T, and then a 3:1/1:3 frame at T
    fits a 4:2/1:5 grid at 2T/3 just as well. Two quantities do not depend on d:
        pair period        P            = n T
        long - short HIGH  dH           = (n - 2) T
    so  n = 2 P / (P - dH)  and  T = P / n.
    Weak signals distort long and short HIGHs unequally, which blurs n_est, so
    the preceding sync gap decides first when known: it is 31 T, and exactly
    one n in 3..8 puts gap * n / P within 8 % of 31.
    Returns NaN when neither the gap nor both bit values pin n down.
    """
    np_ = len(pulses_ns) // 2
    if np_ < MIN_PAIRS:
        return float("nan")
    periods = sorted(float(pulses_ns[2 * k]) + float(pulses_ns[2 * k + 1]) for k in range(np_))
    p_med = _percentile(periods, 0.5)
    if not (p_med > 0):
        return float("nan")
    ps, short_h, long_h = [], [], []
    for k in range(np_):
        h = float(pulses_ns[2 * k])
        p = h + float(pulses_ns[2 * k + 1])
        if abs(p - p_med) > 0.2 * p_med:     # sync or damaged pair
            continue
        ps.append(p)
        (short_h if h < 0.5 * p_med else long_h).append(h)
    if len(ps) < MIN_PAIRS:
        return float("nan")
    p_mean = _mean(ps)
    if gap_ns > 0:
        fits = [n for n in range(3, MAX_DATA_UNITS + 1)
                if abs(gap_ns * n / p_mean - SYNC_UNITS) <= 0.08 * SYNC_UNITS]
        if len(fits) == 1:
            return p_mean / fits[0]
    if len(short_h) < 2 or len(long_h) < 2:
        return float("nan")
    dh = _mean(long_h) - _mean(short_h)
    if not (0.0 < dh < p_mean):
        return float("nan")
    n_est = 2.0 * p_mean / (p_mean - dh)
    n = _round_half_up(n_est)
    if n < 3 or n > MAX_DATA_UNITS or abs(n_est - n) > 0.45:
        return float("nan")
    return p_mean / n


def estimate_clock(pulses_ns: Sequence[int], gap_ns: int = -1) -> float:
    """
    Least-squares estimate of the elementary period T using bit-pair periods.

    T0  = two_symbol_clock() when the frame allows it (immune to duty
          distortion); otherwise the mean of pulses near the 25th percentile
          (the short-symbol cluster).
    n_i = round(w_i / T)
    T   = sum(H+L) / sum(nH+nL)   over data pairs  (two refinement passes)
    """
    if len(pulses_ns) < 2 * MIN_PAIRS:
        return float("nan")
    t = two_symbol_clock(pulses_ns, gap_ns)
    if not (t > 0):
        s = sorted(float(v) for v in pulses_ns)
        q25 = _percentile(s, 0.25)
        near = [v for v in s if 0.5 * q25 <= v <= 1.5 * q25]
        t = _mean(near) if near else q25
    if not (t > 0):
        return float("nan")
    for _ in range(2):
        num = 0.0
        den = 0
        for k in range(len(pulses_ns) // 2):
            h = float(pulses_ns[2 * k])
            l = float(pulses_ns[2 * k + 1])
            nh = max(1, _round_half_up(h / t))
            nl = max(1, _round_half_up(l / t))
            if nh > MAX_DATA_UNITS or nl > MAX_DATA_UNITS:
                continue
            num += h + l
            den += nh + nl
        if den == 0:
            return float("nan")
        t = num / den
    return t


# ---------------------------------------------------------------------------
# Stage 3: full analysis
# ---------------------------------------------------------------------------

def analyze_frame(pulses_ns: Sequence[int],
                  gap_ns: int = -1,
                  glitch_ns: int = GLITCH_NS_DEFAULT) -> FrameAnalysis:
    """Run the full pulse DSP chain on one frame."""
    pulses = merge_glitches(list(pulses_ns)[:MAX_PULSES], glitch_ns)
    fa = FrameAnalysis(ok=False, reason="", pulses_ns=pulses)

    if len(pulses) < 2 * MIN_PAIRS:
        fa.reason = "too_few_pulses"
        return fa

    t = estimate_clock(pulses, gap_ns)
    if not (t > 0) or math.isnan(t):
        fa.reason = "clock_fit_failed"
        return fa
    fa.clock_t_ns = t

    units = [max(1, _round_half_up(w / t)) for w in pulses]

    # Bit pairs, decoded per pair: the pair period fixes the unit count n
    # (distortion cancels in H+L) and the bit is "HIGH is the long half".
    # Rounding pulses one by one fails once the slicer distortion exceeds
    # T/2, which a weak SRX882 signal reaches (0.76 T measured at 1 m).
    # Stop at the first pair containing a long (sync-like) pulse.
    bits: List[int] = []
    n_pairs_total = len(pulses) // 2
    m = 0
    for k in range(n_pairs_total):
        if units[2 * k] > MAX_DATA_UNITS or units[2 * k + 1] > MAX_DATA_UNITS:
            break
        h, l = pulses[2 * k], pulses[2 * k + 1]
        n_pair = max(2, _round_half_up((h + l) / t))
        nh = 1 if (n_pair < 3 or 2 * h < h + l) else n_pair - 1
        units[2 * k], units[2 * k + 1] = nh, n_pair - nh
        bits.append(1 if nh > n_pair - nh else 0)
        m += 1
    resid = [(w - n * t) / t for w, n in zip(pulses, units)]
    fa.units = units
    fa.residuals = resid
    pair_err = [(pulses[2 * k] + pulses[2 * k + 1]) / ((units[2 * k] + units[2 * k + 1]) * t) - 1.0
                for k in range(m)]
    high_res = [resid[2 * k] for k in range(m)]
    fa.n_pairs = m
    fa.bits = bits

    if fa.n_pairs < MIN_PAIRS:
        fa.reason = "too_few_pairs"
        return fa

    rms = math.sqrt(sum(e * e for e in pair_err) / len(pair_err))
    fa.pair_resid_rms = rms
    if rms > MAX_PAIR_RESID_RMS:
        fa.reason = "timing_inconsistent"
        return fa
    data_len = 2 * fa.n_pairs
    # Each pulse against the typical distortion of its class (short/long x
    # HIGH/LOW): a common slicer offset is a feature, a lone outlier is a
    # dropout or glitch.
    sh, lh, sl, ll = [], [], [], []
    for k in range(fa.n_pairs):
        (sh if units[2 * k] == 1 else lh).append(resid[2 * k])
        (sl if units[2 * k + 1] == 1 else ll).append(resid[2 * k + 1])
    centre = {}
    for key, vals in (("sh", sh), ("lh", lh), ("sl", sl), ("ll", ll)):
        centre[key] = _percentile(sorted(vals), 0.5) if vals else 0.0
        if abs(centre[key]) >= 1.0:
            fa.reason = "off_grid_pulse"
            return fa
    for i in range(data_len):
        key = ("s" if units[i] == 1 else "l") + ("h" if i % 2 == 0 else "l")
        if abs(resid[i] - centre[key]) > MAX_PULSE_RESID:
            fa.reason = "off_grid_pulse"
            return fa

    # Code (payload) — used only as the identity *claim*, never as a feature
    val = 0
    for b in bits:
        val = (val << 1) | b
    fa.code_hex = format(val, "0{}x".format(max(1, (len(bits) + 3) // 4)))

    # ---- features ---------------------------------------------------------
    # drift: least-squares slope of pair_err over bit index
    xm = (m - 1) / 2.0
    ym = _mean(pair_err)
    sxx = sum((i - xm) ** 2 for i in range(m))
    sxy = sum((i - xm) * (pair_err[i] - ym) for i in range(m))
    slope = sxy / sxx if sxx > 0 else 0.0

    sync_ratio = float("nan")
    if 0 < gap_ns < SYNC_GAP_MAX_NS:
        sync_ratio = gap_ns / t

    tail = float("nan")
    if len(pulses) == data_len + 1:  # a lone trailing HIGH (sync pulse)
        tail = resid[data_len]

    feats = [
        t / 1000.0,
        _std(pair_err) * 1e6,
        _mean(sh) if sh else float("nan"),
        _mean(lh) if lh else float("nan"),
        _std(high_res),
        resid[0],
        slope * 1e6,
        sync_ratio,
        tail,
        _mean(sl) if sl else float("nan"),
        _mean(ll) if ll else float("nan"),
    ]
    fa.features = np.array(feats, dtype=np.float64)

    seq = np.zeros((SEQ_CHANNELS, SEQ_LEN), dtype=np.float32)
    for k in range(min(SEQ_LEN, m)):
        seq[0, k] = pair_err[k] * 1e3
        seq[1, k] = high_res[k] * 10.0
        seq[2, k] = 1.0
    fa.sequence = seq

    fa.ok = True
    fa.reason = "ok"
    return fa


# ---------------------------------------------------------------------------
# Burst-level helpers
# ---------------------------------------------------------------------------

def frame_period_ppm(frame_durations_ns: Sequence[float], nominal_ns: float) -> float:
    """Deviation (ppm) of a measured repetition period vs a nominal period."""
    if not frame_durations_ns or nominal_ns <= 0:
        return float("nan")
    return (float(np.median(frame_durations_ns)) / nominal_ns - 1.0) * 1e6


def pulse_width_histogram(pulses_ns: Sequence[int], bin_us: float = 10.0,
                          max_us: float = 3000.0) -> Dict[str, List[float]]:
    """Histogram for the UI: helps verify symbol clustering visually."""
    if not pulses_ns:
        return {"edges_us": [], "counts": []}
    arr = np.asarray(pulses_ns, dtype=np.float64) / 1000.0
    bins = np.arange(0.0, max_us + bin_us, bin_us)
    counts, edges = np.histogram(np.clip(arr, 0, max_us), bins=bins)
    return {"edges_us": edges[:-1].tolist(), "counts": counts.tolist()}
