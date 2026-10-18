"""Request/response schemas for the REST API."""

from typing import Optional

from pydantic import BaseModel, Field


class DeviceCreate(BaseModel):
    device_id: str = Field(..., pattern=r"^[A-Za-z0-9_\-]{1,32}$", description="Unique ID, e.g. FOB_A")
    name: str = Field(..., description="Friendly name")
    model_info: str = Field("", description="Hardware model / manufacturer")
    protocol: str = Field("ASK/OOK-433")
    is_authorized: bool = Field(True, description="Enrolled (authorized) devices get a fingerprint profile")
    code: Optional[str] = Field(None, description="Decoded payload code 'hex/nbits'; learned automatically if empty")
    kind: str = Field("fob", description="fob | emulated | attacker | unknown")
    notes: str = ""


class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    model_info: Optional[str] = None
    is_authorized: Optional[bool] = None
    code: Optional[str] = None
    kind: Optional[str] = None
    notes: Optional[str] = None


class ConnectRequest(BaseModel):
    port: str
    baud: int = 921600


class CommandRequest(BaseModel):
    command: str = Field(..., max_length=60)


class SimPressRequest(BaseModel):
    name: str
    distance_m: Optional[float] = None
    orientation_deg: Optional[float] = None


class SimAutoplayRequest(BaseModel):
    enabled: bool
    interval_s: float = 2.5


class RecordRequest(BaseModel):
    device_id: str
    session_id: str = Field("s01", max_length=24)
    experiment_name: str = "capture"
    distance_m: float = 1.0
    orientation_deg: float = 0.0
    target_good_frames: int = Field(150, ge=10, le=5000)
    timeout_s: float = Field(180.0, ge=5, le=1800)
    sim_source: Optional[str] = Field(None, description="Simulation only: which virtual transmitter to press")


class TrainRequest(BaseModel):
    epochs: Optional[int] = Field(None, ge=5, le=500)


class RuntimeSettings(BaseModel):
    active_model: Optional[str] = Field(None, pattern="^(fusion|edge)$")
    threshold_scale: Optional[float] = Field(None, ge=0.5, le=2.0)
    liveness: Optional[bool] = Field(None, description="Enable the start-up drift liveness check")


class CloneRequest(BaseModel):
    target_device_id: str
    frames: int = Field(10, ge=1, le=40)
    clock_t_us: Optional[float] = Field(None, description="Override; default = victim's measured period")
