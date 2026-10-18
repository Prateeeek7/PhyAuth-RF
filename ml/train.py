"""
ml/train.py
-----------
End-to-end training pipeline.

    recordings -> DSP features -> burst-level split -> train FingerprintNet and
    EdgeMLP (cross-entropy + batch-hard triplet, physical augmentation, early
    stopping) -> calibrate Mahalanobis profiles on validation -> evaluate on
    held-out test (+ zero-shot attackers) -> save artifacts + report.

CLI:  python -m tools.train  (see tools/train.py)
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, WeightedRandomSampler

import config
from dsp.pulse_dsp import FEATURE_NAMES
from ml import liveness as lv
from ml.authenticator import OpenSetAuthenticator
from ml.data import FeatureScaler, FingerprintDataset, FrameSet, load_recordings, make_splits
from ml.loss import BatchHardTripletLoss
from ml.models import EdgeMLP, FingerprintNet, count_parameters

logger = logging.getLogger("ml.train")

ProgressCb = Callable[[Dict], None]
MODEL_FILES = {"fusion": "fingerprint_net.pt", "edge": "edge_mlp.pt"}
BUNDLE_FILE = "bundle.json"
REPORT_FILE = "report.json"


def build_model(kind: str, num_classes: int) -> nn.Module:
    if kind == "fusion":
        return FingerprintNet(num_classes, embedding_dim=config.EMBEDDING_DIM)
    return EdgeMLP(num_classes, hidden=config.EDGE_HIDDEN, embedding_dim=config.EDGE_EMBEDDING_DIM)


@torch.no_grad()
def embed(model: nn.Module, X: np.ndarray, S: np.ndarray, scaler: FeatureScaler) -> np.ndarray:
    model.eval()
    if len(X) == 0:
        return np.zeros((0, model.embedding_dim), np.float32)
    z = torch.from_numpy(scaler.transform(X))
    s = torch.from_numpy(S.astype(np.float32))
    out = []
    for i in range(0, len(z), 512):
        e, _ = model(z[i:i + 512], s[i:i + 512])
        out.append(e.numpy())
    return np.concatenate(out)


@torch.no_grad()
def predict_logits(model: nn.Module, X: np.ndarray, S: np.ndarray, scaler: FeatureScaler) -> np.ndarray:
    model.eval()
    if len(X) == 0:
        return np.zeros((0, 0))
    _, logits = model(torch.from_numpy(scaler.transform(X)), torch.from_numpy(S.astype(np.float32)))
    return logits.numpy()


def _train_one(kind: str, num_classes: int, train_ds, val_ds, epochs: int, lr: float,
               batch_size: int, progress: Optional[ProgressCb]) -> nn.Module:
    torch.manual_seed(0)
    model = build_model(kind, num_classes)
    counts = np.bincount(train_ds.y, minlength=num_classes).astype(np.float64)
    weights = 1.0 / np.maximum(counts[train_ds.y], 1.0)
    sampler = WeightedRandomSampler(weights, num_samples=max(len(train_ds), batch_size * 8), replacement=True)
    train_loader = DataLoader(train_ds, batch_size=batch_size, sampler=sampler, drop_last=True)
    val_loader = DataLoader(val_ds, batch_size=512, shuffle=False)

    ce = nn.CrossEntropyLoss(label_smoothing=0.05)
    triplet = BatchHardTripletLoss(margin=0.3)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)

    best_state, best_val, patience, bad = None, float("inf"), 12, 0
    for epoch in range(1, epochs + 1):
        model.train()
        tl, nb = 0.0, 0
        for z, s, y in train_loader:
            opt.zero_grad()
            emb, logits = model(z, s)
            loss = ce(logits, y) + triplet(emb, y)
            loss.backward()
            opt.step()
            tl += loss.item()
            nb += 1
        sched.step()

        model.eval()
        vl, correct, total = 0.0, 0, 0
        with torch.no_grad():
            for z, s, y in val_loader:
                emb, logits = model(z, s)
                vl += (ce(logits, y) + triplet(emb, y)).item() * len(y)
                correct += (logits.argmax(1) == y).sum().item()
                total += len(y)
        vl /= max(total, 1)
        acc = correct / max(total, 1)
        if progress:
            progress({"stage": f"train_{kind}", "epoch": epoch, "total_epochs": epochs,
                      "train_loss": tl / max(nb, 1), "val_loss": vl, "val_accuracy": acc})
        if vl < best_val - 1e-4:
            best_val, bad = vl, 0
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= patience:
                break
    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    return model


def calibrate(model: nn.Module, fs: FrameSet, idx_val: List[int], classes: List[str],
              scaler: FeatureScaler, target_frr: float) -> OpenSetAuthenticator:
    auth = OpenSetAuthenticator(shrinkage=0.1)
    X, S = fs.X[idx_val], fs.S[idx_val]
    dev = np.array([fs.device_ids[i] for i in idx_val])
    E = embed(model, X, S, scaler)
    for c in classes:
        pos = E[dev == c]
        if len(pos) < 5:
            logger.warning("not enough validation frames to calibrate %s (%d)", c, len(pos))
            continue
        auth.calibrate_device(c, pos, target_frr=target_frr, impostor_embeddings=E[dev != c],
                              margin=config.THRESHOLD_MARGIN)
    return auth


def validation_eer(model: nn.Module, auth: OpenSetAuthenticator, fs: FrameSet, idx_val: List[int],
                   scaler: FeatureScaler) -> float:
    """EER on validation (enrolled devices only); used to pick the runtime model
    without looking at the test set."""
    from ml.evaluate import _roc
    E = embed(model, fs.X[idx_val], fs.S[idx_val], scaler)
    dev = np.array([fs.device_ids[i] for i in idx_val])
    gen, imp = [], []
    for c in auth.devices():
        s = auth._dist(c, E) / auth.profiles[c]["threshold"]
        gen += s[dev == c].tolist()
        imp += s[dev != c].tolist()
    eer = _roc(np.array(gen), np.array(imp))["eer"]
    return 1.0 if eer is None else eer


def _pick_active(val_eers: Dict[str, float]) -> str:
    # The runtime default is the physical-feature EdgeMLP, the same model that
    # runs on the ESP32. Validation cannot reveal shortcut learning that only a
    # code-replicating clone exposes (the sequence/fusion model can score
    # better on validation yet accept clones), so validation EER is reported
    # but not used to switch models. The fusion model stays selectable in the UI.
    return "edge"


def train_pipeline(data_dir: Path, out_dir: Path, enrolled: Sequence[str],
                   device_codes: Optional[Dict[str, str]] = None,
                   epochs: int = None, lr: float = None, batch_size: int = None,
                   target_frr: float = None,
                   progress: Optional[ProgressCb] = None) -> Dict:
    from ml.evaluate import evaluate  # local import to avoid a cycle

    epochs = epochs or config.EPOCHS
    lr = lr or config.LEARNING_RATE
    batch_size = batch_size or config.BATCH_SIZE
    target_frr = target_frr or config.TARGET_FRR
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    if progress:
        progress({"stage": "loading", "epoch": 0, "total_epochs": epochs})
    fs = load_recordings(Path(data_dir))
    present = set(fs.device_ids)
    classes = [d for d in enrolled if d in present]
    if len(classes) < 2:
        raise ValueError(
            f"Need recordings of at least 2 enrolled (authorized) devices; found {classes or 'none'}. "
            f"Devices with usable frames: {sorted(present) or 'none'}. "
            "With a single real remote, record the ESP32 transmitter node in PROFILE 1 and 2 as enrolled "
            "devices (EMU_1, EMU_2) so the embedding has classes to separate.")

    splits = make_splits(fs, classes)
    cidx = {c: i for i, c in enumerate(classes)}
    y_all = np.array([cidx.get(d, -1) for d in fs.device_ids])
    for name, idx in (("train", splits.train), ("val", splits.val)):
        missing = [c for c in classes if not np.any(y_all[idx] == cidx[c])]
        if missing:
            raise ValueError(f"{name} split has no frames for {missing}; record more presses.")

    X, S = fs.X, fs.S
    scaler = FeatureScaler.fit(X[splits.train])
    train_ds = FingerprintDataset(X[splits.train], S[splits.train], y_all[splits.train], scaler, augment_data=True)
    val_ds = FingerprintDataset(X[splits.val], S[splits.val], y_all[splits.val], scaler)

    models: Dict[str, nn.Module] = {}
    auths: Dict[str, OpenSetAuthenticator] = {}
    val_eers: Dict[str, float] = {}
    for kind in ("fusion", "edge"):
        models[kind] = _train_one(kind, len(classes), train_ds, val_ds, epochs, lr, batch_size, progress)
        auths[kind] = calibrate(models[kind], fs, splits.val, classes, scaler, target_frr)
        val_eers[kind] = validation_eer(models[kind], auths[kind], fs, splits.val, scaler)
        torch.save({"state_dict": models[kind].state_dict(), "kind": kind, "classes": classes},
                   out_dir / MODEL_FILES[kind])

    # Start-up drift profiles from training + validation presses (never test)
    live = lv.fit_profiles(fs, list(splits.train) + list(splits.val), classes)

    if progress:
        progress({"stage": "evaluating", "epoch": epochs, "total_epochs": epochs})
    report = evaluate(fs, splits, classes, scaler, models, auths, device_codes or {}, live=live)
    report["meta"] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "train_seconds": round(time.time() - t0, 1),
        "classes": classes,
        "split_strategy": splits.strategy,
        "frames": {"train": len(splits.train), "val": len(splits.val), "test": len(splits.test),
                   "impostor_test": len(splits.impostor_test)},
        "dataset": fs.summary(),
        "parameters": {k: count_parameters(m) for k, m in models.items()},
        "feature_names": FEATURE_NAMES,
        "target_frr": target_frr,
        "threshold_margin": config.THRESHOLD_MARGIN,
        "validation_eer": val_eers,
        "active_model": _pick_active(val_eers),
        "simulated_data": any("sim" in s for s in fs.sessions),
    }

    bundle = {
        "version": datetime.now().strftime("%Y%m%d-%H%M%S"),
        "classes": classes,
        "scaler": scaler.to_dict(),
        "device_codes": {c: (device_codes or {}).get(c, "") for c in classes},
        "auth": {k: a.to_dict() for k, a in auths.items()},
        "active_model": _pick_active(val_eers),
        "liveness": live,
        "config": {"embedding_dim": config.EMBEDDING_DIM, "edge_hidden": config.EDGE_HIDDEN,
                   "edge_embedding_dim": config.EDGE_EMBEDDING_DIM},
    }
    (out_dir / BUNDLE_FILE).write_text(json.dumps(bundle))
    (out_dir / REPORT_FILE).write_text(json.dumps(report))
    if progress:
        progress({"stage": "done", "epoch": epochs, "total_epochs": epochs})
    return report
