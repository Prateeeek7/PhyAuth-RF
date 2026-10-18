"""
acquisition/protocol.py
-----------------------
Parser for the receiver serial protocol.

v2 (firmware 2.x, one JSON object per line):
    {"type":"hello", "fw":"phyauth-rx", "ver":"2.0.0", ...}
    {"type":"frame", "seq":12, "t_us":123456, "g":9876543, "n":49, "d":[ns, ...]}
    {"type":"stats", "edges":..., "frames":..., "noise_eps":...}
    {"type":"auth",  "verdict":"AUTHENTIC", ...}          (on-chip decision)
    {"type":"ack"|"err", ...}

v1 (legacy firmware): {"device_id":"DEV_A","intervals":[us, ..., 0, 0]}
Legacy records are converted to frames (zero padding removed, us -> ns,
first pulse assumed HIGH). Their timing is only 1 us resolution.
"""

from __future__ import annotations

import json
from typing import Dict, Optional


def parse_line(line: str) -> Optional[Dict]:
    line = line.strip()
    if not line or line[0] != "{":
        return None
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(msg, dict):
        return None
    return normalize(msg)


def normalize(msg: Dict) -> Optional[Dict]:
    """Return a v2-shaped message or None if unusable."""
    t = msg.get("type")
    if t == "frame":
        d = msg.get("d")
        if not isinstance(d, list) or not d:
            return None
        msg["d"] = [int(v) for v in d]
        msg.setdefault("g", -1)
        msg.setdefault("t_us", None)
        msg["n"] = len(msg["d"])
        return msg
    if t in ("hello", "stats", "auth", "ack", "err", "tx"):
        return msg
    if "intervals" in msg and isinstance(msg["intervals"], list):
        d = [int(v) * 1000 for v in msg["intervals"] if v and v > 0]
        if not d:
            return None
        out = {"type": "frame", "seq": None, "t_us": None, "g": -1, "n": len(d), "d": d,
               "legacy": True}
        if "device_id" in msg:
            out["device_id"] = msg["device_id"]
        return out
    if msg.get("debug") == "heartbeat":
        return {"type": "stats", "edges": msg.get("interrupts", 0), "legacy": True}
    return None
