"""Training, evaluation report, runtime settings and edge export."""

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from sqlmodel import Session, select

import config
from backend.database import engine
from backend.db_models import Device
from backend.hub import hub
from common.models import RuntimeSettings, TrainRequest
from ml.train import BUNDLE_FILE, REPORT_FILE

router = APIRouter(prefix="/api/models", tags=["Models"])


@router.post("/train", status_code=202)
def train(req: TrainRequest = TrainRequest()):
    try:
        hub.start_training(req.epochs)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return hub.training


@router.get("/train/status")
def train_status():
    return hub.training


@router.get("/report")
def report():
    p = config.CHECKPOINT_DIR / REPORT_FILE
    if not p.exists():
        raise HTTPException(404, "no model trained yet")
    return json.loads(p.read_text())


@router.get("/info")
def info():
    return hub.engine.info()


@router.post("/runtime")
def runtime(req: RuntimeSettings):
    if req.active_model:
        hub.engine.set_active(req.active_model)
    if req.threshold_scale is not None:
        hub.engine.set_threshold_scale(req.threshold_scale)
    if req.liveness is not None:
        hub.engine.set_liveness(req.liveness)
    return hub.engine.info()


def _registry():
    with Session(engine) as s:
        devs = s.exec(select(Device)).all()
    return {d.device_id: d.code or "" for d in devs}, [d.device_id for d in devs if d.is_authorized]


@router.get("/edge/header", response_class=PlainTextResponse)
def edge_header():
    from ml.export_edge import build_header
    if not (config.CHECKPOINT_DIR / BUNDLE_FILE).exists():
        raise HTTPException(404, "no model trained yet")
    codes, auth = _registry()
    try:
        return build_header(device_codes=codes, authorized=auth)["text"]
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@router.post("/edge/export")
def edge_export():
    """Write firmware/esp32_receiver/src/phyauth_model.h; then flash the receiver board."""
    from ml.export_edge import export_header
    if not (config.CHECKPOINT_DIR / BUNDLE_FILE).exists():
        raise HTTPException(404, "no model trained yet")
    codes, auth = _registry()
    try:
        info = export_header(device_codes=codes, authorized=auth)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    info.pop("text")
    # The receiver reports its chip in the hello line; default to the classic ESP32.
    hello = hub.rx.hello or {}
    env = "esp32s3" if hello.get("board") == "esp32s3" else "esp32dev"
    info["board_env"] = env
    info["flash_command"] = f"cd firmware/esp32_receiver && pio run -e {env} -t upload"
    return info
