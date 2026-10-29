"""
Cross-day test: train + calibrate the edge model on session s01 only, then
decide every press of session s02 (never seen).

  * FOB_A (ON, same code as enrolled): must be accepted -> cross-day FRR.
  * FOB_A_OFF (same remote, OFF button, code never enrolled): identified by
    fingerprint alone. If it lands on FOB_A's profile, the system recognises the
    hardware rather than the code.

    python -m tools.crossday --enrolled FOB_A EMU_1 EMU_2 --out Report/crossday.json
"""

import argparse
import json
import warnings
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

import config


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(config.DATA_DIR))
    ap.add_argument("--enrolled", nargs="+", required=True)
    ap.add_argument("--train-session", default="s01")
    ap.add_argument("--test-session", default="s02")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--out", default="crossday.json")
    args = ap.parse_args()
    warnings.filterwarnings("ignore")

    from ml.data import FeatureScaler, FingerprintDataset, load_recordings
    from ml.train import _train_one, calibrate, embed

    fs = load_recordings(Path(args.data))
    classes = [c for c in args.enrolled if c in set(fs.device_ids)]
    cidx = {c: i for i, c in enumerate(classes)}
    X, S = fs.X, fs.S
    bursts = defaultdict(list)
    for i, b in enumerate(fs.bursts):
        bursts[b].append(i)
    for b in bursts.values():
        b.sort(key=lambda i: fs.times[i])

    train_b = [b for b, ix in bursts.items()
               if fs.device_ids[ix[0]] in cidx and fs.sessions[ix[0]] == args.train_session]
    val_b = set(train_b[::5])
    tr = [i for b in train_b if b not in val_b for i in bursts[b]]
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

    out = {}
    for dev in sorted({fs.device_ids[ix[0]] for ix in bursts.values()
                       if fs.sessions[ix[0]] == args.test_session}):
        scores, nearest, by_dist = [], [], defaultdict(list)
        for b, ix in bursts.items():
            if fs.device_ids[ix[0]] != dev or fs.sessions[ix[0]] != args.test_session \
                    or len(ix) < config.BURST_MIN_FRAMES:
                continue
            E = embed(model, X[ix[:4]], S[ix[:4]], scaler)
            per = {c: float(np.median(auth._dist(c, E) / auth.profiles[c]["threshold"])) for c in classes}
            claimed = code_owner.get(fs.codes[ix[0]])
            best = min(per, key=per.get)
            sc = per[claimed] if claimed else per[best]
            scores.append(sc)
            nearest.append(claimed or best)
            by_dist[fs.distances[ix[0]]].append(sc <= 1.0)
        out[dev] = {
            "presses": len(scores),
            "claim": "code" if code_owner.get(fs.codes[bursts[[b for b in bursts if fs.device_ids[bursts[b][0]] == dev][0]][0]]) else "fingerprint",
            "accepted": int(sum(s <= 1.0 for s in scores)),
            "matched_profile": dict(Counter(nearest)),
            "median_score": round(float(np.median(scores)), 3) if scores else None,
            "accepted_by_distance": {str(k): f"{sum(v)}/{len(v)}" for k, v in sorted(by_dist.items())},
        }
        print(f"{dev:10s} presses {len(scores):2d}  accepted {out[dev]['accepted']:2d}  "
              f"matched {out[dev]['matched_profile']}  median score {out[dev]['median_score']}  "
              f"by distance {out[dev]['accepted_by_distance']}")
    Path(args.out).write_text(json.dumps(out, indent=1))
    print("saved", args.out)


if __name__ == "__main__":
    main()
