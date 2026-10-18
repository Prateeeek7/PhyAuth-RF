from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Device(SQLModel, table=True):
    """A physical transmitter known to the system."""
    id: Optional[int] = Field(default=None, primary_key=True)
    device_id: str = Field(unique=True, index=True)
    name: str
    model_info: str = ""
    protocol: str = "ASK/OOK-433"
    is_authorized: bool = Field(default=True)
    # Decoded payload code, e.g. "4f6d97/24". Learned automatically from the
    # first recording; it is the identity *claim* a frame makes.
    code: Optional[str] = Field(default=None, index=True)
    # fob | emulated | attacker | unknown
    kind: str = Field(default="fob")
    notes: str = ""
    registered_at: datetime = Field(default_factory=_now)


class Experiment(SQLModel, table=True):
    """One recording session (a .jsonl file in data/)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    experiment_name: str
    center_frequency: float = 433.92e6
    sample_rate: float = 0.0
    gain: str = "N/A"
    duration_seconds: float = 0.0
    transmitter_id: str = Field(index=True)
    distance_meters: float = 1.0
    orientation_deg: float = 0.0
    session_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=_now)
    filepath_prefix: str = ""
    frames_total: int = 0
    frames_good: int = 0
    dominant_code: Optional[str] = None
    clock_t_us: Optional[float] = None   # median estimated clock period of good frames
    source: str = "hardware"       # hardware | simulation


class AuthEvent(SQLModel, table=True):
    """One authentication decision (one button press)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=_now, index=True)
    verdict: str = Field(index=True)          # AUTHENTIC | SPOOF_SUSPECTED | UNKNOWN_DEVICE
    code: str = ""
    claimed_device_id: Optional[str] = Field(default=None, index=True)
    claim_source: str = "code"                # code | fingerprint
    predicted_device_id: Optional[str] = None
    score: float = 0.0                        # distance / threshold (<= 1 accepts)
    distance: float = 0.0
    frames: int = 0
    clock_t_us: Optional[float] = None
    model: str = ""
    model_version: Optional[str] = None
    source: str = "host"                      # host | edge (decided on the ESP32)
    simulated: bool = False
    drift_ppm: Optional[float] = None         # start-up clock drift of the press
    liveness: Optional[str] = None            # ok | no start-up drift | None (not applicable)


class AuthenticationLog(SQLModel, table=True):
    """Legacy v1 table, kept so old databases still open. Not written anymore."""
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=_now, index=True)
    claimed_device_id: Optional[str] = None
    predicted_device_id: Optional[str] = None
    cfo_est_hz: float = 0.0
    iq_gain_est: float = 0.0
    iq_phase_est_deg: float = 0.0
    snr_est_db: float = 0.0
    confidence: float = 0.0
    distance_metric: float = 0.0
    is_authenticated: bool = Field(default=False, index=True)
