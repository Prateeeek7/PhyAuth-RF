"""Attack lab: drive the ESP32-S3 + STX882 node as a clone/replay attacker."""

from fastapi import APIRouter, HTTPException
from sqlmodel import Session, select

from acquisition.serial_link import available_ports
from backend.database import engine
from backend.db_models import Device
from backend.hub import hub
from common.models import CloneRequest, CommandRequest, ConnectRequest

router = APIRouter(prefix="/api/attack", tags=["Attack lab"])


@router.get("/status")
def status():
    return {"connected": hub.tx.connected, "port": hub.tx.port, "log": hub.tx.log[-40:],
            "simulation": hub.sim is not None, "sim_devices": hub.sim_devices(),
            "ports": available_ports()}


@router.post("/tx/connect")
def connect(req: ConnectRequest):
    try:
        hub.tx.connect(req.port, req.baud if req.baud != 921600 else 115200)
    except Exception as exc:
        raise HTTPException(400, str(exc))
    return status()


@router.post("/tx/disconnect")
def disconnect():
    hub.tx.disconnect()
    return status()


@router.post("/tx/command")
def command(req: CommandRequest):
    try:
        hub.tx.send(req.command)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return {"sent": req.command}


@router.post("/clone")
def clone(req: CloneRequest):
    """Replay the victim's code with its measured clock period."""
    with Session(engine) as s:
        dev = s.exec(select(Device).where(Device.device_id == req.target_device_id)).first()
    if not dev or not dev.code:
        raise HTTPException(409, "target has no learned code yet; record it first")
    hexcode, _ = dev.code.split("/")
    t_us = req.clock_t_us or hub.measured_clock(dev.code)
    if not t_us:
        raise HTTPException(409, "victim clock period unknown; record or press the genuine device first")
    if hub.sim is not None and not hub.tx.connected:
        # Simulator: the virtual lab has a matching crystal clone of FOB_A only
        clones = [n for n, m in hub.sim.world.tx.items() if m.kind == "crystal_clone"
                  and f"{m.code:06x}" == hexcode]
        if not clones:
            raise HTTPException(409, "simulation has no clone for this code; use the CLONE_A virtual device")
        hub.sim.trigger(clones[0])
        return {"mode": "simulation", "pressed": clones[0], "code": dev.code, "clock_t_us": t_us}
    cmd = f"CLONE {hexcode} {t_us:.2f} {req.frames}"
    try:
        hub.tx.send("AUTO 0")
        hub.tx.send(cmd)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return {"mode": "hardware", "sent": cmd, "code": dev.code, "clock_t_us": t_us}
