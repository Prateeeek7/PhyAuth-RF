/*
 * phyauth_lock.c — see phyauth_lock.h.
 */
#include "phyauth_lock.h"

#include <string.h>

static int elapsed(uint32_t now, uint32_t since, uint32_t span) {
  return (int32_t)(now - since) >= (int32_t)span;
}

void pa_lock_init(pa_lock_t *lk, uint32_t gap_ms, uint32_t relock_ms, uint32_t lockout_ms) {
  memset(lk, 0, sizeof(*lk));
  lk->owner = -1;
  lk->state = PA_LOCK_DISABLED;
  lk->gap_ms = gap_ms;
  lk->relock_ms = relock_ms;
  lk->lockout_ms = lockout_ms;
}

int pa_lock_set(pa_lock_t *lk, int owner, const uint8_t *keys, int len) {
  if (owner < 0 || len < PA_LOCK_MIN || len > PA_LOCK_MAX) return 0;
  memcpy(lk->pattern, keys, len);
  lk->len = len;
  lk->owner = owner;
  lk->n = 0;
  lk->spoiled = 0;
  lk->fails = 0;
  lk->state = PA_LOCK_LOCKED;
  return 1;
}

void pa_lock_clear(pa_lock_t *lk) {
  pa_lock_init(lk, lk->gap_ms, lk->relock_ms, lk->lockout_ms);
}

void pa_lock_learn(pa_lock_t *lk, int owner) {
  lk->owner = owner;
  lk->state = PA_LOCK_LEARN;
  lk->learn_stage = 0;
  lk->learn1_len = 0;
  lk->n = 0;
  lk->spoiled = 0;
}

void pa_lock_force_lock(pa_lock_t *lk) {
  if (lk->len >= PA_LOCK_MIN && lk->state != PA_LOCK_LOCKOUT) {
    lk->state = PA_LOCK_LOCKED;
    lk->n = 0;
    lk->spoiled = 0;
  }
}

static pa_lock_event_t fail(pa_lock_t *lk, uint32_t now, pa_lock_event_t ev) {
  lk->n = 0;
  lk->spoiled = 0;
  lk->fails++;
  if (lk->fails >= PA_LOCK_MAX_FAILS) {
    int extra = lk->fails - PA_LOCK_MAX_FAILS;           /* 30 s, 60 s, 120 s, ... max 8x */
    uint32_t span = lk->lockout_ms << (extra > 3 ? 3 : extra);
    lk->lockout_until_ms = now + span;
    lk->state = PA_LOCK_LOCKOUT;
    return PA_EV_LOCKOUT;
  }
  return ev;
}

pa_lock_event_t pa_lock_press(pa_lock_t *lk, int authentic, int dev, uint8_t key, uint32_t now) {
  if (lk->state == PA_LOCK_DISABLED) return PA_EV_NONE;
  if (lk->state == PA_LOCK_LOCKOUT) return authentic ? PA_EV_IGNORED : PA_EV_FOREIGN;

  if (lk->state == PA_LOCK_LEARN) {
    if (!authentic || dev != lk->owner) return authentic ? PA_EV_IGNORED : PA_EV_FOREIGN;
    if (lk->n < PA_LOCK_MAX) lk->entry[lk->n++] = key;
    lk->last_press_ms = now;
    return PA_EV_LEARN_STEP;
  }

  if (!authentic) {                      /* clone / unknown transmitter or unclear press */
    lk->last_press_ms = now;
    lk->spoiled = 1;                     /* counted; the attempt fails once, at full length */
    if (lk->n < PA_LOCK_MAX) lk->entry[lk->n] = key;
    lk->n++;
    if (lk->n < lk->len) return PA_EV_FOREIGN;
  } else {
    if (dev != lk->owner) return PA_EV_IGNORED;   /* another enrolled device */
    lk->last_press_ms = now;
    if (lk->n < PA_LOCK_MAX) lk->entry[lk->n] = key;
    lk->n++;
    if (lk->n < lk->len) return PA_EV_PROGRESS;  /* never reveal which press was wrong */
  }

  int ok = !lk->spoiled && lk->n == lk->len && memcmp(lk->entry, lk->pattern, lk->len) == 0;
  lk->n = 0;
  lk->spoiled = 0;
  if (!ok) return fail(lk, now, PA_EV_FAIL);
  lk->fails = 0;
  if (lk->state == PA_LOCK_UNLOCKED) {
    lk->state = PA_LOCK_LOCKED;
    return PA_EV_LOCK;
  }
  lk->state = PA_LOCK_UNLOCKED;
  lk->unlocked_ms = now;
  return PA_EV_UNLOCK;
}

pa_lock_event_t pa_lock_tick(pa_lock_t *lk, uint32_t now) {
  switch (lk->state) {
    case PA_LOCK_LEARN:
      if (lk->n == 0 || !elapsed(now, lk->last_press_ms, lk->gap_ms)) return PA_EV_NONE;
      if (lk->n < PA_LOCK_MIN || lk->n > PA_LOCK_MAX) {   /* too short / long: start over */
        lk->n = 0;
        lk->learn_stage = 0;
        return PA_EV_LEARN_MISMATCH;
      }
      if (lk->learn_stage == 0) {
        memcpy(lk->learn1, lk->entry, lk->n);
        lk->learn1_len = lk->n;
        lk->n = 0;
        lk->learn_stage = 1;
        return PA_EV_LEARN_CONFIRM;
      }
      if (lk->n == lk->learn1_len && memcmp(lk->entry, lk->learn1, lk->n) == 0) {
        int len = lk->n;
        pa_lock_set(lk, lk->owner, lk->learn1, len);
        return PA_EV_LEARNED;
      }
      lk->n = 0;
      lk->learn_stage = 0;
      return PA_EV_LEARN_MISMATCH;
    case PA_LOCK_LOCKED:
    case PA_LOCK_UNLOCKED:
      if (lk->n > 0 && elapsed(now, lk->last_press_ms, lk->gap_ms)) {   /* walked away: clear, no failure */
        lk->n = 0;
        lk->spoiled = 0;
        return PA_EV_ABANDONED;
      }
      if (lk->state == PA_LOCK_UNLOCKED && lk->relock_ms && lk->n == 0 &&
          elapsed(now, lk->unlocked_ms, lk->relock_ms)) {
        lk->state = PA_LOCK_LOCKED;
        return PA_EV_AUTO_RELOCK;
      }
      return PA_EV_NONE;
    case PA_LOCK_LOCKOUT:
      if (elapsed(now, lk->lockout_until_ms, 0)) {
        lk->state = PA_LOCK_LOCKED;
        lk->n = 0;
        return PA_EV_LOCKOUT_END;
      }
      return PA_EV_NONE;
    default:
      return PA_EV_NONE;
  }
}

int pa_lock_sizeof(void) { return (int)sizeof(pa_lock_t); }
int pa_lock_state(const pa_lock_t *lk) { return (int)lk->state; }
int pa_lock_progress(const pa_lock_t *lk) { return lk->n; }
int pa_lock_length(const pa_lock_t *lk) { return lk->len; }
int pa_lock_fails(const pa_lock_t *lk) { return lk->fails; }

const char *pa_lock_state_name(int s) {
  static const char *n[] = {"DISABLED", "LOCKED", "UNLOCKED", "LOCKOUT", "LEARN"};
  return (s >= 0 && s <= 4) ? n[s] : "?";
}

const char *pa_lock_event_name(int e) {
  static const char *n[] = {"none", "progress", "unlock", "lock", "auto_relock", "fail", "foreign",
                            "lockout", "lockout_end", "ignored", "learn_step", "learn_confirm",
                            "learned", "learn_mismatch", "abandoned"};
  return (e >= 0 && e <= 14) ? n[e] : "?";
}
