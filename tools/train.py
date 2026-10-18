"""
Train both models from the command line (same pipeline as Model Lab).

    python -m tools.train                          # enrolled devices from the registry
    python -m tools.train --enrolled FOB_A EMU_1 EMU_2 --epochs 80
    python -m tools.train --data data/sim --out checkpoints_sim

Codes and enrollment come from the backend database (Devices tab) unless
--enrolled is given. Prints the headline held-out metrics when done.
"""

import argparse
import warnings
from pathlib import Path

import config


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(config.DATA_DIR))
    ap.add_argument("--out", default=str(config.CHECKPOINT_DIR))
    ap.add_argument("--enrolled", nargs="*", help="device ids to enroll (default: authorized in registry)")
    ap.add_argument("--epochs", type=int, default=config.EPOCHS)
    args = ap.parse_args()
    warnings.filterwarnings("ignore", category=RuntimeWarning)

    from ml.train import train_pipeline
    from tools._registry import load_registry

    codes, authorized = load_registry()
    enrolled = args.enrolled or authorized
    if not enrolled:
        raise SystemExit("No enrolled devices: register them in the Devices tab or pass --enrolled.")

    def progress(p):
        stage = p.get("stage", "")
        if stage.startswith("train_"):
            print(f"\r  {stage[6:]:<6} epoch {p['epoch']}/{p['total_epochs']}", end="", flush=True)
        else:
            print(f"\n{stage}", flush=True)

    report = train_pipeline(Path(args.data), Path(args.out), enrolled, codes, epochs=args.epochs, progress=progress)
    print()
    if report["meta"].get("simulated_data"):
        print("NOTE: the dataset contains SIMULATED recordings.")
    for kind, m in report["models"].items():
        b = m["verification"]["burst"]
        print(f"[{kind}] closed-set acc {m['closed_set']['accuracy']:.3f} | per press FAR {b['far']:.3f} "
              f"FRR {b['frr']:.3f} (+liveness {m['verification'].get('burst_combined_frr') or 0:.3f})")
        for a in m["attacks"]:
            print(f"    {a['device']:<12} {a['kind']:<20} rejected {a['rejection_rate']:.2f} "
                  f"(+liveness {a.get('combined_rejection_rate') or 0:.2f}) over {a['bursts']} presses")
    for d, p in report["liveness"]["profiles"].items():
        print(f"liveness {d:<10} {'ACTIVE' if p['active'] else 'off':<7} {p.get('median_ppm', '-')} ppm  ({p['reason']})")
    print(f"saved to {args.out}")


if __name__ == "__main__":
    main()
