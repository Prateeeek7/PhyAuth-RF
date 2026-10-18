import os
import sys
import tempfile
from pathlib import Path

# Isolate every test run from the real data/, checkpoints/ and database.
_tmp = Path(tempfile.mkdtemp(prefix="phyauth_test_"))
os.environ.setdefault("PHYAUTH_DATA_DIR", str(_tmp / "data"))
os.environ.setdefault("PHYAUTH_CHECKPOINT_DIR", str(_tmp / "ckpt"))
os.environ.setdefault("PHYAUTH_DB_PATH", str(_tmp / "test.db"))
os.environ.setdefault("PHYAUTH_AUTO_SIMULATION", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
