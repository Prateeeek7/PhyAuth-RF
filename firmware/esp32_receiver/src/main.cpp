/*
 * PhyAuth-RF receiver / verifier node — firmware v2.1
 * Board : ESP32-WROOM-32 DevKit  OR  ESP32-S3 DevKitC (N16R8) — pick the
 *         PlatformIO env that matches the board the SRX882 is wired to.
 * Radio : SRX882 superheterodyne 433.92 MHz ASK receiver
 *
 * Wiring (same on both chips)
 *   SRX882 VCC  -> 3V3        (keeps DATA at 3.3 V logic; never power it from 5 V)
 *   SRX882 GND  -> GND
 *   SRX882 DATA -> GPIO14     (override: -DRX_PIN_NUM=<gpio>)
 *   SRX882 CS   -> 3V3        (CS low = sleep: no data at all)
 *
 * Verdict indicator, no extra parts needed
 *   ESP32    : on-board blue LED (GPIO2)  solid = authentic, fast blink = rejected
 *   ESP32-S3 : on-board RGB LED           green = authentic, blinking red = rejected
 *   Optional external parts:
 *     ESP32    GPIO25 green LED, GPIO26 red LED, GPIO27 buzzer, GPIO33 relay IN
 *     ESP32-S3 GPIO5  green LED, GPIO6  red LED, GPIO7  buzzer, GPIO15 relay IN
 *
 * What it does
 *   1. A GPIO ISR timestamps every edge with the CPU cycle counter
 *      (240 MHz = 4.17 ns resolution) into a lock-free ring buffer.
 *   2. loop() turns edges into pulses, merges glitches and cuts frames at
 *      inter-frame gaps (default 4 ms of LOW).
 *   3. Each frame is streamed as one JSON line at 921600 baud (protocol v2).
 *      On the ESP32-S3 the same lines also go to the native USB port, so
 *      either USB-C connector works.
 *   4. If an edge model has been exported (src/phyauth_model.h), the node
 *      also authenticates on-chip: decode code -> embed -> Mahalanobis vs the
 *      claimed device -> burst fusion -> LED / buzzer / relay + "auth" line.
 *
 * Serial protocol v2 (one JSON object per line)
 *   {"type":"hello",...}  {"type":"frame","seq":..,"t_us":..,"g":..,"n":..,"d":[ns..]}
 *   {"type":"stats",...}  {"type":"auth",...}  {"type":"ack"|"err",...}
 * Commands (newline-terminated): PING, INFO, SET GAP <us>, SET GLITCH <us>,
 *   SET MINP <n>, MODE STREAM|EDGE|BOTH, LIVE ON|OFF, TEST
 *   Pattern lock (needs an exported model): LOCK STATUS, LOCK LEARN <dev>,
 *   LOCK SET <dev> <k,k,...> (keys: ON, OFF or EV1527 key nibble), LOCK CLEAR,
 *   LOCK NOW (lock immediately), LOCK RELOCK <s> (auto-relock, 0 = off)
 *
 * Pattern lock (two factors: this physical remote + a secret ON/OFF sequence)
 *   GPIO25 green LED : on = unlocked, short flash = press accepted,
 *                      fast blink = failed attempt, slow blink = learn mode
 *   GPIO27 buzzer    : failed attempt / foreign transmitter / lockout alarm
 *                      (5 V buzzers need an NPN transistor driver)
 *   GPIO26 red LED   : on while locked (optional)   GPIO33 relay: on while unlocked
 */
#include <Arduino.h>
#include <driver/gpio.h>
#include <esp_timer.h>
#include <soc/gpio_reg.h>

extern "C" {
#include "phyauth_dsp.h"
}
#include "phyauth_model.h"
#include "phyauth_lock.h"
#include <Preferences.h>

// ----------------------------------------------------------------------------
// Configuration
// ----------------------------------------------------------------------------
#define FW_VERSION      "2.1.0"
#define SERIAL_BAUD     921600

#ifndef RX_PIN_NUM
#define RX_PIN_NUM      14
#endif
#define RX_PIN          ((gpio_num_t)RX_PIN_NUM)

#if CONFIG_IDF_TARGET_ESP32S3
#define BOARD_NAME      "esp32s3"
#define LED_OK          5
#define LED_BAD         6
#define BUZZER_PIN      7
#define RELAY_PIN       15
#if defined(RGB_BUILTIN)
#define STATUS_RGB      1             // DevKitC on-board WS2812 (GPIO48 / GPIO38)
#else
#define STATUS_RGB      0
#define LED_STATUS      -1
#endif
// Mirror the protocol on the native USB-Serial/JTAG port as well as UART0.
#if ARDUINO_USB_MODE && !ARDUINO_USB_CDC_ON_BOOT
#define HAS_USB_CDC     1
#endif
#else
#define BOARD_NAME      "esp32"
#define STATUS_RGB      0
#define LED_STATUS      2             // blue LED on most ESP32 DevKits
#define LED_OK          25
#define LED_BAD         26
#define BUZZER_PIN      27
#define RELAY_PIN       33
#endif
#ifndef HAS_USB_CDC
#define HAS_USB_CDC     0
#endif

#define RING_SIZE       4096          // edges (power of two)
#define MAX_PULSES      PA_MAX_PULSES
#define BURST_GAP_MS    300           // frames closer than this belong to one press
#ifndef PA_BURST_FRAMES
#define PA_BURST_FRAMES 4             // decision = median of the first N frames (= config.py)
#endif
#define PA_MIN_BURST_FRAMES 3         // fewer consistent frames = stray noise, no decision (= config.py)

static uint32_t gap_us = 4000;
static uint32_t glitch_us = 80;
static uint32_t min_pulses = 16;
static bool stream_frames = true;
static bool edge_auth = PHYAUTH_MODEL_PRESENT;
static bool live_check = true;        // LIVE ON|OFF

// ----------------------------------------------------------------------------
// Serial I/O (UART0, plus native USB on the ESP32-S3)
// ----------------------------------------------------------------------------
static void emit_n(const char *b, size_t n) {
  Serial.write((const uint8_t *)b, n);
#if HAS_USB_CDC
  if (USBSerial) USBSerial.write((const uint8_t *)b, n);
#endif
}
static void emit(const char *b) { emit_n(b, strlen(b)); }
static void emitln(const char *b) { emit(b); emit_n("\n", 1); }
static int read_cmd_char() {
  if (Serial.available()) return Serial.read();
#if HAS_USB_CDC
  if (USBSerial.available()) return USBSerial.read();
#endif
  return -1;
}

// ----------------------------------------------------------------------------
// Indicator: on-board LED / RGB, works without any extra parts
// ----------------------------------------------------------------------------
static uint8_t verdict_state = 0;  // 0 idle, 1 authentic, 2 rejected

static void ind_set(uint8_t r, uint8_t g, uint8_t b) {
#if STATUS_RGB
  neopixelWrite(RGB_BUILTIN, r, g, b);
#else
  if (LED_STATUS >= 0) digitalWrite(LED_STATUS, (r | g | b) ? HIGH : LOW);
#endif
}

// ----------------------------------------------------------------------------
// ISR -> ring buffer
// ----------------------------------------------------------------------------
struct Edge {
  uint32_t cc;
  uint8_t level;
};
static Edge ring[RING_SIZE];
static volatile uint32_t ring_head = 0;  // written by ISR
static volatile uint32_t ring_tail = 0;  // written by loop
static volatile uint32_t ring_overflow = 0;
static volatile uint32_t edge_count = 0;

static inline uint32_t IRAM_ATTR ccount() {
  uint32_t c;
  asm volatile("rsr %0, ccount" : "=a"(c));
  return c;
}

static void IRAM_ATTR on_edge(void *) {
  uint32_t c = ccount();
  uint8_t lvl = (REG_READ(GPIO_IN_REG) >> RX_PIN) & 1;
  uint32_t h = ring_head;
  uint32_t next = (h + 1) & (RING_SIZE - 1);
  if (next == ring_tail) {
    ring_overflow++;
    return;
  }
  ring[h].cc = c;
  ring[h].level = lvl;
  ring_head = next;
  edge_count++;
}

// ----------------------------------------------------------------------------
// Frame segmentation state
// ----------------------------------------------------------------------------
static int32_t pulses[MAX_PULSES + 2];
static int npulses = 0;
static bool in_frame = false;
static bool armed = false;            // saw a gap; next HIGH starts a frame
static bool merge_next = false;       // previous pulse was a glitch
static int64_t prev_gap_ns = -1;
static uint64_t timeline_ns = 0;      // receiver-local time of last edge
static uint64_t frame_t_ns = 0;
static uint32_t last_cc = 0;
static uint8_t last_level = 0;
static bool have_last = false;
static int64_t last_edge_us = 0;
static bool gap_flushed = false;
static uint32_t frame_seq = 0, frames_out = 0, frames_rejected = 0, frames_overflow = 0;
static uint32_t cpu_mhz = 240;

static char out_buf[4200];

// ----------------------------------------------------------------------------
// Edge authentication (TinyML-style, no external libraries)
// ----------------------------------------------------------------------------
#if PHYAUTH_MODEL_PRESENT
struct Burst {
  uint64_t last_t_ns = 0;
  uint32_t last_ms = 0;           // wall clock of the last frame (timeout decisions)
  uint32_t seq = 0;
  uint64_t code = 0;
  int nbits = 0;
  int dev = -1;
  bool by_code = false;
  float clock_us = 0;
  int64_t infer_us = 0;
  float score[PA_BURST_FRAMES];   // distance / threshold of each frame
  float dist[PA_BURST_FRAMES];
  float clk[PA_BURST_FRAMES];     // clock period per frame (start-up drift)
  int frames = 0;
  bool decided = false;
};
static Burst burst;

static float median_of(float *v, int n) {
  for (int i = 1; i < n; i++) {           // insertion sort, n <= 8
    float x = v[i];
    int j = i - 1;
    while (j >= 0 && v[j] > x) { v[j + 1] = v[j]; j--; }
    v[j + 1] = x;
  }
  return n % 2 ? v[n / 2] : 0.5f * (v[n / 2 - 1] + v[n / 2]);
}
#endif

static uint32_t actuator_off_ms = 0;

static void actuate(bool ok) {
  verdict_state = ok ? 1 : 2;
  if (ok) ind_set(0, 40, 0);
  digitalWrite(ok ? LED_OK : LED_BAD, HIGH);
  digitalWrite(ok ? LED_BAD : LED_OK, LOW);
  if (ok) {
    digitalWrite(RELAY_PIN, HIGH);
    digitalWrite(BUZZER_PIN, HIGH);
    delay(60);
    digitalWrite(BUZZER_PIN, LOW);
  } else {
    for (int i = 0; i < 3; i++) {
      digitalWrite(BUZZER_PIN, HIGH);
      delay(70);
      digitalWrite(BUZZER_PIN, LOW);
      delay(50);
    }
  }
  actuator_off_ms = millis() + 1500;
}


#if PHYAUTH_MODEL_PRESENT
// ----------------------------------------------------------------------------
// Pattern lock: state machine in phyauth_lock.c, outputs here (non-blocking)
// ----------------------------------------------------------------------------
static pa_lock_t lock;
static Preferences prefs;
static uint32_t flash_until = 0;   // short green flash for an accepted press
static uint32_t alarm_until = 0;   // fast blink + buzzer
static uint8_t alarm_kind = 0;     // 1 wrong pattern, 2 foreign transmitter, 3 lockout

static int owner_index(const char *name) {
  for (int i = 0; i < PA_NDEV; i++) if (!strcmp(PA_DEV_ID[i], name)) return i;
  return -1;
}

static void lock_save() {
  prefs.begin("palock", false);
  prefs.putString("owner", lock.owner >= 0 ? PA_DEV_ID[lock.owner] : "");
  prefs.putUChar("len", (uint8_t)lock.len);
  if (lock.len > 0) prefs.putBytes("pat", lock.pattern, lock.len);
  prefs.putUInt("relock", lock.relock_ms);
  prefs.end();
}

static void lock_load() {
  prefs.begin("palock", true);
  String owner = prefs.getString("owner", "");
  uint8_t len = prefs.getUChar("len", 0);
  uint8_t pat[PA_LOCK_MAX] = {0};
  if (len >= PA_LOCK_MIN && len <= PA_LOCK_MAX) prefs.getBytes("pat", pat, len);
  lock.relock_ms = prefs.getUInt("relock", lock.relock_ms);
  prefs.end();
  int idx = owner_index(owner.c_str());   // model re-export may reorder devices
  if (idx >= 0) pa_lock_set(&lock, idx, pat, len);
}

static void lock_report(pa_lock_event_t ev, int key) {
  snprintf(out_buf, sizeof(out_buf),
           "{\"type\":\"lock\",\"event\":\"%s\",\"state\":\"%s\",\"n\":%d,\"len\":%d,\"fails\":%d,"
           "\"owner\":\"%s\",\"key\":%d,\"relock_s\":%u,\"gap_s\":%u,\"led\":%d}\n",
           pa_lock_event_name(ev), pa_lock_state_name(lock.state), lock.n, lock.len, lock.fails,
           lock.owner >= 0 ? PA_DEV_ID[lock.owner] : "", key, (unsigned)(lock.relock_ms / 1000),
           (unsigned)(lock.gap_ms / 1000), (int)((REG_READ(GPIO_OUT_REG) >> LED_OK) & 1));
  emit(out_buf);
}

static void lock_alarm(uint8_t kind, uint32_t now, uint32_t ms) {
  alarm_kind = kind;
  alarm_until = now + ms;
}

static void lock_feedback(pa_lock_event_t ev, uint32_t now) {
  switch (ev) {
    case PA_EV_PROGRESS:
    case PA_EV_LEARN_STEP: flash_until = now + 120; break;
    case PA_EV_LEARN_CONFIRM: flash_until = now + 700; break;
    case PA_EV_LEARNED: lock_save(); flash_until = now + 1500; break;
    case PA_EV_FAIL:
    case PA_EV_LEARN_MISMATCH: lock_alarm(1, now, 1200); break;
    case PA_EV_FOREIGN: flash_until = now + 120; break;   // counted like any press; alarm comes at the end
    case PA_EV_LOCKOUT: lock_alarm(3, now, 3000); break;
    default: break;
  }
}

static void lock_outputs(uint32_t now) {
  bool unlocked = lock.state == PA_LOCK_UNLOCKED;
  bool green = unlocked, buzz = false;
  if (lock.state == PA_LOCK_LEARN) green = (now / 500) & 1;            // slow blink: learning
  if (flash_until) {
    if ((int32_t)(now - flash_until) < 0) green = !unlocked;          // brief flash
    else flash_until = 0;
  }
  if (alarm_until) {
    if ((int32_t)(now - alarm_until) < 0) {
      green = (now / 90) & 1;                                         // fast blink
      uint32_t period = alarm_kind == 1 ? 300 : (alarm_kind == 2 ? 160 : 600);
      buzz = (now % period) < period / 2;
    } else {
      alarm_until = 0;
    }
  }
  digitalWrite(LED_OK, green ? HIGH : LOW);
  digitalWrite(BUZZER_PIN, buzz ? HIGH : LOW);
  digitalWrite(LED_BAD, (lock.state == PA_LOCK_LOCKED || lock.state == PA_LOCK_LOCKOUT) ? HIGH : LOW);
  digitalWrite(RELAY_PIN, unlocked ? HIGH : LOW);
}

static bool lock_active() { return lock.state != PA_LOCK_DISABLED; }

// One decided press -> lock. key = EV1527 key nibble (low 4 bits of the code).
// A rejected press decided on fewer than PA_BURST_FRAMES frames (a quick tap)
// is "unclear": it neither counts nor raises the alarm; the user presses again.
// Only AUTHENTIC presses ever advance the pattern, so this cannot help a clone.
static void lock_on_press(bool authentic, int dev, uint64_t code, int nbits, int frames) {
  uint32_t now = millis();
  int key = nbits == 24 ? (int)(code & 0xF) : -1;
  (void)frames;   // every decided press counts toward the attempt
  pa_lock_event_t ev = pa_lock_press(&lock, authentic ? 1 : 0, dev, (uint8_t)(key & 0xF), now);
  if (ev == PA_EV_NONE) return;
  lock_feedback(ev, now);
  lock_report(ev, key);
}

static int parse_keys(const char *s, uint8_t *out) {
  int n = 0;
  char tmp[64];
  strncpy(tmp, s, sizeof(tmp) - 1);
  tmp[sizeof(tmp) - 1] = 0;
  for (char *t = strtok(tmp, ","); t && n < PA_LOCK_MAX; t = strtok(nullptr, ",")) {
    if (!strcmp(t, "ON")) out[n++] = 8;
    else if (!strcmp(t, "OFF")) out[n++] = 4;
    else out[n++] = (uint8_t)(strtoul(t, nullptr, 16) & 0xF);
  }
  return n;
}

static bool lock_command(const char *c) {
  char a[24], b[64];
  unsigned v = 0;
  if (!strcmp(c, "LOCK STATUS")) {
    lock_report(PA_EV_NONE, -1);
  } else if (sscanf(c, "LOCK LEARN %23s", a) == 1) {
    int idx = owner_index(a);
    if (idx < 0) { emitln("{\"type\":\"err\",\"msg\":\"unknown device\"}"); return true; }
    pa_lock_learn(&lock, idx);
    lock_report(PA_EV_NONE, -1);
  } else if (sscanf(c, "LOCK SET %23s %63s", a, b) == 2) {
    uint8_t keys[PA_LOCK_MAX];
    int idx = owner_index(a), n = parse_keys(b, keys);
    if (idx < 0 || !pa_lock_set(&lock, idx, keys, n)) {
      emitln("{\"type\":\"err\",\"msg\":\"LOCK SET needs a known device and 4-12 keys\"}");
      return true;
    }
    lock_save();
    lock_report(PA_EV_LEARNED, -1);
  } else if (!strcmp(c, "LOCK CLEAR")) {
    pa_lock_clear(&lock);
    lock_save();
    lock_report(PA_EV_NONE, -1);
  } else if (!strcmp(c, "LOCK NOW")) {
    pa_lock_force_lock(&lock);
    lock_report(PA_EV_LOCK, -1);
  } else if (sscanf(c, "LOCK RELOCK %u", &v) == 1 && v <= 3600) {
    lock.relock_ms = v * 1000u;
    lock_save();
    lock_report(PA_EV_NONE, -1);
  } else {
    return false;
  }
  return true;
}
#endif

#if PHYAUTH_MODEL_PRESENT
// Same rule as the host engine: median of the first N normalised distances.
static void decide_burst() {
  burst.decided = true;
  float med_score = median_of(burst.score, burst.frames);
  float med_d = median_of(burst.dist, burst.frames);
  bool fp_ok = med_score <= 1.0f;
  // Liveness: a battery fob's clock drifts while it starts from cold; an
  // always-on crystal transmitter does not. Same rule as ml/liveness.py.
  float drift = 0.0f;
  int live = -1;                  // -1 n/a, 0 no drift, 1 ok
#ifdef PA_HAS_LIVENESS
  if (live_check && burst.frames >= PA_BURST_FRAMES && burst.clk[PA_BURST_FRAMES - 1] > 0) {
    drift = (burst.clk[0] - burst.clk[PA_BURST_FRAMES - 1]) / burst.clk[PA_BURST_FRAMES - 1] * 1e6f;
    if (PA_LIVE_ON[burst.dev]) live = fabsf(drift - PA_LIVE_MU[burst.dev]) <= PA_LIVE_TOL[burst.dev];
  }
#endif
  bool ok = fp_ok && live != 0;
  const char *verdict;
  if (burst.by_code) verdict = ok ? "AUTHENTIC" : "SPOOF_SUSPECTED";
  else verdict = ok ? "AUTHENTIC" : "UNKNOWN_DEVICE";
  snprintf(out_buf, sizeof(out_buf),
           "{\"type\":\"auth\",\"seq\":%u,\"code\":\"%llx/%d\",\"dev\":\"%s\",\"claimed\":%s,"
           "\"dist\":%.3f,\"thr\":%.3f,\"score\":%.3f,\"frames\":%d,\"verdict\":\"%s\",\"T_us\":%.3f,"
           "\"infer_us\":%lld,\"fp_ok\":%d,\"drift_ppm\":%.0f,\"live\":%d}\n",
           burst.seq, (unsigned long long)burst.code, burst.nbits, PA_DEV_ID[burst.dev],
           burst.by_code ? "true" : "false", med_d, PA_THRESH[burst.dev], med_score, burst.frames, verdict,
           burst.clock_us, (long long)burst.infer_us, fp_ok ? 1 : 0, drift, live);
  emit(out_buf);
  if (lock_active()) {          // lock mode: per-press feedback comes from the lock
    verdict_state = ok ? 1 : 2;
    if (ok) ind_set(0, 40, 0);
    actuator_off_ms = millis() + 800;
    lock_on_press(ok, burst.dev, burst.code, burst.nbits, burst.frames);
  } else {
    actuate(ok);
  }
}

static void edge_authenticate(const int32_t *src, int n, int64_t gap_ns, uint64_t t_ns, uint32_t seq) {
  static int32_t work[MAX_PULSES + 2];
  memcpy(work, src, n * sizeof(int32_t));
  int64_t t0 = esp_timer_get_time();
  pa_result_t r;
  pa_analyze(work, n, gap_ns, (int32_t)(glitch_us * 1000), &r);
  if (r.status != PA_OK) return;

  float emb[PA_EMB];
  pa_embed(r.features, PA_NUM_FEATURES, PA_FEAT_MEAN, PA_FEAT_STD,
           PA_W1, PA_B1, PA_H1, PA_W2, PA_B2, PA_EMB, emb);

  // Claim = enrolled device whose code matches; otherwise the nearest profile.
  int claimed = -1;
  for (int i = 0; i < PA_NDEV; i++) {
    if (PA_DEV_NBITS[i] == r.n_bits && PA_DEV_CODE[i] == r.code) { claimed = i; break; }
  }
  int dev = claimed;
  float dist = 1e9f, score = 1e9f;
  if (claimed >= 0) {
    dist = pa_mahalanobis(emb, &PA_CENTROID[claimed * PA_EMB], &PA_COVINV[claimed * PA_EMB * PA_EMB], PA_EMB);
    score = dist / PA_THRESH[claimed];
  } else {
    for (int i = 0; i < PA_NDEV; i++) {
      float d = pa_mahalanobis(emb, &PA_CENTROID[i * PA_EMB], &PA_COVINV[i * PA_EMB * PA_EMB], PA_EMB);
      if (d / PA_THRESH[i] < score) { score = d / PA_THRESH[i]; dist = d; dev = i; }
    }
  }

  bool new_burst = (t_ns - burst.last_t_ns) > (uint64_t)BURST_GAP_MS * 1000000ULL ||
                   burst.code != r.code || burst.nbits != r.n_bits;
  if (new_burst) {
    if (!burst.decided && burst.frames >= PA_MIN_BURST_FRAMES) decide_burst();
    burst = Burst();
    burst.code = r.code;
    burst.nbits = r.n_bits;
    burst.dev = dev;
    burst.by_code = claimed >= 0;
  }
  burst.last_t_ns = t_ns;
  burst.last_ms = millis();
  if (burst.decided) return;
  burst.seq = seq;
  burst.clock_us = r.clock_t_ns / 1000.0;
  burst.infer_us = esp_timer_get_time() - t0;
  burst.score[burst.frames] = score;
  burst.dist[burst.frames] = dist;
  burst.clk[burst.frames] = burst.clock_us;
  burst.frames++;
  if (burst.frames >= PA_BURST_FRAMES) decide_burst();
}

// A press that produced fewer than N good frames is decided after it ends.
static void edge_timeout() {
  if (!burst.decided && burst.frames >= PA_MIN_BURST_FRAMES && millis() - burst.last_ms > 2 * BURST_GAP_MS) decide_burst();
}
#endif

// ----------------------------------------------------------------------------
// Output
// ----------------------------------------------------------------------------
static void print_hello() {
  snprintf(out_buf, sizeof(out_buf),
           "{\"type\":\"hello\",\"fw\":\"phyauth-rx\",\"ver\":\"%s\",\"clk_hz\":%u,\"gap_us\":%u,"
           "\"glitch_us\":%u,\"min_pulses\":%u,\"edge_model\":%d,\"model\":\"%s\",\"pin\":%d,"
           "\"board\":\"%s\"}\n",
           FW_VERSION, cpu_mhz * 1000000u, gap_us, glitch_us, min_pulses, PHYAUTH_MODEL_PRESENT,
           PA_MODEL_VERSION, (int)RX_PIN, BOARD_NAME);
  emit(out_buf);
}

static void emit_frame() {
  merge_next = false;
  if ((uint32_t)npulses < min_pulses) {
    frames_rejected++;
    npulses = 0;
    return;
  }
  frame_seq++;
  if (!verdict_state) ind_set(0, 0, 12);  // activity flicker
  if (stream_frames) {
    int len = snprintf(out_buf, sizeof(out_buf),
                       "{\"type\":\"frame\",\"seq\":%u,\"t_us\":%llu,\"g\":%lld,\"n\":%d,\"d\":[",
                       frame_seq, (unsigned long long)(frame_t_ns / 1000ULL), (long long)prev_gap_ns, npulses);
    for (int i = 0; i < npulses && len < (int)sizeof(out_buf) - 16; i++) {
      len += snprintf(out_buf + len, sizeof(out_buf) - len, i ? ",%d" : "%d", (int)pulses[i]);
    }
    len += snprintf(out_buf + len, sizeof(out_buf) - len, "]}\n");
    emit_n(out_buf, len);
  }
#if PHYAUTH_MODEL_PRESENT
  if (edge_auth) edge_authenticate(pulses, npulses, prev_gap_ns, frame_t_ns, frame_seq);
#endif
  frames_out++;
  npulses = 0;
  if (!verdict_state) ind_set(0, 0, 0);
}

// One completed pulse of `level` lasting `w_ns`
static void on_pulse(uint8_t level, uint32_t w_ns) {
  const uint32_t gap_ns = gap_us * 1000u;
  if (level == 0 && w_ns >= gap_ns) {
    if (in_frame && !gap_flushed) emit_frame();
    in_frame = false;
    armed = true;
    gap_flushed = false;
    prev_gap_ns = w_ns;
    return;
  }
  if (!in_frame) {
    if (level == 1 && armed) {
      in_frame = true;
      npulses = 0;
      merge_next = false;
      frame_t_ns = timeline_ns - w_ns;
    } else {
      return;
    }
  }
  if (merge_next) {
    pulses[npulses - 1] += (int32_t)w_ns;
    merge_next = false;
    return;
  }
  if (w_ns < glitch_us * 1000u && npulses > 0) {
    pulses[npulses - 1] += (int32_t)w_ns;
    merge_next = true;
    return;
  }
  if (npulses >= MAX_PULSES) {   // never-ending noise: drop and wait for a gap
    frames_overflow++;
    in_frame = false;
    armed = false;
    npulses = 0;
    return;
  }
  pulses[npulses++] = (int32_t)w_ns;
}

static void process_edges() {
  while (ring_tail != ring_head) {
    Edge e = ring[ring_tail];
    ring_tail = (ring_tail + 1) & (RING_SIZE - 1);
    int64_t now_us = esp_timer_get_time();
    if (have_last) {
      uint32_t cycles = e.cc - last_cc;  // wraps safely below 17.9 s
      uint64_t w_ns = (uint64_t)cycles * 1000ULL / cpu_mhz;
      if (now_us - last_edge_us > 15000000LL) {  // counter may have wrapped
        w_ns = (uint64_t)(now_us - last_edge_us) * 1000ULL;
      }
      timeline_ns += w_ns;
      bool long_silence = w_ns >= 1000000000ULL;
      if (w_ns > 0x7FFFFFFFULL) w_ns = 0x7FFFFFFFULL;
      on_pulse(last_level, (uint32_t)w_ns);
      if (last_level == 0 && long_silence) prev_gap_ns = -1;  // not a sync gap
    }
    last_cc = e.cc;
    last_level = e.level;
    last_edge_us = now_us;
    have_last = true;
  }
  // A frame ends with a HIGH followed by silence: flush once the gap elapses.
  if (in_frame && have_last && last_level == 0 && !gap_flushed) {
    uint32_t cycles = ccount() - last_cc;
    if ((uint64_t)cycles * 1000ULL / cpu_mhz >= (uint64_t)gap_us * 1000ULL) {
      emit_frame();
      gap_flushed = true;
      in_frame = false;
      armed = true;
    }
  }
}

// ----------------------------------------------------------------------------
// Commands
// ----------------------------------------------------------------------------
static char cmd_buf[64];
static int cmd_len = 0;

static void handle_command(char *c) {
  for (char *p = c; *p; p++) *p = toupper(*p);
  unsigned v = 0;
  if (!strcmp(c, "PING")) {
    emitln("{\"type\":\"ack\",\"cmd\":\"PING\"}");
  } else if (!strcmp(c, "INFO")) {
    print_hello();
  } else if (sscanf(c, "SET GAP %u", &v) == 1 && v >= 500 && v <= 30000) {
    gap_us = v;
    print_hello();
  } else if (sscanf(c, "SET GLITCH %u", &v) == 1 && v <= 400) {
    glitch_us = v;
    print_hello();
  } else if (sscanf(c, "SET MINP %u", &v) == 1 && v >= 4 && v <= MAX_PULSES) {
    min_pulses = v;
    print_hello();
  } else if (!strcmp(c, "MODE STREAM")) {
    stream_frames = true; edge_auth = false;
    emitln("{\"type\":\"ack\",\"cmd\":\"MODE STREAM\"}");
  } else if (!strcmp(c, "MODE EDGE")) {
    stream_frames = false; edge_auth = PHYAUTH_MODEL_PRESENT;
    emitln(PHYAUTH_MODEL_PRESENT ? "{\"type\":\"ack\",\"cmd\":\"MODE EDGE\"}"
                                         : "{\"type\":\"err\",\"msg\":\"no edge model flashed\"}");
  } else if (!strcmp(c, "MODE BOTH")) {
    stream_frames = true; edge_auth = PHYAUTH_MODEL_PRESENT;
    emitln("{\"type\":\"ack\",\"cmd\":\"MODE BOTH\"}");
  } else if (!strcmp(c, "LIVE ON") || !strcmp(c, "LIVE OFF")) {
    live_check = c[6] == 'N';
    emitln(live_check ? "{\"type\":\"ack\",\"cmd\":\"LIVE ON\"}" : "{\"type\":\"ack\",\"cmd\":\"LIVE OFF\"}");
#if PHYAUTH_MODEL_PRESENT
  } else if (!strncmp(c, "LOCK", 4) && lock_command(c)) {
    // handled
#endif
  } else if (!strcmp(c, "PINTEST")) {   // GPIO25 3 s, buzzer 3 beeps, GPIO26 3 s
    digitalWrite(LED_OK, HIGH); digitalWrite(LED_BAD, LOW);
    emitln("{\"type\":\"ack\",\"cmd\":\"PINTEST\",\"on\":\"LED_OK\"}");
    delay(3000);
    digitalWrite(LED_OK, LOW);
    delay(1000);
    emitln("{\"type\":\"ack\",\"cmd\":\"PINTEST\",\"on\":\"BUZZER\"}");
    for (int i = 0; i < 3; i++) {
      digitalWrite(BUZZER_PIN, HIGH); delay(300);
      digitalWrite(BUZZER_PIN, LOW); delay(300);
    }
    delay(1000);
    digitalWrite(LED_BAD, HIGH);
    emitln("{\"type\":\"ack\",\"cmd\":\"PINTEST\",\"on\":\"LED_BAD\"}");
    delay(3000);
    digitalWrite(LED_BAD, LOW);
  } else if (!strcmp(c, "ALLON") || !strcmp(c, "SCAN")) {
    // Wiring finder: drive every free output-capable GPIO (not GPIO14 = radio input).
    static const int pins[] = {4, 5, 13, 16, 17, 18, 19, 21, 22, 23, 25, 26, 27, 32, 33};
    const int np = sizeof(pins) / sizeof(pins[0]);
    bool all = !strcmp(c, "ALLON");
    for (int i = 0; i < np; i++) pinMode(pins[i], OUTPUT);
    if (all) {
      for (int i = 0; i < np; i++) digitalWrite(pins[i], HIGH);
      emitln("{\"type\":\"ack\",\"cmd\":\"ALLON\"}");
      delay(5000);
      for (int i = 0; i < np; i++) digitalWrite(pins[i], LOW);
    } else {
      for (int i = 0; i < np; i++) {
        digitalWrite(pins[i], HIGH);
        snprintf(out_buf, sizeof(out_buf), "{\"type\":\"ack\",\"cmd\":\"SCAN\",\"step\":%d,\"pin\":%d}", i + 1, pins[i]);
        emitln(out_buf);
        delay(2000);
        digitalWrite(pins[i], LOW);
        delay(700);
      }
    }
  } else if (!strcmp(c, "TEST")) {
    actuate(true); delay(400); actuate(false);
    emitln("{\"type\":\"ack\",\"cmd\":\"TEST\"}");
  } else {
    emitln("{\"type\":\"err\",\"msg\":\"unknown command\"}");
  }
}

static void poll_commands() {
  int c;
  while ((c = read_cmd_char()) >= 0) {
    char ch = (char)c;
    if (ch == '\n' || ch == '\r') {
      if (cmd_len) {
        cmd_buf[cmd_len] = 0;
        handle_command(cmd_buf);
        cmd_len = 0;
      }
    } else if (cmd_len < (int)sizeof(cmd_buf) - 1) {
      cmd_buf[cmd_len++] = ch;
    }
  }
}

// ----------------------------------------------------------------------------
void setup() {
  Serial.setTxBufferSize(8192);
  Serial.begin(SERIAL_BAUD);
#if HAS_USB_CDC
  USBSerial.begin();
#endif
#if !STATUS_RGB
  if (LED_STATUS >= 0) pinMode(LED_STATUS, OUTPUT);
#endif
  pinMode(LED_OK, OUTPUT);
  pinMode(LED_BAD, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW);
  cpu_mhz = getCpuFrequencyMhz();
  delay(300);

  gpio_config_t io = {};
  io.pin_bit_mask = 1ULL << RX_PIN;
  io.mode = GPIO_MODE_INPUT;
  io.pull_up_en = GPIO_PULLUP_DISABLE;
  io.pull_down_en = GPIO_PULLDOWN_ENABLE;  // defined LOW if the module is unplugged
  io.intr_type = GPIO_INTR_ANYEDGE;
  gpio_config(&io);
  gpio_install_isr_service(ESP_INTR_FLAG_IRAM);
  gpio_isr_handler_add(RX_PIN, on_edge, nullptr);

  ind_set(0, 0, 0);
#if PHYAUTH_MODEL_PRESENT
  pa_lock_init(&lock, 30000, 15000, 30000);  // clear unfinished attempt after 30 s idle (no failure), relock 15 s, lockout 30 s
  lock_load();
#endif
  print_hello();
#if PHYAUTH_MODEL_PRESENT
  lock_report(PA_EV_NONE, -1);
#endif
}

void loop() {
  static uint32_t last_stats = 0, last_edges = 0;
  process_edges();
  poll_commands();

#if PHYAUTH_MODEL_PRESENT
  if (edge_auth) edge_timeout();
#endif
  uint32_t now = millis();
  if (actuator_off_ms && (int32_t)(now - actuator_off_ms) >= 0) {
    digitalWrite(LED_OK, LOW);
    digitalWrite(LED_BAD, LOW);
    digitalWrite(RELAY_PIN, LOW);
    actuator_off_ms = 0;
    verdict_state = 0;
    ind_set(0, 0, 0);
  } else if (verdict_state == 2) {
    static bool blink_on = false;
    bool on = (now / 120) & 1;
    if (on != blink_on) { blink_on = on; ind_set(on ? 50 : 0, 0, 0); }
  }
#if PHYAUTH_MODEL_PRESENT
  if (lock_active()) {
    pa_lock_event_t lev = pa_lock_tick(&lock, now);
    if (lev != PA_EV_NONE) {
      lock_feedback(lev, now);
      lock_report(lev, -1);
    }
    lock_outputs(now);
  }
#endif
  if (now - last_stats >= 2000) {
    uint32_t edges = edge_count;
    uint32_t eps = (edges - last_edges) * 1000u / (now - last_stats);
    last_edges = edges;
    last_stats = now;
    snprintf(out_buf, sizeof(out_buf),
             "{\"type\":\"stats\",\"up_ms\":%u,\"edges\":%u,\"frames\":%u,\"rejected\":%u,"
             "\"overflow\":%u,\"ring_overflow\":%u,\"noise_eps\":%u}\n",
             now, edges, frames_out, frames_rejected, frames_overflow, (unsigned)ring_overflow, eps);
    emit(out_buf);
  }
}
