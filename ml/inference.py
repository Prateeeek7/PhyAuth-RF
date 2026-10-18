"""
ml/inference.py
---------------
Live authentication engine used by the backend.

Per frame
    DSP analysis -> quality gate -> embedding (active model) -> claim:
      * decoded code belongs to an authorized device -> verify against it
      * otherwise -> identify: nearest authorized profile, then verify
Per button press (burst)
    median normalised distance of the first N frames -> one decision:
      AUTHENTIC        fingerprint matches the claimed (or identified) device
      SPOOF_SUSPECTED  code of an authorized device, wrong physical fingerprint
      UNKNOWN_DEVICE   neither the code nor the fingerprint is enrolled
    plus the start-up drift liveness check (ml/liveness.py) for devices whose
    training presses showed one: a press without it is rejected even when the
    fingerprint matches.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
import torch

import config
from dsp.pulse_dsp import FEATURE_NAMES, analyze_frame
from ml import liveness as lv
from ml.authenticator import OpenSetAuthenticator
from ml.data import FeatureScaler
from ml.train import BUNDLE_FILE, MODEL_FILES, REPORT_FILE, build_model

logger = logging.getLogger("ml.inference")


@dataclass
class Burst:
    key: str
    code: str
    started: float
    last: float
    claimed: Optional[str]
    claim_source: str
    scores: List[float] = field(default_factory=list)
    dists: List[float] = field(default_factory=list)
    nearest: List[str] = field(default_factory=list)
    clock_us: List[float] = field(default_factory=list)
    decided: bool = False
    wall: float = field(default_factory=time.time)   # host time of the last frame


class InferenceEngine:
    def __init__(self, ckpt_dir: Path = config.CHECKPOINT_DIR):
        self.ckpt_dir = Path(ckpt_dir)
        self.lock = threading.Lock()
        self.models: Dict[str, torch.nn.Module] = {}
        self.auths: Dict[str, OpenSetAuthenticator] = {}
        self.scaler: Optional[FeatureScaler] = None
        self.classes: List[str] = []
        self.active: str = "edge"
        self.version: Optional[str] = None
        self.code_owner: Dict[str, str] = {}
        self.authorized: Set[str] = set()
        self.threshold_scale = 1.0
        self.liveness: Dict[str, Dict] = {}
        self.liveness_enabled = config.LIVENESS_CHECK
        self.burst: Optional[Burst] = None
        self.load()

    # ---- model management -----------------------------------------------------
    @property
    def ready(self) -> bool:
        return self.scaler is not None and self.active in self.models

    def load(self) -> bool:
        bundle_path = self.ckpt_dir / BUNDLE_FILE
        with self.lock:
            self.models, self.auths, self.scaler, self.version = {}, {}, None, None
            if not bundle_path.exists():
                logger.info("no trained model bundle in %s", self.ckpt_dir)
                return False
            try:
                bundle = json.loads(bundle_path.read_text())
                self.classes = bundle["classes"]
                self.scaler = FeatureScaler.from_dict(bundle["scaler"])
                for kind, fname in MODEL_FILES.items():
                    ck = torch.load(self.ckpt_dir / fname, map_location="cpu", weights_only=True)
                    m = build_model(kind, len(self.classes))
                    m.load_state_dict(ck["state_dict"])
                    m.eval()
                    self.models[kind] = m
                    self.auths[kind] = OpenSetAuthenticator.from_dict(bundle["auth"][kind])
                self.active = bundle.get("active_model", "edge")
                self.liveness = bundle.get("liveness", {})
                self.version = bundle.get("version")
                self._set_scale(self.threshold_scale)
                logger.info("loaded model bundle %s (active=%s, classes=%s)", self.version, self.active, self.classes)
                return True
            except Exception as exc:
                logger.exception("failed to load model bundle: %s", exc)
                self.models, self.auths, self.scaler = {}, {}, None
                return False

    def _set_scale(self, scale: float) -> None:
        self.threshold_scale = scale
        for a in self.auths.values():
            a.threshold_scale = scale

    def set_threshold_scale(self, scale: float) -> None:
        with self.lock:
            self._set_scale(float(min(max(scale, 0.5), 2.0)))

    def set_liveness(self, enabled: bool) -> None:
        with self.lock:
            self.liveness_enabled = bool(enabled)

    def set_active(self, kind: str) -> None:
        if kind not in MODEL_FILES:
            raise ValueError(kind)
        with self.lock:
            self.active = kind

    def set_registry(self, authorized: Set[str], codes: Dict[str, str]) -> None:
        """codes: device_id -> decoded code string (e.g. '4f6d97/24')."""
        with self.lock:
            self.authorized = set(authorized)
            self.code_owner = {c: d for d, c in codes.items() if c and d in self.authorized}

    def info(self) -> Dict:
        report = None
        rp = self.ckpt_dir / REPORT_FILE
        if rp.exists():
            try:
                report = json.loads(rp.read_text()).get("meta")
            except Exception:
                report = None
        return {"ready": self.ready, "version": self.version, "active_model": self.active,
                "classes": self.classes, "threshold_scale": self.threshold_scale,
                "liveness_enabled": self.liveness_enabled, "liveness": self.liveness,
                "thresholds": {k: {d: p["threshold"] for d, p in a.profiles.items()} for k, a in self.auths.items()},
                "meta": report}

    # ---- inference ------------------------------------------------------------
    def _embed(self, feats: np.ndarray, seq: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        z = torch.from_numpy(self.scaler.transform(feats[None, :]))
        s = torch.from_numpy(seq[None].astype(np.float32))
        with torch.no_grad():
            e, logits = self.models[self.active](z, s)
        probs = torch.softmax(logits[0], 0).numpy()
        return e[0].numpy(), probs

    def process(self, msg: Dict) -> Tuple[Dict, Optional[Dict]]:
        """Analyse one frame. Returns (frame_event, decision_event_or_None)."""
        fa = analyze_frame(msg["d"], int(msg.get("g", -1) if msg.get("g") is not None else -1))
        t = (msg["t_us"] / 1e6) if msg.get("t_us") is not None else msg.get("rx_time", time.time())
        ev: Dict = {
            "type": "frame",
            "seq": msg.get("seq"),
            "t": t,
            "rx_time": msg.get("rx_time", time.time()),
            "n": len(fa.pulses_ns),
            "pulses_us": [round(p / 1000.0, 3) for p in fa.pulses_ns[:120]],
            "ok": fa.ok,
            "quality": fa.reason,
            "code": fa.code,
            "clock_t_us": None if math.isnan(fa.clock_t_ns) else round(fa.clock_t_ns / 1000.0, 4),
            "pair_resid_rms": None if math.isnan(fa.pair_resid_rms) else fa.pair_resid_rms,
            "units": fa.units[:120],
            "residuals": [round(r, 4) for r in fa.residuals[:120]],
            "features": {k: (None if np.isnan(v) else round(float(v), 6)) for k, v in zip(FEATURE_NAMES, fa.features)},
            "gap_us": None if (msg.get("g") or -1) < 0 else round(msg["g"] / 1000.0, 1),
        }
        decision = None
        with self.lock:
            decision = self._flush_if_stale(t)
            if not fa.ok or not self.ready:
                return ev, decision
            emb, probs = self._embed(fa.features, fa.sequence)
            auth = self.auths[self.active]
            candidates = [d for d in auth.devices() if d in self.authorized] or []
            claimed = self.code_owner.get(fa.code)
            claim_source = "code"
            if claimed and claimed in auth.profiles:
                dist = auth.distance(claimed, emb)
                score = dist / auth.threshold(claimed)
            else:
                claimed, claim_source = None, "fingerprint"
                best, score, dist = None, float("inf"), float("inf")
                for d in candidates:
                    dd = auth.distance(d, emb)
                    sc = dd / auth.threshold(d)
                    if sc < score:
                        best, score, dist = d, sc, dd
                claimed = best
            top = int(np.argmax(probs))
            ev.update({
                "claimed": claimed, "claim_source": claim_source,
                "distance": round(float(dist), 4), "score": round(float(score), 4),
                "frame_accept": bool(score <= 1.0),
                "predicted": self.classes[top], "confidence": round(float(probs[top]), 4),
                "probs": {c: round(float(p), 4) for c, p in zip(self.classes, probs)},
                "model": self.active,
            })
            d2 = self._update_burst(t, fa.code, claimed, claim_source, score, dist, self.classes[top],
                                    fa.clock_t_ns / 1000.0)
            decision = decision or d2
        return ev, decision

    def _update_burst(self, t, code, claimed, src, score, dist, nearest, clock_us) -> Optional[Dict]:
        b = self.burst
        if b is None or b.code != code or t - b.last > config.BURST_GAP_S or t < b.last:
            b = self.burst = Burst(key=f"{code}@{t:.3f}", code=code, started=t, last=t,
                                   claimed=claimed, claim_source=src)
        b.last = t
        b.wall = time.time()
        if b.decided:
            return None
        b.scores.append(score)
        b.dists.append(dist)
        b.nearest.append(nearest)
        b.clock_us.append(clock_us)
        if len(b.scores) >= config.BURST_DECISION_FRAMES:
            return self._decide(b)
        return None

    def _flush_if_stale(self, now: float) -> Optional[Dict]:
        b = self.burst
        if b and not b.decided and now - b.last > config.BURST_GAP_S and len(b.scores) >= config.BURST_MIN_FRAMES:
            return self._decide(b)
        return None

    def tick(self) -> Optional[Dict]:
        """Called periodically: decide presses that ended with fewer than N frames."""
        with self.lock:
            b = self.burst
            if b is None or b.decided or len(b.scores) < config.BURST_MIN_FRAMES:
                return None
            if time.time() - b.wall > config.BURST_GAP_S * 2:
                return self._decide(b)
            return None

    def _decide(self, b: Burst) -> Dict:
        b.decided = True
        med = float(np.median(b.scores))
        drift = lv.press_drift_ppm(b.clock_us)
        alive = lv.check(self.liveness.get(b.claimed or ""), drift) if self.liveness_enabled else None
        ok = med <= 1.0 and alive is not False
        if b.claim_source == "code":
            verdict = "AUTHENTIC" if ok else "SPOOF_SUSPECTED"
        else:
            verdict = "AUTHENTIC" if ok else "UNKNOWN_DEVICE"
        return {
            "type": "decision",
            "time": time.time(),
            "verdict": verdict,
            "code": b.code,
            "claimed": b.claimed,
            "claim_source": b.claim_source,
            "score": round(med, 4),
            "distance": round(float(np.median(b.dists)), 4),
            "frames": len(b.scores),
            "fingerprint_ok": med <= 1.0,
            "drift_ppm": None if drift is None else round(drift, 1),
            "liveness": None if alive is None else ("ok" if alive else "no start-up drift"),
            "predicted": max(set(b.nearest), key=b.nearest.count) if b.nearest else None,
            "clock_t_us": round(float(np.median(b.clock_us)), 4) if b.clock_us else None,
            "model": self.active,
            "model_version": self.version,
        }
