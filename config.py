"""
Central configuration. Every value can be overridden with an environment
variable of the same name prefixed with PHYAUTH_ (e.g. PHYAUTH_API_PORT=8001).
"""

import os
from pathlib import Path


def _env(name: str, default, cast=str):
    v = os.environ.get(f"PHYAUTH_{name}")
    return cast(v) if v is not None else default


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(_env("DATA_DIR", str(BASE_DIR / "data")))
CHECKPOINT_DIR = Path(_env("CHECKPOINT_DIR", str(BASE_DIR / "checkpoints")))
EDGE_HEADER_PATH = BASE_DIR / "firmware" / "esp32_receiver" / "src" / "phyauth_model.h"
DB_PATH = Path(_env("DB_PATH", str(BASE_DIR / "phyauth.db")))

DATA_DIR.mkdir(parents=True, exist_ok=True)
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Hardware: ESP32-WROOM-32 + SRX882 receiver, ESP32-S3 + STX882 transmitter
# ---------------------------------------------------------------------------
# Receiver serial port. Leave empty to pick it in the dashboard (Hardware tab).
#   macOS: /dev/cu.usbserial-0001   Linux: /dev/ttyUSB0   Windows: COM3
SERIAL_PORT: str = _env("SERIAL_PORT", os.environ.get("ESP32_SERIAL_PORT", ""))
SERIAL_BAUD_RATE: int = _env("SERIAL_BAUD", 921600, int)       # must match firmware SERIAL_BAUD
TX_SERIAL_PORT: str = _env("TX_SERIAL_PORT", "")
TX_BAUD_RATE: int = 115200

# Start the physics-based virtual receiver when no port is configured
AUTO_SIMULATION: bool = _env("AUTO_SIMULATION", "1") == "1"

DEFAULT_CENTER_FREQ: float = 433.92e6

# ---------------------------------------------------------------------------
# Machine learning
# ---------------------------------------------------------------------------
EMBEDDING_DIM: int = 32         # FingerprintNet (host)
EDGE_HIDDEN: int = 32           # EdgeMLP hidden units (ESP32)
EDGE_EMBEDDING_DIM: int = 16    # EdgeMLP embedding size (ESP32)
BATCH_SIZE: int = _env("BATCH_SIZE", 128, int)
EPOCHS: int = _env("EPOCHS", 60, int)
LEARNING_RATE: float = _env("LR", 2e-3, float)

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
TARGET_FRR: float = 0.03        # per-frame false-reject target used to set thresholds
# Thresholds are the (1-TARGET_FRR) quantile of genuine validation distances
# times this margin, an allowance for slow session-to-session drift
# (temperature, battery voltage) that a few validation sessions under-sample.
THRESHOLD_MARGIN: float = 1.3
BURST_GAP_S: float = 0.30       # frames closer than this belong to one button press
BURST_DECISION_FRAMES: int = 4  # decision = median distance of the first N frames of a press
BURST_MIN_FRAMES: int = 3       # presses with fewer consistent frames are ignored (stray noise)
# Reject presses without the cold-start clock drift a battery fob shows
# (only for devices whose own training presses show it; see ml/liveness.py)
LIVENESS_CHECK: bool = _env("LIVENESS_CHECK", "1") == "1"

# ---------------------------------------------------------------------------
# API server
# ---------------------------------------------------------------------------
API_HOST: str = _env("API_HOST", "127.0.0.1")
API_PORT: int = _env("API_PORT", 8000, int)
DATABASE_URL: str = f"sqlite:///{DB_PATH}"
CORS_ORIGINS = _env("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
