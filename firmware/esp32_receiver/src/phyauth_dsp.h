/*
 * phyauth_dsp.h — on-chip pulse DSP + edge fingerprint model.
 *
 * This is a line-by-line mirror of dsp/pulse_dsp.py. It is compiled both into
 * the ESP32 receiver firmware and (by tests/test_c_parity.py) into a host
 * shared library, so Python and the ESP32 provably compute the same features.
 */
#ifndef PHYAUTH_DSP_H
#define PHYAUTH_DSP_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PA_GLITCH_NS_DEFAULT   80000
#define PA_MIN_PAIRS           12
#define PA_MAX_DATA_UNITS      8
#define PA_SYNC_UNITS          31     /* EV1527 / PT2262 sync LOW = 31 T */
#define PA_MAX_PAIR_RESID_RMS  0.08
#define PA_MAX_PULSE_RESID     0.45
#define PA_SYNC_GAP_MAX_NS     60000000LL
#define PA_NUM_FEATURES        11
#define PA_MAX_PULSES          400

typedef enum {
  PA_OK = 0,
  PA_TOO_FEW_PULSES,
  PA_CLOCK_FIT_FAILED,
  PA_TOO_FEW_PAIRS,
  PA_TIMING_INCONSISTENT,
  PA_OFF_GRID_PULSE
} pa_status_t;

typedef struct {
  pa_status_t status;
  double clock_t_ns;
  int n_pairs;
  int n_bits;
  uint64_t code;            /* first n_bits bits, MSB first */
  double pair_resid_rms;
  double features[PA_NUM_FEATURES];
} pa_result_t;

/* Merge sub-threshold glitches in place. Returns new length. */
int pa_merge_glitches(int32_t *pulses, int n, int32_t glitch_ns);

/* Least-squares clock period estimate (ns), NAN on failure. */
double pa_two_symbol_clock(const int32_t *p, int n, int64_t gap_ns);
double pa_estimate_clock(const int32_t *pulses, int n, int64_t gap_ns);

/* Full analysis. `pulses` is modified in place (glitch merge).
 * gap_ns < 0 means "unknown". */
void pa_analyze(int32_t *pulses, int n, int64_t gap_ns, int32_t glitch_ns, pa_result_t *out);

/* Edge model: standardise -> Linear(nf,h1) -> ReLU -> Linear(h1,emb) -> L2.
 * Weights are row-major [out][in]. NaN features are imputed to the mean. */
void pa_embed(const double *features, int nf,
              const float *mean, const float *std,
              const float *w1, const float *b1, int h1,
              const float *w2, const float *b2, int emb,
              float *out_emb);

/* Mahalanobis distance sqrt((e-c)^T S^-1 (e-c)). */
float pa_mahalanobis(const float *emb, const float *centroid, const float *cov_inv, int dim);

#ifdef __cplusplus
}
#endif
#endif
