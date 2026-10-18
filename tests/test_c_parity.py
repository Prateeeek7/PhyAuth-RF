"""
The ESP32 firmware computes fingerprint features in C (phyauth_dsp.c). This
test compiles that exact file for the host and checks it against the Python
implementation on simulated frames, glitchy frames and noise.
"""

import ctypes
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from dsp.pulse_dsp import NUM_FEATURES, analyze_frame
from sim.rf_simulator import Channel, RFWorld

ROOT = Path(__file__).resolve().parents[1]
C_SRC = ROOT / "firmware" / "esp32_receiver" / "src" / "phyauth_dsp.c"
BUILD = ROOT / "tests" / "_build"


class PaResult(ctypes.Structure):
    _fields_ = [
        ("status", ctypes.c_int),
        ("clock_t_ns", ctypes.c_double),
        ("n_pairs", ctypes.c_int),
        ("n_bits", ctypes.c_int),
        ("code", ctypes.c_uint64),
        ("pair_resid_rms", ctypes.c_double),
        ("features", ctypes.c_double * NUM_FEATURES),
    ]


STATUS = ["ok", "too_few_pulses", "clock_fit_failed", "too_few_pairs",
          "timing_inconsistent", "off_grid_pulse"]


@pytest.fixture(scope="module")
def lib():
    cc = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    if cc is None:
        pytest.skip("no C compiler available")
    BUILD.mkdir(exist_ok=True)
    so = BUILD / "libphyauth.so"
    subprocess.check_call([cc, "-O2", "-shared", "-fPIC", "-o", str(so), str(C_SRC), "-lm"])
    lib = ctypes.CDLL(str(so))
    lib.pa_analyze.argtypes = [ctypes.POINTER(ctypes.c_int32), ctypes.c_int, ctypes.c_int64,
                               ctypes.c_int32, ctypes.POINTER(PaResult)]
    f = ctypes.POINTER(ctypes.c_float)
    lib.pa_embed.argtypes = [ctypes.POINTER(ctypes.c_double), ctypes.c_int, f, f, f, f, ctypes.c_int,
                             f, f, ctypes.c_int, f]
    lib.pa_mahalanobis.argtypes = [f, f, f, ctypes.c_int]
    lib.pa_mahalanobis.restype = ctypes.c_float
    return lib


def c_analyze(lib, pulses, gap):
    arr = (ctypes.c_int32 * len(pulses))(*pulses)
    res = PaResult()
    lib.pa_analyze(arr, len(pulses), gap, 80_000, ctypes.byref(res))
    return res


def _frames():
    w = RFWorld(seed=11)
    out = []
    for dist in (1.0, 6.0, 12.0):
        w.channel = Channel(dist, 45.0)
        for name in w.tx:
            out += w.press(name, frames=5)
    from tests.test_pulse_dsp import _ev1527
    for d in (-107.0, -60.0, 40.0, 100.0):          # strong slicer distortion (real remote)
        p, g = _ev1527(0x936768, 335.0, d)
        out.append({"d": p, "g": g})
    rng = np.random.default_rng(3)
    for _ in range(20):  # pure noise frames
        out.append({"d": [int(x) for x in rng.integers(20_000, 2_000_000, size=int(rng.integers(16, 80)))],
                    "g": -1})
    return out


def test_features_match_python(lib):
    n_ok = 0
    for fr in _frames():
        py = analyze_frame(fr["d"], fr["g"])
        c = c_analyze(lib, fr["d"], fr["g"])
        assert STATUS[c.status] == py.reason, (STATUS[c.status], py.reason)
        if not py.ok:
            continue
        n_ok += 1
        assert c.clock_t_ns == pytest.approx(py.clock_t_ns, rel=1e-12)
        assert c.n_pairs == py.n_pairs
        assert format(c.code, "x") == format(int(py.code_hex, 16), "x")
        cf = np.array(list(c.features))
        np.testing.assert_allclose(cf, py.features, rtol=1e-9, atol=1e-9, equal_nan=True)
    assert n_ok > 40


def test_embedding_and_distance_match_numpy(lib):
    rng = np.random.default_rng(0)
    nf, h1, emb = NUM_FEATURES, 32, 16
    feats = rng.normal(size=nf)
    feats[7] = np.nan
    mean, std = rng.normal(size=nf).astype(np.float32), rng.uniform(0.5, 2, nf).astype(np.float32)
    w1, b1 = rng.normal(size=(h1, nf)).astype(np.float32), rng.normal(size=h1).astype(np.float32)
    w2, b2 = rng.normal(size=(emb, h1)).astype(np.float32), rng.normal(size=emb).astype(np.float32)

    x = np.where(np.isnan(feats), 0.0, (feats - mean) / std).astype(np.float32)
    h = np.maximum(w1 @ x + b1, 0)
    e = w2 @ h + b2
    e = e / np.linalg.norm(e)

    fp = ctypes.POINTER(ctypes.c_float)
    out = (ctypes.c_float * emb)()

    def ptr(a):
        return np.ascontiguousarray(a, dtype=np.float32).ctypes.data_as(fp)

    keep = [mean, std, w1, b1, w2, b2]
    lib.pa_embed(np.ascontiguousarray(feats).ctypes.data_as(ctypes.POINTER(ctypes.c_double)), nf,
                 ptr(keep[0]), ptr(keep[1]), ptr(keep[2]), ptr(keep[3]), h1,
                 ptr(keep[4]), ptr(keep[5]), emb, out)
    np.testing.assert_allclose(np.array(out[:]), e, rtol=1e-4, atol=1e-5)

    c = rng.normal(size=emb).astype(np.float32)
    a = rng.normal(size=(emb, emb))
    ci = (a @ a.T + np.eye(emb)).astype(np.float32)
    d_np = float(np.sqrt((e - c) @ ci @ (e - c)))
    d_c = lib.pa_mahalanobis(ptr(e), ptr(c), ptr(ci), emb)
    assert d_c == pytest.approx(d_np, rel=1e-4)
