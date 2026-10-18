"""
ml/authenticator.py
-------------------
Open-set verification with per-device Mahalanobis profiles.

For each enrolled device we store the mean of its (L2-normalised) embeddings,
a shrinkage-regularised inverse covariance and a decision threshold. The
threshold is one-class: the (1 - target_frr) quantile of genuine validation
distances, times a drift margin. It is deliberately *not* tuned on attacker data, so the reported
spoof rejection is zero-shot and not optimistically biased.

Profiles are stored as JSON (no pickle: loading pickles can execute code).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np


def ledoit_wolf(X: np.ndarray, floor: float = 0.0) -> Tuple[np.ndarray, float]:
    """Ledoit-Wolf (2004) shrinkage covariance towards a scaled identity.
    With few calibration frames per device (tens) in 16-32 dimensions the
    sample covariance is badly conditioned; LW picks the shrinkage
    intensity analytically from the data."""
    n, d = X.shape
    Xc = X - X.mean(axis=0)
    with np.errstate(all="ignore"):  # numpy 2.0 + Accelerate: spurious matmul FP warnings
        S = Xc.T @ Xc / n
    mu = np.trace(S) / d
    F = mu * np.eye(d)
    delta2 = np.sum((S - F) ** 2) / d
    beta2 = sum(np.sum((np.outer(x, x) - S) ** 2) for x in Xc) / (n * n * d)
    alpha = float(min(1.0, max(floor, beta2 / max(delta2, 1e-18))))
    return (1 - alpha) * S + alpha * F + 1e-9 * np.eye(d), alpha


class OpenSetAuthenticator:
    def __init__(self, shrinkage: float = 0.1):
        self.shrinkage = shrinkage
        self.profiles: Dict[str, Dict] = {}
        self.threshold_scale: float = 1.0   # runtime "security level" (lower = stricter)

    # ---- calibration --------------------------------------------------------
    def calibrate_device(self, device_id: str, embeddings: np.ndarray,
                         target_frr: float = 0.03,
                         impostor_embeddings: Optional[np.ndarray] = None,
                         margin: float = 1.0) -> Dict:
        if len(embeddings) < 5:
            raise ValueError(f"{device_id}: need >= 5 calibration frames, got {len(embeddings)}")
        e = np.asarray(embeddings, dtype=np.float64)
        centroid = e.mean(axis=0)
        cov_reg, alpha = ledoit_wolf(e, floor=self.shrinkage)
        cov_inv = np.linalg.inv(cov_reg)
        prof = {"centroid": centroid, "cov_inv": cov_inv, "shrinkage": alpha}
        self.profiles[device_id] = prof
        genuine = self._dist(device_id, e)
        thr = float(np.quantile(genuine, 1.0 - target_frr)) * margin
        prof["threshold"] = thr
        prof["genuine_median"] = float(np.median(genuine))
        prof["n_calib"] = int(len(e))
        if impostor_embeddings is not None and len(impostor_embeddings):
            imp = self._dist(device_id, np.asarray(impostor_embeddings, np.float64))
            prof["calib_far"] = float(np.mean(imp <= thr))
        return prof

    # ---- scoring ------------------------------------------------------------
    def _dist(self, device_id: str, emb: np.ndarray) -> np.ndarray:
        p = self.profiles[device_id]
        diff = np.atleast_2d(emb) - p["centroid"]
        return np.sqrt(np.maximum(np.einsum("ij,jk,ik->i", diff, p["cov_inv"], diff), 0.0))

    def distance(self, device_id: str, emb: np.ndarray) -> float:
        return float(self._dist(device_id, emb)[0])

    def threshold(self, device_id: str) -> float:
        return self.profiles[device_id]["threshold"] * self.threshold_scale

    def authenticate(self, device_id: str, emb: np.ndarray) -> Tuple[bool, float, float]:
        if device_id not in self.profiles:
            return False, float("inf"), 0.0
        d = self.distance(device_id, emb)
        t = self.threshold(device_id)
        return d <= t, d, t

    def nearest(self, emb: np.ndarray) -> Tuple[Optional[str], float]:
        best, best_d = None, float("inf")
        for dev in self.profiles:
            # compare on the threshold-normalised scale so devices with tighter
            # clusters are not unfairly favoured
            d = self.distance(dev, emb) / max(self.profiles[dev]["threshold"], 1e-9)
            if d < best_d:
                best, best_d = dev, d
        return best, best_d

    def devices(self) -> List[str]:
        return list(self.profiles)

    # ---- persistence ----------------------------------------------------------
    def to_dict(self) -> Dict:
        return {"shrinkage": self.shrinkage, "profiles": {
            k: {kk: (vv.tolist() if isinstance(vv, np.ndarray) else vv) for kk, vv in v.items()}
            for k, v in self.profiles.items()}}

    @classmethod
    def from_dict(cls, d: Dict) -> "OpenSetAuthenticator":
        a = cls(d.get("shrinkage", 0.1))
        for k, v in d["profiles"].items():
            a.profiles[k] = {kk: (np.array(vv) if kk in ("centroid", "cov_inv") else vv) for kk, vv in v.items()}
        return a

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict()))

    @classmethod
    def load(cls, path: Path) -> "OpenSetAuthenticator":
        return cls.from_dict(json.loads(Path(path).read_text()))
