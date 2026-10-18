"""Labelled data capture and dataset management."""

from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

import config
from backend.database import get_session
from backend.db_models import Device, Experiment
from backend.hub import hub
from common.models import RecordRequest

router = APIRouter(prefix="/api/recordings", tags=["Recordings"])


@router.post("/start", status_code=status.HTTP_202_ACCEPTED)
def start(req: RecordRequest, session: Session = Depends(get_session)):
    if not session.exec(select(Device).where(Device.device_id == req.device_id)).first():
        raise HTTPException(404, f"Register '{req.device_id}' first (Devices tab).")
    try:
        return hub.start_recording(req.device_id, req.session_id, req.distance_m, req.orientation_deg,
                                   req.target_good_frames, req.timeout_s, req.experiment_name, req.sim_source)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(409, str(exc))


@router.post("/stop")
def stop():
    st = hub.stop_recording()
    if st is None:
        raise HTTPException(409, "no recording running")
    return st


@router.get("/status")
def rec_status():
    return {"active": hub.recording.status() if hub.recording else None, "last": hub.last_recording}


@router.get("", response_model=List[Experiment])
def list_recordings(session: Session = Depends(get_session)):
    return session.exec(select(Experiment).order_by(Experiment.created_at.desc())).all()


@router.delete("/{rec_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recording(rec_id: int, session: Session = Depends(get_session)):
    rec = session.get(Experiment, rec_id)
    if not rec:
        raise HTTPException(404, "not found")
    f = config.DATA_DIR / Path(rec.filepath_prefix).name
    if f.exists() and f.parent == config.DATA_DIR:
        f.unlink()
    session.delete(rec)
    session.commit()


@router.get("/dataset")
def dataset_summary():
    """Per-device frame counts, sessions and codes over everything in data/."""
    from ml.data import load_recordings
    fs = load_recordings(config.DATA_DIR)
    return {"frames": len(fs), "devices": fs.summary(),
            "files": sorted(p.name for p in config.DATA_DIR.glob("*.jsonl"))}
