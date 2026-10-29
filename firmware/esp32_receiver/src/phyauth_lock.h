/*
 * phyauth_lock.h — two-factor press-pattern lock (pure C, no hardware access).
 *
 * Factor 1 (have): every press must be decided AUTHENTIC as the lock's owner
 *                  device by the RF fingerprint (done before calling this).
 * Factor 2 (know): the sequence of buttons pressed must match the stored
 *                  pattern, e.g. ON ON OFF ON OFF OFF ON.
 *
 * The module only keeps state and returns events; the firmware turns events
 * into LED / buzzer / relay output. Time is passed in milliseconds so the same
 * code is unit-tested on the host (tests/test_lock.py).
 */
#ifndef PHYAUTH_LOCK_H
#define PHYAUTH_LOCK_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PA_LOCK_MIN 4
#define PA_LOCK_MAX 12
#define PA_LOCK_MAX_FAILS 3          /* consecutive failures before lockout */

typedef enum {
  PA_LOCK_DISABLED = 0,   /* no pattern stored */
  PA_LOCK_LOCKED = 1,
  PA_LOCK_UNLOCKED = 2,
  PA_LOCK_LOCKOUT = 3,
  PA_LOCK_LEARN = 4,
} pa_lock_state_t;

typedef enum {
  PA_EV_NONE = 0,
  PA_EV_PROGRESS,        /* correct device, press counted (pattern not revealed) */
  PA_EV_UNLOCK,
  PA_EV_LOCK,            /* pattern entered while unlocked: lock again */
  PA_EV_AUTO_RELOCK,
  PA_EV_FAIL,            /* wrong pattern, or the attempt contained a rejected press */
  PA_EV_FOREIGN,         /* press rejected by the fingerprint: counted, attempt fails at the end */
  PA_EV_LOCKOUT,         /* too many failures */
  PA_EV_LOCKOUT_END,
  PA_EV_IGNORED,         /* press during lockout, or from another enrolled device */
  PA_EV_LEARN_STEP,
  PA_EV_LEARN_CONFIRM,   /* first entry stored: repeat it to confirm */
  PA_EV_LEARNED,
  PA_EV_LEARN_MISMATCH,
  PA_EV_ABANDONED,       /* unfinished attempt cleared after a long pause (not a failure) */
} pa_lock_event_t;

typedef struct {
  uint8_t pattern[PA_LOCK_MAX];
  int len;
  int owner;                       /* enrolled device index allowed to unlock */
  uint8_t entry[PA_LOCK_MAX];
  int n;                           /* presses in the current attempt */
  int spoiled;                     /* attempt contains a foreign press */
  uint8_t learn1[PA_LOCK_MAX];
  int learn1_len;
  int learn_stage;                 /* 0 = first entry, 1 = confirmation */
  pa_lock_state_t state;
  uint32_t last_press_ms, unlocked_ms, lockout_until_ms;
  uint32_t gap_ms, relock_ms, lockout_ms;
  int fails;
} pa_lock_t;

void pa_lock_init(pa_lock_t *lk, uint32_t gap_ms, uint32_t relock_ms, uint32_t lockout_ms);
/* Store a pattern directly (keys = EV1527 key nibbles, e.g. ON = 8, OFF = 4). */
int pa_lock_set(pa_lock_t *lk, int owner, const uint8_t *keys, int len);
void pa_lock_clear(pa_lock_t *lk);
void pa_lock_learn(pa_lock_t *lk, int owner);
void pa_lock_force_lock(pa_lock_t *lk);
/* One decided button press. authentic = fingerprint verdict was AUTHENTIC. */
pa_lock_event_t pa_lock_press(pa_lock_t *lk, int authentic, int dev, uint8_t key, uint32_t now_ms);
/* Call periodically: learn step end, abandoned-attempt reset, auto-relock, lockout end. */
pa_lock_event_t pa_lock_tick(pa_lock_t *lk, uint32_t now_ms);

/* Accessors (used by the host tests through ctypes). */
int pa_lock_sizeof(void);
int pa_lock_state(const pa_lock_t *lk);
int pa_lock_progress(const pa_lock_t *lk);
int pa_lock_length(const pa_lock_t *lk);
int pa_lock_fails(const pa_lock_t *lk);
const char *pa_lock_state_name(int state);
const char *pa_lock_event_name(int ev);

#ifdef __cplusplus
}
#endif
#endif
