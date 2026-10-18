export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://localhost:8000';
export const WS_URL = API_BASE.replace(/^http/, 'ws') + '/api/ws';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail = (data && typeof data === 'object' && 'detail' in data) ? (data as { detail: unknown }).detail : text;
    throw new ApiError(res.status, typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return data as T;
}

export const api = {
  get: <T,>(p: string) => request<T>('GET', p),
  post: <T,>(p: string, b?: unknown) => request<T>('POST', p, b ?? {}),
  patch: <T,>(p: string, b: unknown) => request<T>('PATCH', p, b),
  del: <T,>(p: string) => request<T>('DELETE', p),
};

// ---------------------------------------------------------------------------
// Types mirrored from the backend
// ---------------------------------------------------------------------------
export interface Device {
  id: number;
  device_id: string;
  name: string;
  model_info: string;
  protocol: string;
  is_authorized: boolean;
  code: string | null;
  kind: string;
  notes: string;
  registered_at: string;
}

export interface FrameEvent {
  type: 'frame';
  seq: number | null;
  t: number;
  rx_time: number;
  n: number;
  pulses_us: number[];
  ok: boolean;
  quality: string;
  code: string;
  clock_t_us: number | null;
  pair_resid_rms: number | null;
  units: number[];
  residuals: number[];
  features: Record<string, number | null>;
  gap_us: number | null;
  claimed?: string | null;
  claim_source?: string;
  distance?: number;
  score?: number;
  frame_accept?: boolean;
  predicted?: string;
  confidence?: number;
  probs?: Record<string, number>;
  model?: string;
  simulated?: boolean;
  sim_source?: string | null;
}

export interface Decision {
  type: 'decision';
  time: number;
  verdict: 'AUTHENTIC' | 'SPOOF_SUSPECTED' | 'UNKNOWN_DEVICE';
  code: string;
  claimed: string | null;
  claim_source: string;
  score: number;
  distance: number;
  frames: number;
  predicted: string | null;
  clock_t_us: number | null;
  model: string;
  model_version: string | null;
  source: 'host' | 'edge';
  simulated?: boolean;
  sim_source?: string | null;
  infer_us?: number;
  fingerprint_ok?: boolean | null;
  drift_ppm?: number | null;
  liveness?: string | null;
}

export interface RecordingStatus {
  device_id: string;
  session_id: string;
  name: string;
  state: string;
  frames_total: number;
  frames_good: number;
  target_good: number;
  elapsed_s: number;
  timeout_s: number;
  file: string;
  dominant_code: string | null;
  clock_t_us: number | null;
  reject_reasons: Record<string, number>;
  source: string;
  expected_code: string | null;
  foreign_frames: number;
}

export interface TrainingState {
  status: 'IDLE' | 'RUNNING' | 'COMPLETED' | 'FAILED';
  progress: { stage?: string; epoch?: number; total_epochs?: number; train_loss?: number; val_loss?: number; val_accuracy?: number };
  error: string;
  report_ready: boolean;
}

export interface ReceiverStatus {
  mode: 'disconnected' | 'hardware' | 'simulation';
  port: string | null;
  baud: number;
  connected: boolean;
  hello: Record<string, unknown> | null;
  stats: Record<string, number> | null;
  lines_rx: number;
  frames_rx: number;
  last_error: string;
  last_frame_age_s: number | null;
}

export interface ModelInfo {
  ready: boolean;
  version: string | null;
  active_model: string;
  classes: string[];
  threshold_scale: number;
  thresholds: Record<string, Record<string, number>>;
  liveness_enabled?: boolean;
  liveness?: Record<string, LivenessProfile>;
  meta: ReportMeta | null;
}

export interface LivenessProfile {
  active: boolean;
  n: number;
  median_ppm?: number;
  sd_ppm?: number;
  tolerance_ppm?: number;
  reason: string;
}

export interface LivenessReport {
  profiles: Record<string, LivenessProfile>;
  genuine_test: Record<string, { presses: number; median_ppm: number; rejected: number }>;
  impostor_test: Record<string, { presses: number; median_ppm: number; claimed: string | null; rejected: number | null }>;
}

export interface HubStatus {
  receiver: ReceiverStatus;
  transmitter: { connected: boolean; port: string | null };
  simulation: boolean;
  model: ModelInfo;
  recording: RecordingStatus | null;
  last_recording: RecordingStatus | null;
  training: TrainingState;
  quality: Record<string, number>;
  verdicts: Record<string, number>;
  clients: number;
}

export interface RocStats {
  eer: number | null;
  auc: number | null;
  far: number | null;
  frr: number | null;
  roc: [number, number][];
  n_genuine?: number;
  n_impostor?: number;
}

export interface ModelReport {
  closed_set: { accuracy: number | null; labels: string[]; confusion: number[][]; per_class: Record<string, { frames: number; accuracy: number | null; threshold: number }> };
  verification: { frame: RocStats; burst: RocStats; burst_combined_frr?: number | null };
  attacks: { device: string; kind: string; claimed: string | null; code: string; bursts: number; rejected_bursts: number; rejection_rate: number | null; combined_rejection_rate?: number | null; frame_rejection_rate: number | null }[];
  by_distance: { distance_m: number; frames: number; frr: number; accuracy: number | null }[];
}

export interface ReportMeta {
  created_at: string;
  train_seconds: number;
  classes: string[];
  split_strategy: string;
  frames: Record<string, number>;
  dataset: Record<string, { frames: number; sessions: string[]; bursts: number; top_code: string; rejected: Record<string, number> }>;
  parameters: Record<string, number>;
  feature_names: string[];
  target_frr: number;
  threshold_margin: number;
  validation_eer: Record<string, number>;
  active_model: string;
  simulated_data: boolean;
}

export interface Report {
  models: Record<'fusion' | 'edge', ModelReport>;
  feature_importance: { feature: string; eer: number | null; delta_eer: number | null }[];
  embedding_map: { points: { x: number; y: number; device: string; enrolled: boolean }[]; explained: number | null };
  liveness?: LivenessReport;
  meta: ReportMeta;
}

export interface SimDevice {
  name: string;
  kind: string;
  code: string;
  clock_t_us: number;
}

export interface PortInfo {
  device: string;
  description: string;
  hwid: string;
  likely_esp32: boolean;
}
