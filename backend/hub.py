"""
backend/hub.py
--------------
The single runtime object that owns hardware links, the inference engine,
recording/training jobs and WebSocket clients.

Data flow
    ReceiverLink thread --(raw msg)--> RecordingJob.write()   (same thread, no loss)
                        \\-(call_soon_threadsafe)-> asyncio queue
    _consume(): frame -> InferenceEngine.process() (once per frame, worker thread)
              -> broadcast frame event / decision to every client, persist decisions
"""

from __future__ import annotations

import asyncio
import json
import logging
import statistics
import threading
import time
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Deque, Dict, List, Optional, Set

from sqlmodel import Session, select

import config
from acquisition.serial_link import ReceiverLink, TransmitterLink
from backend.database import engine as db_engine
from backend.db_models import AuthEvent, Device, Experiment
from dsp.pulse_dsp import analyze_frame
from ml.inference import InferenceEngine
from sim.rf_simulator import Channel, RFWorld, SimulatedSerialPort

logger = logging.getLogger("hub")


class RecordingJob:
    """Streams labelled frames to data/<session>_<device>_<timestamp>.jsonl."""

    def __init__(self, device_id: str, session_id: str, distance_m: float, orientation_deg: float,
                 target_good: int, timeout_s: float, name: str, source: str,
                 expected_code: Optional[str] = None):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_sess = "".join(ch for ch in session_id if ch.isalnum() or ch in "-") or "s"
        self.path = config.DATA_DIR / f"{safe_sess}_{device_id}_{stamp}.jsonl"
        self.device_id, self.session_id, self.name = device_id, session_id, name
        self.distance_m, self.orientation_deg = distance_m, orientation_deg
        self.target_good, self.timeout_s, self.source = target_good, timeout_s, source
        self.started = time.time()
        self.frames_total = 0
        self.frames_good = 0
        self.codes: Counter = Counter()
        self.clocks: List[float] = []
        self.reject_reasons: Counter = Counter()
        # Code lock: other 433 MHz devices nearby (doorbells, weather stations,
        # neighbours' remotes) must not end up labelled as this transmitter.
        self.expected_code = expected_code
        self.foreign = 0
        self.state = "recording"      # recording | done | stopped | timeout
        self.finalized = False
        self._fh = open(self.path, "w")
        self._lock = threading.Lock()

    def write(self, msg: Dict) -> None:
        if msg.get("type") != "frame":
            return
        fa = analyze_frame(msg["d"], int(msg.get("g", -1) if msg.get("g") is not None else -1))
        with self._lock:
            if self.state != "recording":
                return
            lock = self.expected_code or self._auto_lock()
            if fa.ok and lock and fa.code != lock:
                self.foreign += 1
                return
            rec = {k: msg[k] for k in ("type", "seq", "t_us", "g", "n", "d") if k in msg}
            rec.update({"device_id": self.device_id, "session_id": self.session_id,
                        "distance_m": self.distance_m, "orientation_deg": self.orientation_deg,
                        "rx_time": msg.get("rx_time"), "simulated": self.source == "simulation"})
            self._fh.write(json.dumps(rec) + "\n")
            self.frames_total += 1
            if fa.ok:
                self.frames_good += 1
                self.codes[fa.code] += 1
                self.clocks.append(fa.clock_t_ns / 1000.0)
            else:
                self.reject_reasons[fa.reason] += 1
            if self.frames_good >= self.target_good:
                self._close("done")

    def _auto_lock(self) -> Optional[str]:
        # lock onto a code once it has clearly dominated the first good frames
        if self.frames_good >= 8:
            code, n = self.codes.most_common(1)[0]
            if n >= 0.75 * self.frames_good:
                return code
        return None

    def check_timeout(self) -> None:
        if self.state == "recording" and time.time() - self.started > self.timeout_s:
            with self._lock:
                self._close("timeout")

    def stop(self) -> None:
        with self._lock:
            if self.state == "recording":
                self._close("stopped")

    def _close(self, state: str) -> None:
        self.state = state
        self._fh.flush()
        self._fh.close()

    @property
    def dominant_code(self) -> Optional[str]:
        if not self.codes:
            return None
        code, n = self.codes.most_common(1)[0]
        return code if n >= 0.6 * self.frames_good else None

    def status(self) -> Dict:
        return {"device_id": self.device_id, "session_id": self.session_id, "name": self.name,
                "state": self.state, "frames_total": self.frames_total, "frames_good": self.frames_good,
                "target_good": self.target_good, "elapsed_s": round(time.time() - self.started, 1),
                "timeout_s": self.timeout_s, "file": self.path.name,
                "dominant_code": self.dominant_code,
                "clock_t_us": round(statistics.median(self.clocks), 3) if self.clocks else None,
                "reject_reasons": dict(self.reject_reasons), "source": self.source,
                "expected_code": self.expected_code, "foreign_frames": self.foreign}


class Hub:
    def __init__(self):
        self.rx = ReceiverLink()
        self.tx = TransmitterLink()
        self.sim: Optional[SimulatedSerialPort] = None
        self.engine = InferenceEngine()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.queue: Optional[asyncio.Queue] = None
        self.clients: Set = set()
        self.recent_frames: Deque[Dict] = deque(maxlen=300)
        self.recent_decisions: Deque[Dict] = deque(maxlen=100)
        self.clock_by_code: Dict[str, Deque[float]] = {}
        self.quality = Counter()
        self.verdicts = Counter()
        self.recording: Optional[RecordingJob] = None
        self.last_recording: Optional[Dict] = None
        self.training: Dict = {"status": "IDLE", "progress": {}, "error": "", "report_ready": False}
        self._sim_driver: Optional[threading.Thread] = None
        self.sim_autoplay = True          # user preference, restored after recordings
        self._exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="infer")
        self._tasks: List[asyncio.Task] = []
        self._sub_id: Optional[int] = None

    # ---- lifecycle --------------------------------------------------------------
    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.queue = asyncio.Queue(maxsize=5000)
        self._sub_id = self.rx.subscribe(self._on_msg)
        self.refresh_registry()
        self._tasks = [asyncio.create_task(self._consume()), asyncio.create_task(self._ticker())]
        if config.SERIAL_PORT:
            self.connect_hardware(config.SERIAL_PORT, config.SERIAL_BAUD_RATE)
        elif config.AUTO_SIMULATION:
            self.start_simulation()

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        if self.recording:
            self.recording.stop()
        self.rx.disconnect()
        self.tx.disconnect()
        self._exec.shutdown(wait=False)

    # ---- links -----------------------------------------------------------------
    def connect_hardware(self, port: str, baud: int) -> None:
        self.sim = None
        self.rx.connect_hardware(port, baud)

    def start_simulation(self, autoplay: bool = True) -> None:
        self.sim_autoplay = autoplay
        self.sim = SimulatedSerialPort(RFWorld(seed=int(time.time()) % 1000), autoplay=autoplay)
        self.rx.connect_simulation(self.sim)

    def disconnect(self) -> None:
        self.rx.disconnect()
        self.sim = None

    def sim_devices(self) -> List[Dict]:
        if not self.sim:
            return []
        out = []
        for name, m in self.sim.world.tx.items():
            out.append({"name": name, "kind": m.kind, "code": f"{m.code:06x}/24",
                        "clock_t_us": round(m.t_ns / 1000.0, 3)})
        return out

    # ---- registry --------------------------------------------------------------
    def refresh_registry(self) -> None:
        with Session(db_engine) as s:
            devs = s.exec(select(Device)).all()
        self.engine.set_registry({d.device_id for d in devs if d.is_authorized},
                                 {d.device_id: d.code or "" for d in devs})

    # ---- serial thread callback ------------------------------------------------
    def _on_msg(self, msg: Dict) -> None:
        job = self.recording
        if job is not None and job.state == "recording":
            job.write(msg)
        if self.loop is not None:
            try:
                self.loop.call_soon_threadsafe(self._enqueue, msg)
            except RuntimeError:
                pass

    def _enqueue(self, msg: Dict) -> None:
        try:
            self.queue.put_nowait(msg)
        except asyncio.QueueFull:
            self.quality["dropped_backlog"] += 1

    # ---- async consumers --------------------------------------------------------
    async def _consume(self) -> None:
        while True:
            msg = await self.queue.get()
            try:
                t = msg.get("type")
                if t == "frame":
                    ev, dec = await self.loop.run_in_executor(self._exec, self.engine.process, msg)
                    self.quality[ev["quality"]] += 1
                    if ev["ok"] and ev.get("clock_t_us"):
                        self.clock_by_code.setdefault(ev["code"], deque(maxlen=200)).append(ev["clock_t_us"])
                    ev["simulated"] = self.rx.mode == "simulation"
                    if self.sim is not None:
                        ev["sim_source"] = self.sim.last_pressed
                    self.recent_frames.append(ev)
                    await self.broadcast(ev)
                    if dec:
                        await self._handle_decision(dec, source="host")
                elif t == "auth":   # decision made on the ESP32 itself
                    dec = {"type": "decision", "time": time.time(), "verdict": msg.get("verdict"),
                           "code": msg.get("code", ""), "claimed": msg.get("dev"),
                           "claim_source": "code" if msg.get("claimed") else "fingerprint",
                           "score": msg.get("score", 0.0), "distance": msg.get("dist", 0.0),
                           "frames": msg.get("frames", 0), "predicted": msg.get("dev"),
                           "clock_t_us": msg.get("T_us"), "model": "edge",
                           "model_version": (self.rx.hello or {}).get("model"),
                           "infer_us": msg.get("infer_us"),
                           "fingerprint_ok": bool(msg["fp_ok"]) if "fp_ok" in msg else None,
                           "drift_ppm": msg.get("drift_ppm") if msg.get("live", -1) != -1 else None,
                           "liveness": {1: "ok", 0: "no start-up drift"}.get(msg.get("live", -1))}
                    await self._handle_decision(dec, source="edge")
                elif t in ("stats", "hello", "ack", "err"):
                    await self.broadcast({**msg, "type": f"rx_{t}"})
            except Exception as exc:
                logger.exception("consume error: %s", exc)

    async def _handle_decision(self, dec: Dict, source: str) -> None:
        dec["source"] = source
        dec["simulated"] = self.rx.mode == "simulation"
        if self.sim is not None:
            dec["sim_source"] = self.sim.last_pressed
        self.verdicts[dec["verdict"]] += 1
        self.recent_decisions.appendleft(dec)
        with Session(db_engine) as s:
            s.add(AuthEvent(verdict=dec["verdict"], code=dec.get("code") or "",
                            claimed_device_id=dec.get("claimed"), claim_source=dec.get("claim_source", "code"),
                            predicted_device_id=dec.get("predicted"), score=float(dec.get("score") or 0),
                            distance=float(dec.get("distance") or 0), frames=int(dec.get("frames") or 0),
                            clock_t_us=dec.get("clock_t_us"), model=dec.get("model", ""),
                            model_version=dec.get("model_version"), source=source,
                            simulated=dec["simulated"], drift_ppm=dec.get("drift_ppm"),
                            liveness=dec.get("liveness")))
            s.commit()
        await self.broadcast(dec)

    async def _ticker(self) -> None:
        n = 0
        while True:
            await asyncio.sleep(0.25)
            n += 1
            try:
                dec = await self.loop.run_in_executor(self._exec, self.engine.tick)
                if dec:
                    await self._handle_decision(dec, source="host")
                job = self.recording
                if job is not None:
                    job.check_timeout()
                    if job.state != "recording" and not job.finalized:
                        self._finalize_recording(job)
                    if n % 2 == 0 or job.finalized:
                        await self.broadcast({"type": "recording", **job.status()})
                    if job.finalized:
                        self.recording = None
                if n % 8 == 0:
                    await self.broadcast({"type": "status", **self.status()})
            except Exception as exc:
                logger.exception("ticker error: %s", exc)

    # ---- websocket ---------------------------------------------------------------
    async def broadcast(self, obj: Dict) -> None:
        if not self.clients:
            return
        data = json.dumps(obj, default=str)
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def broadcast_threadsafe(self, obj: Dict) -> None:
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.broadcast(obj), self.loop)

    # ---- recording ------------------------------------------------------------------
    def start_recording(self, device_id: str, session_id: str, distance_m: float, orientation_deg: float,
                        target_good: int, timeout_s: float, name: str, sim_source: Optional[str]) -> Dict:
        if self.recording and self.recording.state == "recording":
            raise RuntimeError("a recording is already running")
        if self.rx.mode == "disconnected":
            raise RuntimeError("receiver is not connected (connect hardware or start the simulator)")
        source = "simulation" if self.rx.mode == "simulation" else "hardware"
        if source == "simulation":
            name_sim = sim_source or device_id
            if name_sim not in self.sim.world.tx:
                raise ValueError(f"simulation: choose a virtual transmitter ({', '.join(self.sim.world.tx)})")
        with Session(db_engine) as s:
            dev = s.exec(select(Device).where(Device.device_id == device_id)).first()
        job = RecordingJob(device_id, session_id, distance_m, orientation_deg, target_good, timeout_s, name, source,
                           expected_code=dev.code if dev else None)
        if source == "simulation":
            self.sim.autoplay = False
            self.sim.flush()
        self.recording = job
        if source == "simulation":
            self.sim.set_channel(distance_m, orientation_deg)
            self._sim_driver = threading.Thread(target=self._drive_sim, args=(job, name_sim), daemon=True)
            self._sim_driver.start()
        return job.status()

    def _drive_sim(self, job: RecordingJob, name: str) -> None:
        sim = self.sim
        try:
            while job.state == "recording" and self.sim is sim:
                sim.trigger(name)
                time.sleep(1.1)
        finally:
            if self.recording is job or self.recording is None:
                sim.set_channel(1.0, 0.0)
                sim.autoplay = self.sim_autoplay

    def stop_recording(self) -> Optional[Dict]:
        if self.recording:
            self.recording.stop()
            return self.recording.status()
        return None

    def _finalize_recording(self, job: RecordingJob) -> None:
        job.finalized = True
        st = job.status()
        self.last_recording = st
        if job.frames_total == 0:
            try:
                job.path.unlink()
            except OSError:
                pass
            return
        with Session(db_engine) as s:
            s.add(Experiment(experiment_name=job.name, transmitter_id=job.device_id,
                             distance_meters=job.distance_m, orientation_deg=job.orientation_deg,
                             session_id=job.session_id, duration_seconds=time.time() - job.started,
                             filepath_prefix=job.path.name, frames_total=job.frames_total,
                             frames_good=job.frames_good, dominant_code=job.dominant_code,
                             clock_t_us=st["clock_t_us"], source=job.source))
            dev = s.exec(select(Device).where(Device.device_id == job.device_id)).first()
            if dev and not dev.code and job.dominant_code:
                dev.code = job.dominant_code   # learn the identity claim of this transmitter
                s.add(dev)
            s.commit()
        self.refresh_registry()

    # ---- training ---------------------------------------------------------------------
    def start_training(self, epochs: Optional[int] = None) -> None:
        if self.training["status"] == "RUNNING":
            raise RuntimeError("training already running")
        with Session(db_engine) as s:
            devs = s.exec(select(Device)).all()
        enrolled = [d.device_id for d in devs if d.is_authorized]
        codes = {d.device_id: d.code or "" for d in devs}
        self.training = {"status": "RUNNING", "progress": {"stage": "starting"}, "error": "",
                         "report_ready": False, "started": time.time()}

        def run():
            from ml.train import train_pipeline

            def prog(p: Dict):
                self.training["progress"] = p
                self.broadcast_threadsafe({"type": "training", **self.training})
            try:
                train_pipeline(config.DATA_DIR, config.CHECKPOINT_DIR, enrolled, codes, epochs=epochs, progress=prog)
                self.engine.load()
                self.refresh_registry()
                self.training.update({"status": "COMPLETED", "report_ready": True})
            except Exception as exc:
                logger.exception("training failed")
                self.training.update({"status": "FAILED", "error": str(exc)})
            self.broadcast_threadsafe({"type": "training", **self.training})

        threading.Thread(target=run, name="Trainer", daemon=True).start()

    # ---- status ---------------------------------------------------------------------------
    def status(self) -> Dict:
        return {
            "receiver": self.rx.status(),
            "transmitter": {"connected": self.tx.connected, "port": self.tx.port},
            "simulation": self.sim is not None,
            "model": self.engine.info(),
            "recording": self.recording.status() if self.recording else None,
            "last_recording": self.last_recording,
            "training": self.training,
            "quality": dict(self.quality),
            "verdicts": dict(self.verdicts),
            "clients": len(self.clients),
        }

    def measured_clock(self, code: str) -> Optional[float]:
        vals = self.clock_by_code.get(code)
        if vals:
            return statistics.median(vals)
        with Session(db_engine) as s:
            rows = s.exec(select(Experiment).where(Experiment.dominant_code == code)).all()
        clocks = [r.clock_t_us for r in rows if r.clock_t_us]
        return statistics.median(clocks) if clocks else None


hub = Hub()
