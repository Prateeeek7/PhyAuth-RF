"""Two-factor pattern lock running on the receiver ESP32 (see phyauth_lock.c)."""

from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.hub import hub

router = APIRouter(prefix="/api/lock", tags=["Lock"])

KEY_NAMES = {8: "ON", 4: "OFF"}


class LockSet(BaseModel):
    owner: str = Field("FOB_A", pattern=r"^[A-Za-z0-9_\-]{1,23}$")
    keys: List[str] = Field(..., min_length=4, max_length=12, description="ON / OFF or key nibble")


class LockLearn(BaseModel):
    owner: str = Field("FOB_A", pattern=r"^[A-Za-z0-9_\-]{1,23}$")


class LockRelock(BaseModel):
    seconds: int = Field(15, ge=0, le=3600)


def _send(cmd: str) -> dict:
    if hub.rx.mode != "hardware" or not hub.rx.send(cmd):
        raise HTTPException(409, "receiver not connected (the lock runs on the ESP32)")
    return {"sent": cmd}


@router.get("/status")
def status():
    return {"state": hub.lock_state, "events": list(hub.lock_events)[:50], "key_names": KEY_NAMES}


@router.post("/refresh")
def refresh():
    return _send("LOCK STATUS")


@router.post("/set")
def set_pattern(req: LockSet):
    keys = [k.upper() for k in req.keys]
    if any(k not in ("ON", "OFF") and not (len(k) == 1 and k in "0123456789ABCDEF") for k in keys):
        raise HTTPException(422, "keys must be ON, OFF or a hex key nibble")
    return _send(f"LOCK SET {req.owner.upper()} {','.join(keys)}")


@router.post("/learn")
def learn(req: LockLearn = LockLearn()):
    return _send(f"LOCK LEARN {req.owner.upper()}")


@router.post("/clear")
def clear():
    return _send("LOCK CLEAR")


@router.post("/now")
def lock_now():
    return _send("LOCK NOW")


@router.post("/relock")
def relock(req: LockRelock):
    return _send(f"LOCK RELOCK {req.seconds}")

