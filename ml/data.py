"""
ml/data.py
----------
Loading recordings, DSP analysis, leakage-safe splitting and augmentation.

Recording format (data/*.jsonl, one frame per line, written by the backend):
    {"type":"frame","seq":..,"t_us":..,"g":..,"n":..,"d":[ns..],
     "device_id":"FOB_A","session_id":"s01","distance_m":1.0,"orientation_deg":0}
Legacy v1 lines ({"device_id","intervals"}) are accepted; the session is then
taken from the filename prefix and the device from the record itself.

Splitting
    Frames from one button press are near-duplicates, so splitting is done on
    *bursts* (presses), never on individual frames:
      cross_session  every enrolled device has >= 2 sessions -> the latest
                     session of each device is the test set (default when possible);
                     every 5th earlier burst is validation
      temporal       otherwise: per device, the newest 15 % of bursts are test;
                     every 6th earlier burst is validation
    Devices that are not enrolled (attackers, unknown fobs) never appear in
    training or calibration; they are only used as zero-shot impostors in test.
"""

from __future__ import annotations

import glob
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import torch
from torch.utils.data import Dataset

from acquisition.protocol import normalize
from dsp.pulse_dsp import FEATURE_NAMES, NUM_FEATURES, SEQ_LEN, analyze_frame

logger = logging.getLogger("ml.data")
BURST_GAP_US = 300_000

# Indices of features shifted by a change of slicer threshold (channel/RSSI)
_HIGH_IDX = [FEATURE_NAMES.index(n) for n in ("duty_short_high", "duty_long_high",
                                              "first_edge_resid", "tail_high_resid")]
_LOW_IDX = [FEATURE_NAMES.index(n) for n in ("duty_short_low", "duty_long_low")]
_T_IDX = FEATURE_NAMES.index("clock_T_us")
_HJ_IDX = FEATURE_NAMES.index("high_jitter")
_DRIFT_IDX = FEATURE_NAMES.index("drift_ppm_per_bit")


@dataclass
class FrameSet:
    device_ids: List[str] = field(default_factory=list)
    sessions: List[str] = field(default_factory=list)
    bursts: List[str] = field(default_factory=list)
    codes: List[str] = field(default_factory=list)
    distances: List[float] = field(default_factory=list)
    orientations: List[float] = field(default_factory=list)
    times: List[float] = field(default_factory=list)
    feats: List[np.ndarray] = field(default_factory=list)
    seqs: List[np.ndarray] = field(default_factory=list)
    rejected: Dict[str, Dict[str, int]] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.device_ids)

    @property
    def X(self) -> np.ndarray:
        return np.stack(self.feats) if self.feats else np.zeros((0, NUM_FEATURES))

    @property
    def S(self) -> np.ndarray:
        return np.stack(self.seqs) if self.seqs else np.zeros((0, 3, SEQ_LEN), np.float32)

    def subset(self, idx: Sequence[int]) -> "FrameSet":
        out = FrameSet()
        for name in ("device_ids", "sessions", "bursts", "codes", "distances",
                     "orientations", "times", "feats", "seqs"):
            src = getattr(self, name)
            setattr(out, name, [src[i] for i in idx])
        return out

    def summary(self) -> Dict:
        per: Dict[str, Dict] = {}
        for d, s, b, c in zip(self.device_ids, self.sessions, self.bursts, self.codes):
            e = per.setdefault(d, {"frames": 0, "sessions": set(), "bursts": set(), "codes": {}})
            e["frames"] += 1
            e["sessions"].add(s)
            e["bursts"].add(b)
            e["codes"][c] = e["codes"].get(c, 0) + 1
        return {d: {"frames": e["frames"], "sessions": sorted(e["sessions"]),
                    "bursts": len(e["bursts"]),
                    "top_code": max(e["codes"], key=e["codes"].get) if e["codes"] else "",
                    "rejected": self.rejected.get(d, {})}
                for d, e in per.items()}


def load_recordings(data_dir: Path, include_legacy: bool = True) -> FrameSet:
    """Load and analyse every recording. Within each file, frames whose decoded
    code differs from the file's dominant code are dropped (another transmitter
    that happened to be active during the capture), unless no code dominates
    (rolling-code devices)."""
    fs = FrameSet()
    for fpath in sorted(glob.glob(str(Path(data_dir) / "*.jsonl"))):
        p = Path(fpath)
        file_session = p.stem.split("_", 1)[0]
        rows = []
        with open(p, "r") as f:
            for line_no, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                dev = raw.get("device_id")
                msg = normalize(dict(raw))
                if not dev or msg is None or msg.get("type") != "frame":
                    continue
                if msg.get("legacy") and not include_legacy:
                    continue
                fa = analyze_frame(msg["d"], int(msg.get("g", -1) if msg.get("g") is not None else -1))
                if not fa.ok:
                    rej = fs.rejected.setdefault(dev, {})
                    rej[fa.reason] = rej.get(fa.reason, 0) + 1
                    continue
                rows.append((line_no, raw, msg, fa))

        dominant: Dict[str, str] = {}
        by_dev: Dict[str, Counter] = {}
        for _, raw, _, fa in rows:
            by_dev.setdefault(raw["device_id"], Counter())[fa.code] += 1
        for dev, cnt in by_dev.items():
            code, n = cnt.most_common(1)[0]
            if n >= 0.5 * sum(cnt.values()):
                dominant[dev] = code

        last_t: Dict[str, float] = {}
        burst_no: Dict[str, int] = {}
        for line_no, raw, msg, fa in rows:
            dev = raw["device_id"]
            if dev in dominant and fa.code != dominant[dev]:
                rej = fs.rejected.setdefault(dev, {})
                rej["foreign_code"] = rej.get("foreign_code", 0) + 1
                continue
            session = str(raw.get("session_id") or file_session)
            t_us = msg.get("t_us")
            key = f"{p.name}:{dev}"
            if t_us is None:
                bno = line_no // 10
            else:
                prev = last_t.get(key)
                if prev is None or t_us - prev > BURST_GAP_US or t_us < prev:
                    burst_no[key] = burst_no.get(key, -1) + 1
                last_t[key] = t_us
                bno = burst_no[key]
            fs.device_ids.append(dev)
            fs.sessions.append(session)
            fs.bursts.append(f"{p.stem}#{dev}#{bno}")
            fs.codes.append(fa.code)
            fs.distances.append(_num(raw.get("distance_m")))
            fs.orientations.append(_num(raw.get("orientation_deg")))
            fs.times.append(float(t_us if t_us is not None else line_no))
            fs.feats.append(fa.features.astype(np.float64))
            fs.seqs.append(fa.sequence)
    return fs


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


@dataclass
class Splits:
    strategy: str
    train: List[int]
    val: List[int]
    test: List[int]
    impostor_test: List[int]


def make_splits(fs: FrameSet, enrolled: Sequence[str], seed: int = 42) -> Splits:
    enrolled = list(enrolled)
    sess_per_dev = {d: sorted({s for dd, s in zip(fs.device_ids, fs.sessions) if dd == d}) for d in enrolled}
    cross = len(enrolled) > 0 and all(len(v) >= 2 for v in sess_per_dev.values())

    by_dev_burst: Dict[str, Dict[str, List[int]]] = {}
    for i, (d, b) in enumerate(zip(fs.device_ids, fs.bursts)):
        by_dev_burst.setdefault(d, {}).setdefault(b, []).append(i)

    train, val, test, imp = [], [], [], []
    for d, bursts in by_dev_burst.items():
        ordered = sorted(bursts.items(), key=lambda kv: (fs.sessions[kv[1][0]], fs.times[kv[1][0]], kv[0]))
        if d not in enrolled:
            for _, idx in ordered:
                imp += idx
            continue
        if cross:
            test_sess = sess_per_dev[d][-1]
            rest = [(b, idx) for b, idx in ordered if fs.sessions[idx[0]] != test_sess]
            for b, idx in ordered:
                if fs.sessions[idx[0]] == test_sess:
                    test += idx
            # validation interleaves bursts from every training session so the
            # calibrated profiles see session-to-session drift
            for k, (_, idx) in enumerate(rest):
                (val if k % 5 == 4 else train).extend(idx)
        else:
            n = len(ordered)
            n_test = max(1, int(round(0.15 * n)))
            head = ordered[:n - n_test]
            for k, (_, idx) in enumerate(head):
                (val if k % 6 == 5 else train).extend(idx)
            for _, idx in ordered[n - n_test:]:
                test += idx
    return Splits("cross_session" if cross else "temporal", train, val, test, imp)


# ---------------------------------------------------------------------------
# Scaling + augmentation
# ---------------------------------------------------------------------------

@dataclass
class FeatureScaler:
    mean: np.ndarray
    std: np.ndarray

    @classmethod
    def fit(cls, X: np.ndarray) -> "FeatureScaler":
        mean = np.nanmean(X, axis=0)
        std = np.nanstd(X, axis=0)
        mean = np.where(np.isnan(mean), 0.0, mean)
        std = np.where(np.isnan(std) | (std < 1e-9), 1.0, std)
        return cls(mean.astype(np.float64), std.astype(np.float64))

    def transform(self, X: np.ndarray) -> np.ndarray:
        Z = (X - self.mean) / self.std
        return np.where(np.isnan(Z), 0.0, Z).astype(np.float32)

    def to_dict(self) -> Dict:
        return {"mean": self.mean.tolist(), "std": self.std.tolist()}

    @classmethod
    def from_dict(cls, d: Dict) -> "FeatureScaler":
        return cls(np.array(d["mean"]), np.array(d["std"]))


def augment(x: np.ndarray, s: np.ndarray, rng: np.random.Generator) -> Tuple[np.ndarray, np.ndarray]:
    """
    Physically motivated augmentation of one frame:
      * slicer/channel bias: HIGH residuals shift by b, LOW residuals by -b
        (what a change of distance/RSSI does to an ASK data slicer)
      * clock drift: T scales by (1 + 0.8 %) sigma. Measured on the real remote:
        -0.66 % within one afternoon (temperature in the hand, 23A battery sag).
        The clone copies T anyway, so identity must rest on the stable shape features.
      * channel noise: edge jitter scales x0.5..x2 and the per-frame drift slope
        gets extra noise. Both rise with a weaker signal (battery, distance); on the
        real remote high_jitter rose 4.5 SD on a noisy day while the duty and edge
        distortions (the hardware fingerprint) moved < 0.3 SD.
    """
    x = x.copy()
    s = s.copy()
    b = rng.normal(0.0, 0.02)
    for i in _HIGH_IDX:
        x[i] += b
    for i in _LOW_IDX:
        x[i] -= b
    x[_T_IDX] *= 1.0 + rng.normal(0.0, 0.008)
    x[_HJ_IDX] *= float(np.exp(rng.normal(0.0, 0.35)))
    x[_DRIFT_IDX] += rng.normal(0.0, 150.0)
    s[1] += 10.0 * b * s[2]
    s[0] += rng.normal(0.0, 0.05, size=s.shape[1]).astype(np.float32) * s[2]
    return x, s


class FingerprintDataset(Dataset):
    def __init__(self, X: np.ndarray, S: np.ndarray, y: np.ndarray, scaler: FeatureScaler,
                 augment_data: bool = False, seed: int = 0):
        self.X, self.S, self.y = X, S.astype(np.float32), y.astype(np.int64)
        self.scaler = scaler
        self.augment_data = augment_data
        self.rng = np.random.default_rng(seed)

    def __len__(self) -> int:
        return len(self.y)

    def __getitem__(self, i):
        x, s = self.X[i], self.S[i]
        if self.augment_data:
            x, s = augment(x, s, self.rng)
        z = self.scaler.transform(x[None, :])[0]
        return torch.from_numpy(z), torch.from_numpy(np.ascontiguousarray(s)), int(self.y[i])
