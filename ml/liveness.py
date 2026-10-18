"""
ml/liveness.py
--------------
Press-level "cold start" liveness check.

A key fob is unpowered until its button is pressed, so every press starts its
RC oscillator (and loads its coin cell) from cold: the clock period of the
first frames drifts while the oscillator settles. An always-powered,
crystal-clocked transmitter (an ESP32 node replaying a code) shows no such
start-up drift.

Per press we measure

    drift_ppm = (T[first frame] - T[last frame]) / T[last frame] * 1e6

over the first BURST_DECISION_FRAMES good frames with the press's code (the
same frames the fingerprint decision uses). Each enrolled device gets a
profile (median, robust sd) learned from its training presses. The check is
switched on for a device only when its accept window (median +/- 5 sd)
excludes zero drift, i.e. the drift is large and repeatable enough that a
crystal transmitter could not pass; other devices are never judged by it.
First real capture (one EV1527 remote, 5 presses): about -530 ppm, +/- 200
ppm between presses, so the check may well stay off for a given remote. The
report shows the learned profile per device.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Sequence

import numpy as np

import config
from dsp.pulse_dsp import FEATURE_NAMES

CLOCK_IDX = FEATURE_NAMES.index("clock_T_us")
MIN_PRESSES = 10          # presses needed to learn a profile
TOLERANCE_SD = 5.0        # accept drift within median +/- 5 sd ...
TOLERANCE_FLOOR_PPM = 400.0  # ... but never tighter than this
CRYSTAL_MARGIN_PPM = 300.0   # the accept window must miss zero drift (a crystal
                             # transmitter) by at least this much to activate


def press_drift_ppm(clock_us: Sequence[float], frames: int = config.BURST_DECISION_FRAMES) -> Optional[float]:
    """Start-up drift of one press, or None when the press has too few frames."""
    t = [float(x) for x in clock_us[:frames] if x and np.isfinite(x)]
    if len(t) < frames or t[-1] <= 0:
        return None
    return (t[0] - t[-1]) / t[-1] * 1e6


def burst_drifts(fs, idx: Sequence[int]) -> Dict[str, List[float]]:
    """Drift of every complete press in `idx`, grouped by device."""
    groups: Dict[str, List[int]] = defaultdict(list)
    for i in idx:
        groups[fs.bursts[i]].append(i)
    out: Dict[str, List[float]] = defaultdict(list)
    X = fs.X
    for members in groups.values():
        members.sort(key=lambda i: fs.times[i])
        d = press_drift_ppm(X[members, CLOCK_IDX])
        if d is not None:
            out[fs.device_ids[members[0]]].append(d)
    return out


def fit_profiles(fs, idx: Sequence[int], classes: Sequence[str]) -> Dict[str, Dict]:
    drifts = burst_drifts(fs, idx)
    prof: Dict[str, Dict] = {}
    for c in classes:
        v = np.asarray(drifts.get(c, []), float)
        if len(v) < MIN_PRESSES:
            prof[c] = {"active": False, "n": int(len(v)), "reason": "too few complete presses"}
            continue
        med = float(np.median(v))
        sd = float(1.4826 * np.median(np.abs(v - med))) or float(np.std(v))
        sd = max(sd, 1.0)
        tol = max(TOLERANCE_SD * sd, TOLERANCE_FLOOR_PPM)
        active = abs(med) - tol >= CRYSTAL_MARGIN_PPM
        prof[c] = {
            "active": bool(active), "n": int(len(v)), "median_ppm": round(med, 1), "sd_ppm": round(sd, 1),
            "tolerance_ppm": round(tol, 1),
            "reason": "clear start-up drift" if active else "no consistent start-up drift",
        }
    return prof


def check(profile: Optional[Dict], drift: Optional[float]) -> Optional[bool]:
    """True = alive, False = no start-up drift (replayed), None = not applicable."""
    if not profile or not profile.get("active") or drift is None:
        return None
    return abs(drift - profile["median_ppm"]) <= profile["tolerance_ppm"]
