import numpy as np

from dsp.pulse_dsp import FEATURE_NAMES, analyze_frame, estimate_clock, merge_glitches
from sim.rf_simulator import Channel, RFWorld, make_clone, make_fob


def ev1527(code: int, t_ns: float, high_bias: float = 0.0, with_tail: bool = True):
    d = []
    for b in range(23, -1, -1):
        bit = (code >> b) & 1
        h, l = (3, 1) if bit else (1, 3)
        d += [int(h * t_ns + high_bias), int(l * t_ns - high_bias)]
    if with_tail:
        d.append(int(t_ns + high_bias))
    return d


def test_ideal_frame_decodes_code_and_clock():
    fa = analyze_frame(ev1527(0xA5C30F, 350_000.0), gap_ns=int(31 * 350_000))
    assert fa.ok, fa.reason
    assert fa.code == "a5c30f/24"
    assert abs(fa.clock_t_ns - 350_000) < 1
    assert abs(fa.features[FEATURE_NAMES.index("sync_ratio")] - 31) < 1e-6


def test_clock_estimate_is_invariant_to_duty_distortion():
    # a slicer/PA asymmetry stretches HIGHs and shrinks LOWs; T must not move
    for bias in (-40_000, 0, 40_000):
        t = estimate_clock(ev1527(0x5A3C91, 300_000.0, high_bias=bias))
        assert abs(t - 300_000) < 1, (bias, t)


def test_glitch_merge_restores_alternation():
    d = [300_000, 900_000, 300_000, 900_000]
    glitched = [300_000, 400_000, 30_000, 470_000, 300_000, 900_000]  # glitch inside the 1st LOW
    assert merge_glitches(glitched, 80_000) == d
    assert merge_glitches([20_000, 5_000] + d, 80_000) == d             # leading glitch


def test_noise_is_rejected():
    rng = np.random.default_rng(1)
    rejected = 0
    for _ in range(200):
        fa = analyze_frame(list(rng.integers(20_000, 2_000_000, size=int(rng.integers(16, 60)))))
        rejected += not fa.ok
    assert rejected >= 198


def test_features_separate_fob_from_clone():
    fob = make_fob("F", 1)
    clone = make_clone("C", fob)
    w = RFWorld()
    w.tx = {"F": fob, "C": clone}
    w.new_session()
    jit = {}
    for name in ("F", "C"):
        vals = [analyze_frame(f["d"], f["g"]) for f in w.press(name, frames=10)]
        vals = [v for v in vals if v.ok]
        # same claim (a noise-contaminated first frame may decode garbage; the
        # burst logic and code-lock ignore such single frames)
        assert sum(v.code == f"{fob.code:06x}/24" for v in vals) >= len(vals) - 1
        vals = [v for v in vals if v.code == f"{fob.code:06x}/24"]
        jit[name] = np.median([v.features[FEATURE_NAMES.index("pair_jitter_ppm")] for v in vals])
    assert jit["F"] > 3 * jit["C"]          # RC oscillator jitter vs crystal


def test_far_distance_still_decodes():
    w = RFWorld()
    w.channel = Channel(8.0, 90.0)
    ok = [analyze_frame(f["d"], f["g"]).ok for f in w.press("FOB_A", frames=12)]
    assert sum(ok) >= 6


def _ev1527(code: int, t_us: float, d_us: float):
    """Ideal EV1527 frame with HIGHs shortened / LOWs lengthened by d (slicer)."""
    out = []
    for b in range(23, -1, -1):
        h, l = (3, 1) if (code >> b) & 1 else (1, 3)
        out += [int((h * t_us + d_us) * 1000), int((l * t_us - d_us) * 1000)]
    out.append(int((t_us + d_us) * 1000))          # sync HIGH; sync LOW is the gap
    return out, int((31 * t_us - d_us) * 1000)


def test_strong_duty_distortion_keeps_ev1527_grid():
    # First real capture: T = 335 us, HIGHs shortened by ~107 us (0.32 T).
    # A naive short-pulse clock locks onto 2T/3 and decodes a 4:2/1:5 grid.
    pulses, gap = _ev1527(0xA5C3E1, 335.0, -107.0)
    fa = analyze_frame(pulses, gap)
    assert fa.ok, fa.reason
    assert abs(fa.clock_t_ns / 1000 - 335.0) < 0.5
    assert fa.code == "a5c3e1/24"
    assert abs(fa.features[FEATURE_NAMES.index("sync_ratio")] - 31.0) < 0.5


def test_real_capture_ev1527_remote():
    """First real capture (classic ESP32 + SRX882, one EV1527 remote, 5 presses,
    plus room noise): the remote must decode at T ~ 335 us with the EV1527
    31 T sync, and the noise must not be mistaken for it."""
    import json
    from collections import Counter
    from pathlib import Path
    path = Path(__file__).parent / "data" / "real_ev1527_srx882.jsonl"
    frames = [json.loads(ln) for ln in path.open()]
    good = [analyze_frame(f["d"], f.get("g", -1)) for f in frames]
    codes = Counter(a.code for a in good if a.ok)
    code, n = codes.most_common(1)[0]
    assert code == "936768/24" and n >= 35
    remote = [a for a in good if a.ok and a.code == code]
    t_us = np.median([a.clock_t_ns / 1000 for a in remote])
    assert 333 < t_us < 337
    sync = np.median([a.features[FEATURE_NAMES.index("sync_ratio")] for a in remote])
    assert 30.5 < sync < 31.5
    assert all(np.isfinite(a.features).all() for a in remote)


def test_real_over_the_air_esp32_node():
    """ESP32-S3 + STX882 node -> SRX882 receiver: every firmware profile and the
    clone of the real remote decode with the programmed code and period, and the
    clone's clock matches the remote, so only physical impairments remain."""
    import json
    from pathlib import Path
    path = Path(__file__).parent / "data" / "real_ota_esp32s3_stx882.jsonl"
    frames = [json.loads(ln) for ln in path.open()]
    expect = {"EMU_1": ("5a3c91/24", 318.0), "EMU_2": ("1e77c4/24", 331.0),
              "EMU_3": ("9b0d2a/24", 305.5), "CLONE_A": ("936768/24", 334.9)}
    for label, (code, t_us) in expect.items():
        res = [analyze_frame(f["d"], f.get("g", -1)) for f in frames if f["label"] == label]
        good = [a for a in res if a.ok and a.code == code]
        assert len(good) >= 72, label            # 8 presses x 10 frames; room noise aside
        from collections import Counter
        assert Counter(a.code for a in res if a.ok).most_common(1)[0][0] == code, label
        assert abs(np.median([a.clock_t_ns for a in good]) / 1000 - t_us) < 0.3, label
