import time

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:      # runs lifespan: DB init + simulator
        yield c


def test_root_and_status(client):
    r = client.get("/")
    assert r.status_code == 200 and r.json()["status"] == "online"
    st = client.get("/api/hardware/status").json()
    assert st["receiver"]["mode"] == "simulation"


def test_device_crud(client):
    r = client.post("/api/devices", json={"device_id": "TEST_01", "name": "Fob", "model_info": "EV1527"})
    assert r.status_code == 201
    assert client.post("/api/devices", json={"device_id": "TEST_01", "name": "x"}).status_code == 400
    r = client.patch("/api/devices/TEST_01", json={"is_authorized": False, "code": "abc123/24"})
    assert r.json()["is_authorized"] is False and r.json()["code"] == "abc123/24"
    assert client.delete("/api/devices/TEST_01").status_code == 204
    assert client.get("/api/devices/TEST_01").status_code == 404


def test_simulated_recording_learns_code(client):
    client.post("/api/devices", json={"device_id": "FOB_A", "name": "Fob A"})
    r = client.post("/api/recordings/start", json={"device_id": "FOB_A", "session_id": "t1",
                                                   "target_good_frames": 20, "timeout_s": 30})
    assert r.status_code == 202, r.text
    for _ in range(80):
        time.sleep(0.25)
        st = client.get("/api/recordings/status").json()
        if st["active"] is None and st["last"]:
            break
    assert st["last"]["frames_good"] >= 20
    dev = client.get("/api/devices/FOB_A").json()
    assert dev["code"] and dev["code"].endswith("/24")
    assert any(r["transmitter_id"] == "FOB_A" for r in client.get("/api/recordings").json())


def test_recording_requires_registered_device(client):
    r = client.post("/api/recordings/start", json={"device_id": "NOPE"})
    assert r.status_code == 404


def test_report_absent_before_training(client):
    assert client.get("/api/models/report").status_code == 404
