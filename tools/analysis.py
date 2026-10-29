"""
Robustness analyses on real recordings (edge model, same pipeline as training).

  1. Leave-one-distance-out: train + calibrate on all distances but one, test on
     the unseen distance (genuine FRR, clone / unknown rejection per press).
  2. Frames per decision: the same held-out presses decided from the median of
     the first k frames, k = 1..4 (speed vs reliability).

    python -m tools.analysis --enrolled FOB_A EMU_1 EMU_2 --out Report/analysis.json
"""

import argparse
import json
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np

import config


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(config.DATA_DIR))
    ap.add_argument("--enrolled", nargs="+", required=True)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--out", default="analysis.json")
    args = ap.parse_args()
    warnings.filterwarnings("ignore")

    from ml.data import FeatureScaler, FingerprintDataset, load_recordings
    from ml.train import _train_one, calibrate, embed

    fs = load_recordings(Path(args.data))
    classes = [c for c in args.enrolled if c in set(fs.device_ids)]
    cidx = {c: i for i, c in enumerate(classes)}
    X, S = fs.X, fs.S
    dists = sorted({d for d in fs.distances if d == d})
    bursts = defaultdict(list)
    for i, b in enumerate(fs.bursts):
        bursts[b].append(i)
    for b in bursts.values():
        b.sort(key=lambda i: fs.times[i])

    per_k = {k: {"gen": [], "clone": [], "unknown": []} for k in range(1, 5)}
    folds = []
    for held in dists:
        train_b = [b for b, ix in bursts.items() if fs.device_ids[ix[0]] in cidx and fs.distances[ix[0]] != held]
        val_b = train_b[::5]
        tr = [i for b in train_b if b not in set(val_b) for i in bursts[b]]
        va = [i for b in val_b for i in bursts[b]]
        y = np.array([cidx.get(d, -1) for d in fs.device_ids])
        scaler = FeatureScaler.fit(X[tr])
        model = _train_one("edge", len(classes),
                           FingerprintDataset(X[tr], S[tr], y[tr], scaler, augment_data=True),
                           FingerprintDataset(X[va], S[va], y[va], scaler),
                           args.epochs, config.LEARNING_RATE, config.BATCH_SIZE, None)
        auth = calibrate(model, fs, va, classes, scaler, config.TARGET_FRR)
        code_owner = {}
        for c in classes:
            codes = [fs.codes[i] for i in tr if fs.device_ids[i] == c]
            code_owner[max(set(codes), key=codes.count)] = c

        res = {"held_out_m": held, "genuine": {}, "clone": None, "unknown": None}
        counts = defaultdict(lambda: [0, 0])
        for b, ix in bursts.items():
            if fs.distances[ix[0]] != held or len(ix) < config.BURST_MIN_FRAMES:
                continue
            dev = fs.device_ids[ix[0]]
            E = embed(model, X[ix[:4]], S[ix[:4]], scaler)
            claimed = code_owner.get(fs.codes[ix[0]])
            if claimed:
                sc = auth._dist(claimed, E) / auth.profiles[claimed]["threshold"]
            else:
                sc = np.min([auth._dist(c, E) / auth.profiles[c]["threshold"] for c in classes], axis=0)
            kind = "gen" if dev in cidx else ("clone" if claimed else "unknown")
            for k in range(1, min(4, len(sc)) + 1):
                per_k[k][kind].append(float(np.median(sc[:k])))
            accept = float(np.median(sc[:4])) <= 1.0
            key = dev if kind == "gen" else kind
            counts[key][0] += 1
            counts[key][1] += int(accept if kind == "gen" else not accept)
        for key, (n, ok) in counts.items():
            entry = {"presses": n, "rate": ok / n}
            if key in ("clone", "unknown"):
                res[key] = {"presses": n, "rejection": ok / n}
            else:
                res["genuine"][key] = {"presses": n, "frr": 1 - ok / n}
        folds.append(res)
        print(f"held-out {held} m: " + ", ".join(
            [f"{d} FRR {v['frr']:.2f} ({v['presses']})" for d, v in res["genuine"].items()] +
            [f"{k} rejected {res[k]['rejection']:.2f} ({res[k]['presses']})" for k in ("clone", "unknown") if res[k]]))

    frames = []
    for k, v in per_k.items():
        g, c, u = (np.array(v[x]) for x in ("gen", "clone", "unknown"))
        frames.append({"frames": k, "genuine_frr": float(np.mean(g > 1)) if len(g) else None,
                       "clone_rejection": float(np.mean(c > 1)) if len(c) else None,
                       "unknown_rejection": float(np.mean(u > 1)) if len(u) else None,
                       "genuine_presses": len(g), "latency_ms": round(k * 42.9, 1)})
        print(f"k={k}: genuine FRR {frames[-1]['genuine_frr']:.3f}  clone rejected {frames[-1]['clone_rejection']:.3f}  "
              f"unknown rejected {frames[-1]['unknown_rejection']:.3f}  (~{k*42.9:.0f} ms of signal)")
    Path(args.out).write_text(json.dumps({"leave_one_distance_out": folds, "frames_per_decision": frames}, indent=1))
    print("saved", args.out)


if __name__ == "__main__":
    main()
