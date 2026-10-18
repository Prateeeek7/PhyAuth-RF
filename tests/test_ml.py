import json

import numpy as np
import pytest
import torch

from ml.authenticator import OpenSetAuthenticator, ledoit_wolf
from ml.loss import BatchHardTripletLoss
from ml.models import EdgeMLP, FingerprintNet
from dsp.pulse_dsp import NUM_FEATURES, SEQ_CHANNELS, SEQ_LEN


def test_model_shapes_and_normalised_embeddings():
    z = torch.randn(8, NUM_FEATURES)
    s = torch.randn(8, SEQ_CHANNELS, SEQ_LEN)
    for m in (FingerprintNet(4), EdgeMLP(4)):
        m.eval()
        e, logits = m(z, s)
        assert logits.shape == (8, 4)
        assert torch.allclose(e.norm(dim=1), torch.ones(8), atol=1e-5)


def test_triplet_loss_prefers_separated_clusters():
    loss = BatchHardTripletLoss(margin=0.3)
    y = torch.tensor([0, 0, 1, 1])
    good = torch.nn.functional.normalize(torch.tensor([[1, 0.], [1, .05], [0, 1.], [.05, 1]]), dim=1)
    bad = torch.nn.functional.normalize(torch.tensor([[1, 0.], [0, 1.], [1, .05], [.05, 1]]), dim=1)
    assert loss(good, y) < loss(bad, y)


def test_authenticator_roundtrip_and_open_set():
    rng = np.random.default_rng(0)
    a = OpenSetAuthenticator()
    a.calibrate_device("A", rng.normal(0, 0.05, (200, 8)) + 1.0, target_frr=0.02)
    ok, d, t = a.authenticate("A", np.ones(8))
    assert ok and d < t
    assert not a.authenticate("A", np.zeros(8))[0]
    assert not a.authenticate("UNKNOWN", np.ones(8))[0]
    b = OpenSetAuthenticator.from_dict(json.loads(json.dumps(a.to_dict())))
    assert b.distance("A", np.ones(8)) == pytest.approx(a.distance("A", np.ones(8)))


def test_ledoit_wolf_shrinks_small_samples():
    rng = np.random.default_rng(0)
    _, a_small = ledoit_wolf(rng.normal(size=(20, 16)))
    _, a_big = ledoit_wolf(rng.normal(size=(5000, 16)) * np.linspace(0.1, 3, 16))
    assert a_small > 0.5 and a_big < 0.05


def test_end_to_end_training_on_simulated_lab(tmp_path):
    """Small but complete run: simulate -> train -> evaluate -> export header."""
    from ml.export_edge import build_header
    from ml.train import train_pipeline
    from sim.rf_simulator import RFWorld, generate_dataset_lines

    data = tmp_path / "data"
    data.mkdir()
    devices = ["FOB_A", "EMU_1", "CLONE_A"]
    files = {}
    for rec in generate_dataset_lines(devices, presses_per_device=10, sessions=2, seed=3):
        key = (rec["session_id"], rec["device_id"])
        if key not in files:
            files[key] = open(data / f"{key[0]}_{key[1]}.jsonl", "w")
        files[key].write(json.dumps(rec) + "\n")
    for f in files.values():
        f.close()
    w = RFWorld(seed=3)
    codes = {k: f"{m.code:06x}/24" for k, m in w.tx.items()}
    report = train_pipeline(data, tmp_path / "ckpt", ["FOB_A", "EMU_1"], codes, epochs=12)

    edge = report["models"]["edge"]
    assert edge["closed_set"]["accuracy"] > 0.9
    clone = [a for a in edge["attacks"] if a["device"] == "CLONE_A"][0]
    assert clone["kind"] == "code_clone" and clone["claimed"] == "FOB_A"
    assert clone["rejection_rate"] >= 0.8 and clone["combined_rejection_rate"] >= clone["rejection_rate"]
    live = report["liveness"]["profiles"]
    assert not live["EMU_1"]["active"]                    # the ESP32 node never gets the check
    hdr = build_header(tmp_path / "ckpt", device_codes=codes)
    assert "PHYAUTH_MODEL_PRESENT 1" in hdr["text"] and hdr["devices"] == ["FOB_A", "EMU_1"]
