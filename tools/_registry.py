"""Read the device registry (enrollment + learned codes) from the backend database."""

from typing import Dict, List, Tuple

from sqlmodel import Session, select


def load_variants() -> Dict[str, str]:
    """Devices registered as kind 'variant' (same remote, other button) -> owner device.
    The owner is the enrolled device whose code shares the 20-bit EV1527 address."""
    from backend.database import engine, init_db
    from backend.db_models import Device
    init_db()
    with Session(engine) as s:
        devs = s.exec(select(Device)).all()
    return variants_from(devs)


def variants_from(devs) -> Dict[str, str]:
    owners = {(d.code or "")[:5]: d.device_id for d in devs if d.is_authorized and d.code}
    return {d.device_id: owners[(d.code or "")[:5]] for d in devs
            if d.kind == "variant" and d.code and (d.code or "")[:5] in owners}


def load_registry() -> Tuple[Dict[str, str], List[str]]:
    """Returns ({device_id: code}, [authorized device ids])."""
    from backend.database import engine, init_db
    from backend.db_models import Device
    init_db()
    with Session(engine) as s:
        devs = s.exec(select(Device)).all()
    return {d.device_id: d.code or "" for d in devs}, [d.device_id for d in devs if d.is_authorized]
