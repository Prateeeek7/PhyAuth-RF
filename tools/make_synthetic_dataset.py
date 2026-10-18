"""
Generate a labelled SIMULATED dataset with the virtual RF lab.

    python -m tools.make_synthetic_dataset --out data/sim --sessions 3 --presses 30

Files are written as <session>_<device>_sim.jsonl and every record carries
"simulated": true so it can never be confused with real captures.
"""

import argparse
import json
from pathlib import Path

from sim.rf_simulator import generate_dataset_lines

DEVICES = ["FOB_A", "EMU_1", "EMU_2", "CLONE_A", "EMU_3"]  # = the real kit, see sim.rf_simulator.RFWorld


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="data/sim")
    ap.add_argument("--sessions", type=int, default=3)
    ap.add_argument("--presses", type=int, default=30, help="button presses per device per session")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--devices", nargs="*", default=DEVICES)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    handles = {}
    n = 0
    for rec in generate_dataset_lines(args.devices, args.presses, args.sessions, seed=args.seed):
        key = (rec["session_id"], rec["device_id"])
        if key not in handles:
            handles[key] = open(out / f"{key[0]}_{key[1]}_sim.jsonl", "w")
        handles[key].write(json.dumps(rec) + "\n")
        n += 1
    for h in handles.values():
        h.close()
    print(f"wrote {n} simulated frames in {len(handles)} files to {out}")


if __name__ == "__main__":
    main()
