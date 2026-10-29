"""
Pattern lock state machine: compiles firmware/esp32_receiver/src/phyauth_lock.c
for the host and drives it exactly as the ESP32 does.
"""

import ctypes
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "firmware" / "esp32_receiver" / "src" / "phyauth_lock.c"
BUILD = ROOT / "tests" / "_build"

ON, OFF = 8, 4
OWNER, OTHER = 0, 1
GAP, RELOCK, LOCKOUT = 3000, 15000, 30000
STATES = ["DISABLED", "LOCKED", "UNLOCKED", "LOCKOUT", "LEARN"]


@pytest.fixture(scope="module")
def lib():
    cc = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    if cc is None:
        pytest.skip("no C compiler available")
    BUILD.mkdir(exist_ok=True)
    so = BUILD / "libphyauth_lock.so"
    subprocess.check_call([cc, "-O2", "-shared", "-fPIC", "-o", str(so), str(SRC)])
    lib = ctypes.CDLL(str(so))
    lib.pa_lock_event_name.restype = ctypes.c_char_p
    lib.pa_lock_press.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint8, ctypes.c_uint32]
    lib.pa_lock_tick.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    lib.pa_lock_init.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
    lib.pa_lock_set.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    lib.pa_lock_learn.argtypes = [ctypes.c_void_p, ctypes.c_int]
    for f in ("pa_lock_state", "pa_lock_progress", "pa_lock_length", "pa_lock_fails"):
        getattr(lib, f).argtypes = [ctypes.c_void_p]
    return lib


class Lock:
    def __init__(self, lib, pattern=(ON, ON, OFF, ON, OFF, OFF, ON)):
        self.lib = lib
        self.buf = ctypes.create_string_buffer(lib.pa_lock_sizeof())
        self.t = 1000
        lib.pa_lock_init(self.buf, GAP, RELOCK, LOCKOUT)
        if pattern:
            assert lib.pa_lock_set(self.buf, OWNER, bytes(pattern), len(pattern)) == 1

    def press(self, key, authentic=True, dev=OWNER, dt=800):
        self.t += dt
        ev = self.lib.pa_lock_press(self.buf, int(authentic), dev, key, self.t)
        return self.lib.pa_lock_event_name(ev).decode()

    def tick(self, dt):
        self.t += dt
        return self.lib.pa_lock_event_name(self.lib.pa_lock_tick(self.buf, self.t)).decode()

    def enter(self, keys, **kw):
        return [self.press(k, **kw) for k in keys][-1]

    @property
    def state(self):
        return STATES[self.lib.pa_lock_state(self.buf)]


PATTERN = (ON, ON, OFF, ON, OFF, OFF, ON)


def test_correct_pattern_unlocks_and_relocks(lib):
    lk = Lock(lib)
    assert lk.state == "LOCKED"
    events = [lk.press(k) for k in PATTERN]
    assert events[:-1] == ["progress"] * 6 and events[-1] == "unlock"
    assert lk.state == "UNLOCKED"
    assert lk.enter(PATTERN) == "lock" and lk.state == "LOCKED"        # same pattern locks again


def test_wrong_pattern_fails_without_revealing_position(lib):
    lk = Lock(lib)
    wrong = (OFF,) + PATTERN[1:]
    events = [lk.press(k) for k in wrong]
    assert events[:-1] == ["progress"] * 6 and events[-1] == "fail"   # no early hint
    assert lk.state == "LOCKED"


def test_rejected_press_is_counted_and_fails_once_at_the_end(lib):
    lk = Lock(lib)
    events = [lk.press(k, authentic=(i != 2)) for i, k in enumerate(PATTERN)]
    assert events[2] == "foreign"                       # shown, but the user keeps going
    assert events[:2] + events[3:-1] == ["progress"] * (len(PATTERN) - 2)
    assert events[-1] == "fail" and lk.lib.pa_lock_fails(lk.buf) == 1   # one failure, at full length
    assert lk.enter(PATTERN) == "unlock"


def test_other_enrolled_device_is_ignored(lib):
    lk = Lock(lib)
    assert lk.press(ON, dev=OTHER) == "ignored"
    assert lk.enter(PATTERN) == "unlock"


def test_three_failures_cause_lockout_that_expires_and_grows(lib):
    lk = Lock(lib)
    for _ in range(2):
        assert lk.enter((OFF,) * 7) == "fail"
    assert lk.enter((OFF,) * 7) == "lockout" and lk.state == "LOCKOUT"
    assert lk.press(ON) == "ignored"                                   # even the right remote waits
    assert lk.tick(LOCKOUT - 1000) == "none"
    assert lk.tick(2000) == "lockout_end" and lk.state == "LOCKED"
    assert lk.enter((OFF,) * 7) == "lockout"                           # 4th failure: longer lockout
    assert lk.tick(LOCKOUT + 1000) == "none"
    assert lk.tick(LOCKOUT) == "lockout_end"
    assert lk.enter(PATTERN) == "unlock" and lk.lib.pa_lock_fails(lk.buf) == 0


def test_abandoned_attempt_is_cleared_without_failure(lib):
    lk = Lock(lib)
    lk.enter(PATTERN[:3])
    assert lk.tick(GAP + 100) == "abandoned"
    assert lk.lib.pa_lock_fails(lk.buf) == 0
    assert lk.enter(PATTERN) == "unlock"


def test_auto_relock(lib):
    lk = Lock(lib)
    lk.enter(PATTERN)
    assert lk.tick(RELOCK - 100) == "none"
    assert lk.tick(200) == "auto_relock" and lk.state == "LOCKED"


def test_learn_mode_needs_matching_confirmation(lib):
    lk = Lock(lib, pattern=None)
    assert lk.state == "DISABLED" and lk.press(ON) == "none"
    lib.pa_lock_learn(lk.buf, OWNER)
    new = (OFF, ON, ON, OFF, ON)
    assert lk.enter(new) == "learn_step"
    assert lk.tick(GAP + 100) == "learn_confirm"
    lk.enter((ON,) * 5)
    assert lk.tick(GAP + 100) == "learn_mismatch" and lk.state == "LEARN"
    lk.enter(new)
    assert lk.tick(GAP + 100) == "learn_confirm"
    lk.enter(new)
    assert lk.tick(GAP + 100) == "learned" and lk.state == "LOCKED"
    assert lib.pa_lock_length(lk.buf) == 5
    assert lk.enter(new) == "unlock"


def test_clone_presses_can_never_unlock(lib):
    lk = Lock(lib)
    assert lk.enter(PATTERN, authentic=False) == "fail"   # right buttons, wrong hardware
    assert lk.state == "LOCKED"


def test_learn_rejects_too_short_and_foreign(lib):
    lk = Lock(lib, pattern=None)
    lib.pa_lock_learn(lk.buf, OWNER)
    assert lk.press(ON, authentic=False) == "foreign"
    lk.enter((ON, OFF, ON))
    assert lk.tick(GAP + 100) == "learn_mismatch"
