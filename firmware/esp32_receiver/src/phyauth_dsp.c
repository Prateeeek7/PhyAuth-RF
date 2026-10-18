/*
 * phyauth_dsp.c — see phyauth_dsp.h. Mirror of dsp/pulse_dsp.py.
 */
#include "phyauth_dsp.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

static int cmp_double(const void *a, const void *b) {
  double x = *(const double *)a, y = *(const double *)b;
  return (x > y) - (x < y);
}

static double percentile_sorted(const double *s, int n, double q) {
  if (n <= 0) return NAN;
  double pos = q * (double)(n - 1);
  int lo = (int)floor(pos);
  int hi = lo + 1 < n ? lo + 1 : n - 1;
  double frac = pos - (double)lo;
  return s[lo] + (s[hi] - s[lo]) * frac;
}

static int round_half_up(double x) { return (int)floor(x + 0.5); }

static double class_median(const double *v, int n) {
  static double tmp[PA_MAX_PULSES / 2];
  if (n <= 0) return 0.0;
  memcpy(tmp, v, n * sizeof(double));
  qsort(tmp, n, sizeof(double), cmp_double);
  return percentile_sorted(tmp, n, 0.5);
}

static double mean_of(const double *v, int n) {
  if (n <= 0) return NAN;
  double s = 0.0;
  for (int i = 0; i < n; i++) s += v[i];
  return s / (double)n;
}

static double std_of(const double *v, int n) {
  if (n < 2) return NAN;
  double m = mean_of(v, n), s = 0.0;
  for (int i = 0; i < n; i++) s += (v[i] - m) * (v[i] - m);
  return sqrt(s / (double)n);
}

int pa_merge_glitches(int32_t *p, int n, int32_t glitch_ns) {
  int out = 0, i = 0;
  while (i < n) {
    int32_t w = p[i];
    if (w < glitch_ns) {
      if (out > 0 && i + 1 < n) {
        p[out - 1] += w + p[i + 1];
        i += 2;
        continue;
      }
      if (out == 0) { i += 2; continue; }
      out--;          /* trailing glitch: drop it and the pulse before */
      i += 1;
      continue;
    }
    p[out++] = w;
    i += 1;
  }
  return out;
}

/* Distortion-invariant T for one-short-one-long encoders; see two_symbol_clock()
 * in dsp/pulse_dsp.py:  n = 2P / (P - dH),  T = P / n. */
double pa_two_symbol_clock(const int32_t *p, int n, int64_t gap_ns) {
  static double per[PA_MAX_PULSES / 2];
  int np = n / 2;
  if (np < PA_MIN_PAIRS) return NAN;
  for (int k = 0; k < np; k++) per[k] = (double)p[2 * k] + (double)p[2 * k + 1];
  qsort(per, np, sizeof(double), cmp_double);
  double p_med = percentile_sorted(per, np, 0.5);
  if (!(p_med > 0)) return NAN;
  double psum = 0.0, ssum = 0.0, lsum = 0.0;
  int pc = 0, sc = 0, lc = 0;
  for (int k = 0; k < np; k++) {
    double h = (double)p[2 * k];
    double pp = h + (double)p[2 * k + 1];
    if (fabs(pp - p_med) > 0.2 * p_med) continue;
    psum += pp; pc++;
    if (h < 0.5 * p_med) { ssum += h; sc++; } else { lsum += h; lc++; }
  }
  if (pc < PA_MIN_PAIRS) return NAN;
  double p_mean = psum / pc;
  if (gap_ns > 0) {           /* sync LOW = 31 T decides n when unique */
    int fit = 0, fits = 0;
    for (int k = 3; k <= PA_MAX_DATA_UNITS; k++) {
      if (fabs((double)gap_ns * k / p_mean - PA_SYNC_UNITS) <= 0.08 * PA_SYNC_UNITS) { fit = k; fits++; }
    }
    if (fits == 1) return p_mean / fit;
  }
  if (sc < 2 || lc < 2) return NAN;
  double dh = lsum / lc - ssum / sc;
  if (!(dh > 0.0 && dh < p_mean)) return NAN;
  double n_est = 2.0 * p_mean / (p_mean - dh);
  int nn = round_half_up(n_est);
  if (nn < 3 || nn > PA_MAX_DATA_UNITS || fabs(n_est - nn) > 0.45) return NAN;
  return p_mean / nn;
}

double pa_estimate_clock(const int32_t *p, int n, int64_t gap_ns) {
  static double s[PA_MAX_PULSES];
  if (n < 2 * PA_MIN_PAIRS || n > PA_MAX_PULSES) return NAN;
  double t = pa_two_symbol_clock(p, n, gap_ns);
  if (!(t > 0)) {
    for (int i = 0; i < n; i++) s[i] = (double)p[i];
    qsort(s, n, sizeof(double), cmp_double);
    double q25 = percentile_sorted(s, n, 0.25);
    double sum = 0.0;
    int cnt = 0;
    for (int i = 0; i < n; i++) {
      if (s[i] >= 0.5 * q25 && s[i] <= 1.5 * q25) { sum += s[i]; cnt++; }
    }
    t = cnt ? sum / cnt : q25;
  }
  if (!(t > 0)) return NAN;
  for (int it = 0; it < 2; it++) {
    double num = 0.0;
    long den = 0;
    for (int k = 0; k < n / 2; k++) {
      double h = p[2 * k], l = p[2 * k + 1];
      int nh = round_half_up(h / t); if (nh < 1) nh = 1;
      int nl = round_half_up(l / t); if (nl < 1) nl = 1;
      if (nh > PA_MAX_DATA_UNITS || nl > PA_MAX_DATA_UNITS) continue;
      num += h + l;
      den += nh + nl;
    }
    if (den == 0) return NAN;
    t = num / (double)den;
  }
  return t;
}

void pa_analyze(int32_t *pulses, int n, int64_t gap_ns, int32_t glitch_ns, pa_result_t *out) {
  static int units[PA_MAX_PULSES];
  static double resid[PA_MAX_PULSES];
  static double pair_err[PA_MAX_PULSES / 2], high_res[PA_MAX_PULSES / 2];
  static double sh[PA_MAX_PULSES / 2], lh[PA_MAX_PULSES / 2];
  static double sl[PA_MAX_PULSES / 2], ll[PA_MAX_PULSES / 2];

  memset(out, 0, sizeof(*out));
  for (int i = 0; i < PA_NUM_FEATURES; i++) out->features[i] = NAN;
  out->clock_t_ns = NAN;
  out->pair_resid_rms = NAN;

  if (n > PA_MAX_PULSES) n = PA_MAX_PULSES;
  n = pa_merge_glitches(pulses, n, glitch_ns);
  if (n < 2 * PA_MIN_PAIRS) { out->status = PA_TOO_FEW_PULSES; return; }

  double t = pa_estimate_clock(pulses, n, gap_ns);
  if (!(t > 0) || isnan(t)) { out->status = PA_CLOCK_FIT_FAILED; return; }
  out->clock_t_ns = t;

  for (int i = 0; i < n; i++) {
    int u = round_half_up(pulses[i] / t);
    units[i] = u < 1 ? 1 : u;
  }

  /* Decode per pair (see analyze_frame): the pair period fixes n, the bit is
   * "HIGH is the long half"; robust to slicer distortion beyond T/2. */
  int m = 0;
  uint64_t code = 0;
  for (int k = 0; k < n / 2; k++) {
    if (units[2 * k] > PA_MAX_DATA_UNITS || units[2 * k + 1] > PA_MAX_DATA_UNITS) break;
    double h = pulses[2 * k], l = pulses[2 * k + 1];
    int np_ = round_half_up((h + l) / t);
    if (np_ < 2) np_ = 2;
    int nh = (np_ < 3 || 2.0 * h < h + l) ? 1 : np_ - 1;
    units[2 * k] = nh;
    units[2 * k + 1] = np_ - nh;
    if (m < 64) code = (code << 1) | (uint64_t)(nh > np_ - nh ? 1 : 0);
    m++;
  }
  for (int i = 0; i < n; i++) resid[i] = (pulses[i] - units[i] * t) / t;
  for (int k = 0; k < m; k++) {
    double h = pulses[2 * k], l = pulses[2 * k + 1];
    pair_err[k] = (h + l) / ((units[2 * k] + units[2 * k + 1]) * t) - 1.0;
    high_res[k] = resid[2 * k];
  }
  out->n_pairs = m;
  out->n_bits = m < 64 ? m : 64;
  out->code = code;
  if (m < PA_MIN_PAIRS) { out->status = PA_TOO_FEW_PAIRS; return; }

  double ss = 0.0;
  for (int i = 0; i < m; i++) ss += pair_err[i] * pair_err[i];
  double rms = sqrt(ss / m);
  out->pair_resid_rms = rms;
  if (rms > PA_MAX_PAIR_RESID_RMS) { out->status = PA_TIMING_INCONSISTENT; return; }
  int data_len = 2 * m;
  int nsh = 0, nlh = 0, nsl = 0, nll = 0;
  for (int k = 0; k < m; k++) {
    if (units[2 * k] == 1) sh[nsh++] = resid[2 * k]; else lh[nlh++] = resid[2 * k];
    if (units[2 * k + 1] == 1) sl[nsl++] = resid[2 * k + 1]; else ll[nll++] = resid[2 * k + 1];
  }
  /* Each pulse vs the median distortion of its class: a common slicer offset
   * is a feature, a lone outlier is a dropout or glitch. */
  double c_sh = class_median(sh, nsh), c_lh = class_median(lh, nlh);
  double c_sl = class_median(sl, nsl), c_ll = class_median(ll, nll);
  if (fabs(c_sh) >= 1.0 || fabs(c_lh) >= 1.0 || fabs(c_sl) >= 1.0 || fabs(c_ll) >= 1.0) {
    out->status = PA_OFF_GRID_PULSE; return;
  }
  for (int i = 0; i < data_len; i++) {
    int is_high = (i % 2) == 0, is_short = units[i] == 1;
    double c = is_high ? (is_short ? c_sh : c_lh) : (is_short ? c_sl : c_ll);
    if (fabs(resid[i] - c) > PA_MAX_PULSE_RESID) { out->status = PA_OFF_GRID_PULSE; return; }
  }

  double xm = (m - 1) / 2.0, ym = mean_of(pair_err, m), sxx = 0.0, sxy = 0.0;
  for (int i = 0; i < m; i++) {
    sxx += (i - xm) * (i - xm);
    sxy += (i - xm) * (pair_err[i] - ym);
  }
  double slope = sxx > 0 ? sxy / sxx : 0.0;

  double sync_ratio = NAN;
  if (gap_ns > 0 && gap_ns < PA_SYNC_GAP_MAX_NS) sync_ratio = (double)gap_ns / t;
  double tail = NAN;
  if (n == data_len + 1) tail = resid[data_len];

  out->features[0] = t / 1000.0;
  out->features[1] = std_of(pair_err, m) * 1e6;
  out->features[2] = nsh ? mean_of(sh, nsh) : NAN;
  out->features[3] = nlh ? mean_of(lh, nlh) : NAN;
  out->features[4] = std_of(high_res, m);
  out->features[5] = resid[0];
  out->features[6] = slope * 1e6;
  out->features[7] = sync_ratio;
  out->features[8] = tail;
  out->features[9] = nsl ? mean_of(sl, nsl) : NAN;
  out->features[10] = nll ? mean_of(ll, nll) : NAN;
  out->status = PA_OK;
}

void pa_embed(const double *features, int nf,
              const float *mean, const float *std,
              const float *w1, const float *b1, int h1,
              const float *w2, const float *b2, int emb,
              float *out_emb) {
  float x[32];
  float h[128];
  for (int i = 0; i < nf; i++) {
    double v = features[i];
    x[i] = isnan(v) ? 0.0f : (float)((v - mean[i]) / std[i]);
  }
  for (int j = 0; j < h1; j++) {
    float a = b1[j];
    for (int i = 0; i < nf; i++) a += w1[j * nf + i] * x[i];
    h[j] = a > 0.0f ? a : 0.0f;
  }
  float norm = 0.0f;
  for (int j = 0; j < emb; j++) {
    float a = b2[j];
    for (int i = 0; i < h1; i++) a += w2[j * h1 + i] * h[i];
    out_emb[j] = a;
    norm += a * a;
  }
  norm = sqrtf(norm);
  if (norm < 1e-12f) norm = 1e-12f;
  for (int j = 0; j < emb; j++) out_emb[j] /= norm;
}

float pa_mahalanobis(const float *e, const float *c, const float *ci, int dim) {
  float d[64];
  for (int i = 0; i < dim; i++) d[i] = e[i] - c[i];
  float acc = 0.0f;
  for (int i = 0; i < dim; i++) {
    float row = 0.0f;
    for (int j = 0; j < dim; j++) row += ci[i * dim + j] * d[j];
    acc += d[i] * row;
  }
  return sqrtf(acc > 0.0f ? acc : 0.0f);
}
