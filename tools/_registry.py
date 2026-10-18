"""Read the device registry (enrollment + learned codes) from the backend database."""

from typing import Dict, List, Tuple

from sqlmodel import Session, select


def load_registry() -> Tuple[Dict[str, str], List[str]]:
    """Returns ({device_id: code}, [authorized device ids])."""
    from backend.database import engine, init_db
    from backend.db_models import Device
    init_db()
    with Session(engine) as s:
        devs = s.exec(select(Device)).all()
    return {d.device_id: d.code or "" for d in devs}, [d.device_id for d in devs if d.is_authorized]
