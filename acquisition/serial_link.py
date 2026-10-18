"""
acquisition/serial_link.py
--------------------------
Threaded serial links to the two ESP32 nodes.

ReceiverLink   one long-lived reader for the RX node (or the virtual one). Every
               parsed message is fanned out to subscribers; recording jobs and
               the live inference engine subscribe instead of owning the port, so
               starting/stopping a recording never interrupts live telemetry.
TransmitterLink a small command channel to the TX/attacker node.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Dict, List, Optional

from acquisition.protocol import parse_line

logger = logging.getLogger("SerialLink")

try:
    import serial
    from serial.tools import list_ports
    SERIAL_AVAILABLE = True
except ImportError:  # pragma: no cover
    serial = None
    list_ports = None
    SERIAL_AVAILABLE = False


def available_ports() -> List[Dict]:
    if not SERIAL_AVAILABLE:
        return []
    out = []
    for p in list_ports.comports():
        likely = any(k in (p.description or "").lower() + (p.device or "").lower()
                     for k in ("cp210", "usbserial", "ch340", "wch", "usbmodem", "uart", "ttyusb", "ttyacm"))
        out.append({"device": p.device, "description": p.description or "", "hwid": p.hwid or "",
                    "likely_esp32": likely})
    return out


Subscriber = Callable[[Dict], None]


class ReceiverLink:
    def __init__(self):
        self.mode: str = "disconnected"         # disconnected | hardware | simulation
        self.port: Optional[str] = None
        self.baud: int = 921600
        self.hello: Optional[Dict] = None
        self.last_stats: Optional[Dict] = None
        self.last_error: str = ""
        self.lines_rx = 0
        self.frames_rx = 0
        self.connected_since: Optional[float] = None
        self.last_frame_time: Optional[float] = None
        self._ser = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._subs: Dict[int, Subscriber] = {}
        self._next_id = 1
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()

    # ---- subscription -----------------------------------------------------
    def subscribe(self, cb: Subscriber) -> int:
        with self._lock:
            sid = self._next_id
            self._next_id += 1
            self._subs[sid] = cb
            return sid

    def unsubscribe(self, sid: int) -> None:
        with self._lock:
            self._subs.pop(sid, None)

    def _publish(self, msg: Dict) -> None:
        with self._lock:
            subs = list(self._subs.values())
        for cb in subs:
            try:
                cb(msg)
            except Exception as exc:  # a broken subscriber must not kill acquisition
                logger.exception("subscriber error: %s", exc)

    # ---- lifecycle ----------------------------------------------------------
    def connect_hardware(self, port: str, baud: int = 921600) -> None:
        if not SERIAL_AVAILABLE:
            raise RuntimeError("pyserial is not installed")
        self.disconnect()
        self.mode, self.port, self.baud = "hardware", port, baud
        self._start()

    def connect_simulation(self, sim_port) -> None:
        self.disconnect()
        self.mode, self.port, self.baud = "simulation", "virtual://rf-lab", 0
        self._ser = sim_port
        self._start()

    def _start(self) -> None:
        self.hello, self.last_stats, self.last_error = None, None, ""
        self.lines_rx = self.frames_rx = 0
        self.connected_since = time.time()
        self._running = True
        self._thread = threading.Thread(target=self._run, name="RxLink", daemon=True)
        self._thread.start()

    def disconnect(self) -> None:
        self._running = False
        ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)
        self._thread = None
        self.mode = "disconnected"
        self.connected_since = None

    def send(self, command: str) -> bool:
        with self._write_lock:
            if self._ser is None:
                return False
            try:
                self._ser.write((command.strip() + "\n").encode())
                return True
            except Exception as exc:
                self.last_error = str(exc)
                return False

    def status(self) -> Dict:
        return {
            "mode": self.mode,
            "port": self.port,
            "baud": self.baud,
            "connected": self.mode != "disconnected" and self._ser is not None,
            "hello": self.hello,
            "stats": self.last_stats,
            "lines_rx": self.lines_rx,
            "frames_rx": self.frames_rx,
            "last_error": self.last_error,
            "connected_since": self.connected_since,
            "last_frame_age_s": None if self.last_frame_time is None
            else round(time.time() - self.last_frame_time, 2),
        }

    # ---- reader thread --------------------------------------------------------
    def _open(self):
        s = serial.Serial(self.port, self.baud, timeout=0.5)
        # Opening the port toggles DTR/RTS which resets most ESP32 dev boards.
        time.sleep(0.05)
        return s

    def _run(self) -> None:
        backoff = 0.5
        while self._running:
            try:
                if self._ser is None:
                    if self.mode != "hardware":
                        break
                    self._ser = self._open()
                    logger.info("receiver connected on %s @ %d", self.port, self.baud)
                    backoff = 0.5
                    self.send("INFO")
                raw = self._ser.readline()
                if not raw:
                    continue
                self.lines_rx += 1
                msg = parse_line(raw.decode("utf-8", errors="ignore"))
                if msg is None:
                    continue
                msg["rx_time"] = time.time()
                t = msg["type"]
                if t == "hello":
                    self.hello = msg
                elif t == "stats":
                    self.last_stats = msg
                elif t == "frame":
                    self.frames_rx += 1
                    self.last_frame_time = msg["rx_time"]
                self._publish(msg)
            except Exception as exc:
                if not self._running:
                    break
                self.last_error = str(exc)
                logger.warning("receiver link error: %s (retry in %.1fs)", exc, backoff)
                try:
                    if self._ser is not None and self.mode == "hardware":
                        self._ser.close()
                except Exception:
                    pass
                if self.mode == "hardware":
                    self._ser = None
                time.sleep(backoff)
                backoff = min(backoff * 2, 5.0)


class TransmitterLink:
    """Command channel to the ESP32-S3 TX / attacker node."""

    def __init__(self):
        self.port: Optional[str] = None
        self._ser = None
        self.log: List[Dict] = []
        self._thread: Optional[threading.Thread] = None
        self._running = False

    @property
    def connected(self) -> bool:
        return self._ser is not None

    def connect(self, port: str, baud: int = 115200) -> None:
        if not SERIAL_AVAILABLE:
            raise RuntimeError("pyserial is not installed")
        self.disconnect()
        self._ser = serial.Serial(port, baud, timeout=0.5)
        self.port = port
        self._running = True
        self._thread = threading.Thread(target=self._run, name="TxLink", daemon=True)
        self._thread.start()
        time.sleep(1.5)  # board reset after opening the port
        self.send("INFO")

    def disconnect(self) -> None:
        self._running = False
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
        self._ser = None
        self.port = None

    def send(self, command: str) -> None:
        if self._ser is None:
            raise RuntimeError("transmitter node not connected")
        self._ser.write((command.strip() + "\n").encode())
        self._append({"type": "cmd", "cmd": command.strip(), "time": time.time()})

    def _append(self, entry: Dict) -> None:
        self.log.append(entry)
        del self.log[:-100]

    def _run(self) -> None:
        while self._running and self._ser is not None:
            try:
                raw = self._ser.readline()
                if raw:
                    msg = parse_line(raw.decode("utf-8", errors="ignore"))
                    if msg:
                        msg["time"] = time.time()
                        self._append(msg)
            except Exception:
                time.sleep(0.5)
