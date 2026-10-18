from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from backend.database import get_session
from backend.db_models import Device
from backend.hub import hub
from common.models import DeviceCreate, DeviceUpdate

router = APIRouter(prefix="/api/devices", tags=["Devices"])


def _get(session: Session, device_id: str) -> Device:
    dev = session.exec(select(Device).where(Device.device_id == device_id)).first()
    if not dev:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Device '{device_id}' not found.")
    return dev


@router.post("", response_model=Device, status_code=status.HTTP_201_CREATED)
def create_device(data: DeviceCreate, session: Session = Depends(get_session)):
    if session.exec(select(Device).where(Device.device_id == data.device_id)).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Device '{data.device_id}' already registered.")
    dev = Device(**data.model_dump())
    session.add(dev)
    session.commit()
    session.refresh(dev)
    hub.refresh_registry()
    return dev


@router.get("", response_model=List[Device])
def list_devices(session: Session = Depends(get_session)):
    return session.exec(select(Device).order_by(Device.registered_at)).all()


@router.get("/{device_id}", response_model=Device)
def get_device(device_id: str, session: Session = Depends(get_session)):
    return _get(session, device_id)


@router.patch("/{device_id}", response_model=Device)
def update_device(device_id: str, data: DeviceUpdate, session: Session = Depends(get_session)):
    dev = _get(session, device_id)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(dev, k, v if not (k == "code" and v == "") else None)
    session.add(dev)
    session.commit()
    session.refresh(dev)
    hub.refresh_registry()
    return dev


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_device(device_id: str, session: Session = Depends(get_session)):
    session.delete(_get(session, device_id))
    session.commit()
    hub.refresh_registry()
