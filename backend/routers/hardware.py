"""Receiver connection, port discovery, firmware commands and the simulator."""

from fastapi import APIRouter, HTTPException

from acquisition.serial_link import available_ports
from backend.hub import hub
from common.models import CommandRequest, ConnectRequest, SimAutoplayRequest, SimPressRequest
from sim.rf_simulator import Channel

router = APIRouter(prefix="/api/hardware", tags=["Hardware"])


@router.get("/ports")
def ports():
    return available_ports()


@router.get("/status")
def status():
    return hub.status()


@router.post("/connect")
def connect(req: ConnectRequest):
    try:
        hub.connect_hardware(req.port, req.baud)
    except Exception as exc:
        raise HTTPException(400, str(exc))
    return hub.rx.status()


@router.post("/disconnect")
def disconnect():
    hub.disconnect()
    return hub.rx.status()


@router.post("/command")
def command(req: CommandRequest):
    if not hub.rx.send(req.command):
        raise HTTPException(409, "receiver not connected")
    return {"sent": req.command}


@router.post("/simulate")
def simulate(autoplay: bool = True):
    hub.start_simulation(autoplay=autoplay)
    return {"devices": hub.sim_devices(), **hub.rx.status()}


@router.get("/sim/devices")
def sim_devices():
    return hub.sim_devices()


@router.post("/sim/press")
def sim_press(req: SimPressRequest):
    if hub.sim is None:
        raise HTTPException(409, "simulator not running")
    if req.name not in hub.sim.world.tx:
        raise HTTPException(404, f"unknown virtual transmitter {req.name}")
    if req.distance_m is not None:
        hub.sim.set_channel(req.distance_m, req.orientation_deg or 0.0)
    hub.sim.trigger(req.name)
    return {"pressed": req.name}


@router.post("/sim/autoplay")
def sim_autoplay(req: SimAutoplayRequest):
    if hub.sim is None:
        raise HTTPException(409, "simulator not running")
    hub.sim_autoplay = req.enabled
    hub.sim.autoplay = req.enabled
    hub.sim.interval_s = max(0.5, req.interval_s)
    return {"autoplay": hub.sim.autoplay, "interval_s": hub.sim.interval_s}


@router.post("/sim/channel")
def sim_channel(distance_m: float = 1.0, orientation_deg: float = 0.0):
    if hub.sim is None:
        raise HTTPException(409, "simulator not running")
    hub.sim.world.channel = Channel(distance_m, orientation_deg)
    return {"distance_m": distance_m, "orientation_deg": orientation_deg,
            "snr_db": round(hub.sim.world.channel.snr_db, 1)}
