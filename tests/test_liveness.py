"""Start-up drift liveness: rule, profile activation and the simulated kit."""

from collections import Counter

import numpy as np

from dsp.pulse_dsp import analyze_frame
from ml import liveness as lv
from sim.rf_simulator import RFWorld


def _press_drifts(world, name, presses=25):
    out = []
    for _ in range(presses):
        frames = [analyze_frame(f["d"], f["g"]) for f in world.press(name)]
        frames = [a for a in frames if a.ok]
        code = Counter(a.code for a in frames).most_common(1)[0][0]
        d = lv.press_drift_ppm([a.clock_t_ns / 1000.0 for a in frames if a.code == code])
        if d is not None:
            out.append(d)
    return np.array(out)


def test_rule():
    assert lv.press_drift_ppm([301.0, 300.0]) is None            # too few frames
    assert abs(lv.press_drift_ppm([303.0, 301.0, 300.5, 300.0]) - 10000.0) < 1e-6
    prof = {"active": True, "median_ppm": 10000.0, "tolerance_ppm": 2000.0}
    assert lv.check(prof, 9000.0) is True
    assert lv.check(prof, 300.0) is False
    assert lv.check({"active": False}, 300.0) is None              # never judges inactive devices
    assert lv.check(prof, None) is None


def test_fob_drifts_esp_node_does_not():
    # Simulator calibrated on a real remote: about -500 ppm per press.
    w = RFWorld(seed=21)
    fob, clone = (_press_drifts(w, n, presses=40) for n in ("FOB_A", "CLONE_A"))
    assert np.median(fob) < -200
    assert abs(np.median(clone)) < 600 and np.std(clone) < 200


def test_activation_needs_window_excluding_zero():
    class FS:  # minimal FrameSet stand-in: one 4-frame press per burst
        pass
    def fs_with(drifts_ppm):
        fs = FS()
        fs.bursts, fs.times, fs.device_ids, rows = [], [], [], []
        for b, d in enumerate(drifts_ppm):
            t_last = 335.0
            for k, t in enumerate([t_last * (1 + d * 1e-6), t_last, t_last, t_last]):
                fs.bursts.append(f"b{b}"); fs.times.append(b * 10 + k); fs.device_ids.append("FOB_A")
                row = np.zeros(11); row[lv.CLOCK_IDX] = t; rows.append(row)
        fs.X = np.array(rows)
        return fs
    rng = np.random.default_rng(0)
    weak = fs_with(rng.normal(-530, 200, 30))            # like the first real capture
    strong = fs_with(rng.normal(-5000, 200, 30))
    assert not lv.fit_profiles(weak, range(120), ["FOB_A"])["FOB_A"]["active"]
    assert lv.fit_profiles(strong, range(120), ["FOB_A"])["FOB_A"]["active"]
