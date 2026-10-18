"""
ml/evaluate.py
--------------
Held-out evaluation producing the research report shown in the dashboard.

  closed_set      accuracy + confusion matrix over enrolled devices
  verification    genuine vs impostor score distributions -> ROC, AUC, EER,
                  FAR/FRR at the calibrated operating point; frame and burst level
  attacks         per non-enrolled transmitter: which device it claims (same
                  decoded code = clone/replay, otherwise nearest profile) and the
                  fraction of its presses that were rejected (zero-shot)
  by_distance     genuine FRR / accuracy per recorded TX-RX distance
  liveness        start-up drift check per press (ml/liveness.py): learned
                  profile per device, genuine FRR it adds, attacks it catches;
                  "combined" numbers = fingerprint AND liveness (= live engine)
  importance      permutation importance of each physical feature (edge model)
  embedding_map   2-D PCA of test embeddings for visual inspection
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Dict, List, Optional, Sequence

import numpy as np

from dsp.pulse_dsp import FEATURE_NAMES
from ml.authenticator import OpenSetAuthenticator
import config
from ml.data import FeatureScaler, FrameSet, Splits
from ml import liveness as lv

# Burst decisions use exactly the rule of the live engine and the firmware:
# median normalised distance of the first N frames of a press.
BURST_FRAMES = config.BURST_DECISION_FRAMES


def _roc(gen: np.ndarray, imp: np.ndarray) -> Dict:
    if len(gen) == 0 or len(imp) == 0:
        return {"eer": None, "auc": None, "far": None, "frr": None, "roc": []}
    allv = np.concatenate([gen, imp])
    grid = np.unique(np.quantile(allv, np.linspace(0, 1, 200)))
    far = np.array([np.mean(imp <= t) for t in grid])
    tar = np.array([np.mean(gen <= t) for t in grid])
    frr = 1 - tar
    k = int(np.argmin(np.abs(far - frr)))
    # AUC = P(genuine score < impostor score) (Mann-Whitney)
    order = np.argsort(allv, kind="mergesort")
    ranks = np.empty(len(allv))
    ranks[order] = np.arange(1, len(allv) + 1)
    auc = (np.sum(ranks[len(gen):]) - len(imp) * (len(imp) + 1) / 2) / (len(gen) * len(imp))
    return {
        "eer": float((far[k] + frr[k]) / 2),
        "auc": float(auc),
        "far": float(np.mean(imp <= 1.0)),   # operating point: normalised score 1 == threshold
        "frr": float(np.mean(gen > 1.0)),
        "roc": [[float(a), float(b)] for a, b in zip(far, tar)],
        "n_genuine": int(len(gen)),
        "n_impostor": int(len(imp)),
    }


def _norm_scores(auth: OpenSetAuthenticator, dev: str, E: np.ndarray) -> np.ndarray:
    if len(E) == 0:
        return np.zeros(0)
    return auth._dist(dev, E) / auth.profiles[dev]["threshold"]


def _burst_groups(fs: FrameSet, idx: Sequence[int]) -> Dict[str, List[int]]:
    g: Dict[str, List[int]] = defaultdict(list)
    for k, i in enumerate(idx):
        g[fs.bursts[i]].append(k)
    return {b: v[:BURST_FRAMES] for b, v in g.items() if len(v) >= config.BURST_MIN_FRAMES}


def _press_drift(fs: FrameSet, idx: Sequence[int], ks: Sequence[int]):
    members = sorted((idx[k] for k in ks), key=lambda i: fs.times[i])
    return lv.press_drift_ppm(fs.X[members, lv.CLOCK_IDX])


def _eval_model(model, auth: OpenSetAuthenticator, fs: FrameSet, splits: Splits, classes: List[str],
                scaler: FeatureScaler, device_codes: Dict[str, str], X_override=None,
                live: Optional[Dict[str, Dict]] = None) -> Dict:
    from ml.train import embed, predict_logits

    classes = [c for c in classes if c in auth.profiles]
    X = fs.X if X_override is None else X_override
    S = fs.S
    test, imp = splits.test, splits.impostor_test
    E_t = embed(model, X[test], S[test], scaler)
    E_i = embed(model, X[imp], S[imp], scaler)
    dev_t = np.array([fs.device_ids[i] for i in test])
    dev_i = np.array([fs.device_ids[i] for i in imp])

    # closed set
    logits = predict_logits(model, X[test], S[test], scaler)
    all_classes = list(classes)
    pred = np.array([all_classes[k] for k in logits.argmax(1)]) if len(test) else np.array([])
    labels = all_classes
    cm = [[int(np.sum((dev_t == a) & (pred == b))) for b in labels] for a in labels]
    acc = float(np.mean(pred == dev_t)) if len(test) else None

    # verification: frame level
    gen, impo = [], []
    gen_by_dist: Dict[float, List[float]] = defaultdict(list)
    for c in classes:
        m = dev_t == c
        sc = _norm_scores(auth, c, E_t[m])
        gen += sc.tolist()
        for s, i in zip(sc, np.array(test)[m]):
            gen_by_dist[fs.distances[i]].append(s)
        impo += _norm_scores(auth, c, E_t[~m]).tolist()
        impo += _norm_scores(auth, c, E_i).tolist()
    frame = _roc(np.array(gen), np.array(impo))

    # burst level
    live = live or {}
    gb, ib = [], []
    combined_rej: List[bool] = []
    for b, ks in _burst_groups(fs, test).items():
        d_true = dev_t[ks[0]]
        for c in classes:
            s = float(np.median(_norm_scores(auth, c, E_t[ks])))
            (gb if c == d_true else ib).append(s)
            if c == d_true:
                alive = lv.check(live.get(c), _press_drift(fs, test, ks))
                combined_rej.append(s > 1.0 or alive is False)
    imp_bursts = _burst_groups(fs, imp)
    for b, ks in imp_bursts.items():
        for c in classes:
            ib.append(float(np.median(_norm_scores(auth, c, E_i[ks]))))
    burst = _roc(np.array(gb), np.array(ib))

    # attacks (zero-shot, burst level)
    code_owner = {v: k for k, v in device_codes.items() if v and k in classes}
    attacks = []
    for d in sorted(set(dev_i.tolist())):
        idx_d = np.where(dev_i == d)[0]
        codes = Counter(fs.codes[imp[k]] for k in idx_d)
        top_code = codes.most_common(1)[0][0] if codes else ""
        claimed = code_owner.get(top_code)
        rejected, rejected_comb, n = 0, 0, 0
        frame_rej = []
        for b, ks in imp_bursts.items():
            if dev_i[ks[0]] != d:
                continue
            n += 1
            if claimed:
                s = _norm_scores(auth, claimed, E_i[ks])
                target = claimed
            else:
                per = np.stack([_norm_scores(auth, c, E_i[ks]) for c in classes])
                target = classes[int(np.argmin(np.median(per, axis=1)))]
                s = np.min(per, axis=0)
            frame_rej += (s > 1.0).tolist()
            fp_rej = bool(np.median(s) > 1.0)
            rejected += int(fp_rej)
            rejected_comb += int(fp_rej or lv.check(live.get(target), _press_drift(fs, imp, ks)) is False)
        attacks.append({
            "device": d, "kind": "code_clone" if claimed else "unknown_transmitter",
            "claimed": claimed, "code": top_code, "bursts": n,
            "rejected_bursts": rejected,
            "rejection_rate": rejected / n if n else None,
            "combined_rejection_rate": rejected_comb / n if n else None,
            "frame_rejection_rate": float(np.mean(frame_rej)) if frame_rej else None,
        })

    by_distance = []
    for dist in sorted(k for k in gen_by_dist if not np.isnan(k)):
        s = np.array(gen_by_dist[dist])
        idx = [k for k, i in enumerate(test) if fs.distances[i] == dist]
        by_distance.append({"distance_m": dist, "frames": len(s), "frr": float(np.mean(s > 1.0)),
                            "accuracy": float(np.mean(pred[idx] == dev_t[idx])) if idx else None})

    per_class = {}
    for c in classes:
        m = dev_t == c
        per_class[c] = {"frames": int(m.sum()),
                        "accuracy": float(np.mean(pred[m] == c)) if m.any() else None,
                        "threshold": auth.profiles[c]["threshold"]}
    return {
        "closed_set": {"accuracy": acc, "labels": labels, "confusion": cm, "per_class": per_class},
        "verification": {"frame": frame, "burst": burst,
                         "burst_combined_frr": float(np.mean(combined_rej)) if combined_rej else None},
        "attacks": attacks,
        "by_distance": by_distance,
        "_emb_test": E_t, "_emb_imp": E_i,
    }


def _importance(model, auth, fs, splits, classes, scaler, device_codes, base_eer: float) -> List[Dict]:
    rng = np.random.default_rng(0)
    out = []
    for j, name in enumerate(FEATURE_NAMES):
        Xp = fs.X.copy()
        rows = np.array(splits.test + splits.impostor_test)
        if len(rows) < 2:
            break
        Xp[rows, j] = Xp[rng.permutation(rows), j]
        r = _eval_model(model, auth, fs, splits, classes, scaler, device_codes, X_override=Xp)
        eer = r["verification"]["frame"]["eer"]
        out.append({"feature": name, "eer": eer,
                    "delta_eer": None if eer is None or base_eer is None else eer - base_eer})
    out.sort(key=lambda d: -(d["delta_eer"] or 0))
    return out


def _embedding_map(fs: FrameSet, splits: Splits, E_t: np.ndarray, E_i: np.ndarray,
                   classes: List[str]) -> Dict:
    E = np.concatenate([E_t, E_i]) if len(E_i) else E_t
    if len(E) < 3:
        return {"points": []}
    idx = list(splits.test) + list(splits.impostor_test)
    E = E.astype(np.float64)
    mu = E.mean(0)
    with np.errstate(all="ignore"):  # Accelerate BLAS emits spurious matmul warnings
        _, sv, vt = np.linalg.svd(E - mu, full_matrices=False)
        P = (E - mu) @ vt[:2].T
    explained = float((sv[:2] ** 2).sum() / max((sv ** 2).sum(), 1e-12))
    rng = np.random.default_rng(1)
    keep = rng.permutation(len(E))[:1500]
    pts = [{"x": round(float(P[k, 0]), 4), "y": round(float(P[k, 1]), 4),
            "device": fs.device_ids[idx[k]], "enrolled": fs.device_ids[idx[k]] in classes}
           for k in sorted(keep)]
    return {"points": pts, "explained": round(explained, 3)}


def _liveness_report(fs: FrameSet, splits: Splits, classes: List[str], device_codes: Dict[str, str],
                     live: Dict[str, Dict]) -> Dict:
    """Model-independent view of the start-up drift check on held-out presses."""
    code_owner = {v: k for k, v in device_codes.items() if v and k in classes}
    genuine = {}
    for d, v in lv.burst_drifts(fs, splits.test).items():
        if d not in classes:
            continue
        res = [lv.check(live.get(d), x) for x in v]
        genuine[d] = {"presses": len(v), "median_ppm": round(float(np.median(v)), 1),
                      "rejected": int(sum(r is False for r in res))}
    impostors = {}
    imp_codes: Dict[str, Counter] = defaultdict(Counter)
    for i in splits.impostor_test:
        imp_codes[fs.device_ids[i]][fs.codes[i]] += 1
    for d, v in lv.burst_drifts(fs, splits.impostor_test).items():
        claimed = code_owner.get(imp_codes[d].most_common(1)[0][0]) if imp_codes[d] else None
        res = [lv.check(live.get(claimed), x) for x in v] if claimed else []
        impostors[d] = {"presses": len(v), "median_ppm": round(float(np.median(v)), 1), "claimed": claimed,
                        "rejected": int(sum(r is False for r in res)) if claimed else None}
    return {"profiles": live, "genuine_test": genuine, "impostor_test": impostors}


def evaluate(fs: FrameSet, splits: Splits, classes: List[str], scaler: FeatureScaler,
             models: Dict, auths: Dict[str, OpenSetAuthenticator], device_codes: Dict[str, str],
             live: Optional[Dict[str, Dict]] = None) -> Dict:
    report: Dict = {"models": {}}
    emb = {}
    live = live or {}
    for kind, model in models.items():
        r = _eval_model(model, auths[kind], fs, splits, classes, scaler, device_codes, live=live)
        emb[kind] = (r.pop("_emb_test"), r.pop("_emb_imp"))
        report["models"][kind] = r
    edge_eer = report["models"]["edge"]["verification"]["frame"]["eer"]
    report["feature_importance"] = _importance(models["edge"], auths["edge"], fs, splits, classes,
                                               scaler, device_codes, edge_eer)
    report["embedding_map"] = _embedding_map(fs, splits, *emb["fusion"], classes)
    report["liveness"] = _liveness_report(fs, splits, classes, device_codes, live)
    return report
