"""
Export the trained edge model into the receiver firmware.

    python -m tools.export_edge                    # -> firmware/esp32_receiver/src/phyauth_model.h
    python -m tools.export_edge --ckpt checkpoints_sim

Then flash the receiver board:
    cd firmware/esp32_receiver && pio run -e esp32dev -t upload   # classic ESP32
    cd firmware/esp32_receiver && pio run -e esp32s3  -t upload   # ESP32-S3
"""

import argparse
from pathlib import Path

import config


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ckpt", default=str(config.CHECKPOINT_DIR))
    ap.add_argument("--out", default=str(config.EDGE_HEADER_PATH))
    args = ap.parse_args()

    from ml.export_edge import export_header
    from tools._registry import load_registry

    codes, authorized = load_registry()
    info = export_header(Path(args.out), ckpt_dir=Path(args.ckpt), device_codes=codes,
                         authorized=authorized or None)
    print(f"wrote {info['path']}")
    print(f"model {info['version']} | {info['parameters']} parameters | {info['flash_bytes'] / 1024:.1f} KB")
    for d in info["devices"]:
        print(f"  {d:<10} code {info['codes'][d] or '(identify only)':<12} liveness {'on' if info['liveness'][d] else 'off'}")


if __name__ == "__main__":
    main()
