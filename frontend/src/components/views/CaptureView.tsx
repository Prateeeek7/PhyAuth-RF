'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api, Device, HubStatus, RecordingStatus, SimDevice } from '../../lib/api';
import { Badge, Field, Kpi, Notify, Panel } from '../ui';

interface Experiment {
  id: number;
  experiment_name: string;
  transmitter_id: string;
  session_id: string;
  distance_meters: number;
  orientation_deg: number;
  created_at: string;
  filepath_prefix: string;
  frames_total: number;
  frames_good: number;
  dominant_code: string | null;
  clock_t_us: number | null;
  source: string;
}

interface DatasetSummary {
  frames: number;
  devices: Record<string, { frames: number; sessions: string[]; bursts: number; top_code: string; rejected: Record<string, number> }>;
  files: string[];
}

export function CaptureView({ status, devices, recording, notify }: { status: HubStatus | null; devices: Device[]; recording: RecordingStatus | null; notify: Notify }) {
  const sim = status?.simulation;
  const [form, setForm] = useState({
    device_id: '', session_id: 's01', experiment_name: 'capture', distance_m: 1, orientation_deg: 0,
    target_good_frames: 150, timeout_s: 180, sim_source: '',
  });
  const [recs, setRecs] = useState<Experiment[]>([]);
  const [summary, setSummary] = useState<DatasetSummary | null>(null);
  const [simDevs, setSimDevs] = useState<SimDevice[]>([]);
  const [txConnected, setTxConnected] = useState(false);
  const txAuto = useRef(false);   // we started AUTO on the transmitter node

  const reload = useCallback(() => {
    api.get<Experiment[]>('/api/recordings').then(setRecs).catch(() => undefined);
    api.get<DatasetSummary>('/api/recordings/dataset').then(setSummary).catch(() => undefined);
  }, []);

  useEffect(() => { reload(); }, [reload]);
  useEffect(() => {
    const poll = () => api.get<{ connected: boolean }>('/api/attack/status').then((r) => setTxConnected(r.connected)).catch(() => undefined);
    poll();
    const t = setInterval(poll, 4000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    if (sim) api.get<SimDevice[]>('/api/hardware/sim/devices').then(setSimDevs).catch(() => undefined);
  }, [sim]);
  const active = recording && recording.state === 'recording' ? recording : null;
  const deviceId = form.device_id || devices[0]?.device_id || '';
  useEffect(() => {
    if (recording && recording.state !== 'recording') {
      reload();
      if (txAuto.current) {   // recording finished: silence the transmitter node
        txAuto.current = false;
        api.post('/api/attack/tx/command', { command: 'AUTO 0' }).catch(() => undefined);
      }
    }
  }, [recording?.state, reload]); // eslint-disable-line react-hooks/exhaustive-deps

  const txCmd = (command: string) => api.post('/api/attack/tx/command', { command });
  const txRun = async (label: string, steps: () => Promise<unknown>) => {
    try {
      await steps();
      txAuto.current = true;
      notify(`Transmitter node: ${label}, one press every 1.2 s. Start the recording now.`, 'info');
    } catch (e) {
      notify(String(e), 'danger');
    }
  };
  const victims = devices.filter((d) => d.is_authorized && d.code && d.kind === 'fob');

  const start = async () => {
    try {
      const body = { ...form, device_id: deviceId, sim_source: sim ? (form.sim_source || deviceId) : null };
      await api.post('/api/recordings/start', body);
      notify(`Recording ${deviceId} (${form.session_id}). ${sim ? 'The simulator presses the virtual transmitter for you.' : 'Press the transmitter button repeatedly, ~1 s apart.'}`, 'info');
    } catch (e) {
      notify(String(e), 'danger');
    }
  };
  const stop = async () => {
    try { await api.post('/api/recordings/stop'); } catch (e) { notify(String(e), 'danger'); }
  };
  const del = async (id: number) => {
    if (!confirm('Delete this recording file?')) return;
    await api.del(`/api/recordings/${id}`).catch((e) => notify(String(e), 'danger'));
    reload();
  };

  const set = (k: string, v: string | number) => setForm((f) => ({ ...f, [k]: v }));
  const dev = devices.find((d) => d.device_id === deviceId);
  const sessionsPerDevice = summary ? Object.values(summary.devices).map((d) => d.sessions.length) : [];

  return (
    <div className="grid-2">
      <Panel title="Record labelled frames">
        {!devices.length && <p className="hint">Register transmitters in the <b>Devices</b> tab first.</p>}
        <div className="form-grid">
          <Field label="Transmitter">
            <select className="eng-select" value={deviceId} onChange={(e) => set('device_id', e.target.value)}>
              {devices.map((d) => <option key={d.device_id} value={d.device_id}>{d.device_id} — {d.name}{d.is_authorized ? '' : ' (not enrolled)'}</option>)}
            </select>
          </Field>
          <Field label="Session ID">
            <input className="eng-input" value={form.session_id} onChange={(e) => set('session_id', e.target.value)} />
          </Field>
          <Field label="Distance (m)">
            <input className="eng-input" type="number" step={0.5} min={0.1} value={form.distance_m} onChange={(e) => set('distance_m', parseFloat(e.target.value))} />
          </Field>
          <Field label="Orientation (°)">
            <input className="eng-input" type="number" step={15} value={form.orientation_deg} onChange={(e) => set('orientation_deg', parseFloat(e.target.value))} />
          </Field>
          <Field label="Good frames to collect">
            <input className="eng-input" type="number" min={10} value={form.target_good_frames} onChange={(e) => set('target_good_frames', parseInt(e.target.value))} />
          </Field>
          <Field label="Timeout (s)">
            <input className="eng-input" type="number" min={5} value={form.timeout_s} onChange={(e) => set('timeout_s', parseFloat(e.target.value))} />
          </Field>
          {sim && (
            <Field label="Virtual transmitter (simulator)">
              <select className="eng-select" value={form.sim_source || deviceId} onChange={(e) => set('sim_source', e.target.value)}>
                {simDevs.map((s) => <option key={s.name} value={s.name}>{s.name} ({s.kind})</option>)}
              </select>
            </Field>
          )}
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          <button className="eng-btn eng-btn-primary" disabled={!!active || !devices.length} onClick={start}>Start recording</button>
          <button className="eng-btn eng-btn-danger" disabled={!active} onClick={stop}>Stop</button>
        </div>
        {dev && (
          <p className="hint" style={{ marginTop: 8 }}>
            {dev.code ? <>Code-lock active: only frames decoding to <code>{dev.code}</code> are stored. Other 433 MHz devices nearby are ignored.</>
              : <>The code of {dev.device_id} is not known yet. It is learned from this recording and locked after 8 consistent frames.</>}
          </p>
        )}
        {recording && <RecordingProgress r={recording} />}

        <div style={{ borderTop: '1px solid var(--grid-color)', marginTop: 12, paddingTop: 10 }}>
          <div className="eng-label">ESP32 transmitter node (one board plays EMU_1..3 and the clone)</div>
          {txConnected ? (
            <>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {[1, 2, 3].map((p) => (
                  <button key={p} className="eng-btn" onClick={() => txRun(`PROFILE ${p}`, async () => { await txCmd(`PROFILE ${p}`); await txCmd('AUTO 1200'); })}>
                    EMU_{p}: profile {p} + auto
                  </button>
                ))}
                {victims.map((v) => (
                  <button key={v.device_id} className="eng-btn eng-btn-danger"
                    onClick={() => txRun(`clone of ${v.device_id}`, async () => {
                      await api.post('/api/attack/clone', { target_device_id: v.device_id, frames: 10 });
                      await txCmd('AUTO 1200');
                    })}>
                    CLONE_A: clone {v.device_id} + auto
                  </button>
                ))}
                <button className="eng-btn" onClick={() => { txAuto.current = false; txCmd('AUTO 0').catch((e) => notify(String(e), 'danger')); }}>Stop node (AUTO 0)</button>
              </div>
              <p className="hint" style={{ marginTop: 6 }}>Recording your real remote? Keep the node silent (AUTO 0) and press the remote&apos;s button yourself, about 1 s apart. The node is stopped automatically when a recording ends.</p>
            </>
          ) : (
            <p className="hint">{sim ? 'Simulator: the virtual transmitter above is pressed for you.' : 'Connect the transmitter node in the Attack tab to record EMU_1..3 and CLONE_A hands-free (or press its BOOT button).'}</p>
          )}
        </div>
      </Panel>

      <Panel title="Dataset" right={<button className="eng-btn" onClick={reload}>Refresh</button>}>
        {summary && (
          <>
            <div className="kpi-row">
              <Kpi label="usable frames" value={summary.frames} />
              <Kpi label="files" value={summary.files.length} />
              <Kpi label="split" value={sessionsPerDevice.length && Math.min(...sessionsPerDevice) >= 2 ? 'cross-session' : 'temporal'}
                hint="With ≥2 sessions per device the newest session becomes the test set" />
            </div>
            <table className="eng-table" style={{ marginTop: 8 }}>
              <thead><tr><th>device</th><th>frames</th><th>presses</th><th>sessions</th><th>code</th><th>rejected</th></tr></thead>
              <tbody>
                {Object.entries(summary.devices).map(([d, s]) => (
                  <tr key={d}>
                    <td>{d}</td><td>{s.frames}</td><td>{s.bursts}</td><td>{s.sessions.join(', ')}</td><td><code>{s.top_code}</code></td>
                    <td className="hint">{Object.entries(s.rejected).map(([k, v]) => `${k}:${v}`).join(' ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
        <div className="checklist">
          <div className="eng-label">Protocol for credible results</div>
          <ol>
            <li>≥ 150 good frames (≈15 presses) per device per session. Use the <i>same button</i> of the remote every time.</li>
            <li>≥ 2 sessions per device on different days or times (temperature and battery drift). This enables cross-session testing.</li>
            <li>Vary the distance (1 m, 3 m, 5 m) and orientation (0°, 90°) within sessions, so the model learns hardware, not channel.</li>
            <li>With one remote: enroll FOB_A plus EMU_1 and EMU_2 (ESP32 node profiles) so training has ≥ 2 classes.</li>
            <li>Record CLONE_A (node replaying FOB_A) and EMU_3 as <i>not enrolled</i>. They are used only as zero-shot attackers in testing.</li>
            <li>Release the button between presses: every press must start the remote from cold (liveness).</li>
          </ol>
        </div>
      </Panel>

      <Panel title="Recordings" style={{ gridColumn: '1 / -1' }}>
        <div className="table-scroll">
          <table className="eng-table">
            <thead><tr><th>time</th><th>device</th><th>session</th><th>dist</th><th>orient</th><th>good / total</th><th>code</th><th>T (µs)</th><th>source</th><th>file</th><th /></tr></thead>
            <tbody>
              {recs.map((r) => (
                <tr key={r.id}>
                  <td>{new Date(r.created_at + (r.created_at.endsWith('Z') || r.created_at.includes('+') ? '' : 'Z')).toLocaleString()}</td>
                  <td>{r.transmitter_id}</td><td>{r.session_id}</td><td>{r.distance_meters} m</td><td>{r.orientation_deg}°</td>
                  <td>{r.frames_good} / {r.frames_total}</td><td><code>{r.dominant_code ?? '—'}</code></td>
                  <td>{r.clock_t_us?.toFixed(3) ?? '—'}</td>
                  <td>{r.source === 'simulation' ? <Badge tone="warning">sim</Badge> : <Badge tone="info">hw</Badge>}</td>
                  <td className="hint">{r.filepath_prefix}</td>
                  <td><button className="eng-btn" onClick={() => del(r.id)}>Delete</button></td>
                </tr>
              ))}
              {!recs.length && <tr><td colSpan={11} className="hint">No recordings yet</td></tr>}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

function RecordingProgress({ r }: { r: RecordingStatus }) {
  const frac = Math.min(1, r.frames_good / r.target_good);
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
        <span>{r.device_id} · {r.session_id} · <Badge tone={r.state === 'recording' ? 'info' : r.state === 'done' ? 'success' : 'warning'}>{r.state}</Badge></span>
        <span className="hint">{r.elapsed_s}s / {r.timeout_s}s</span>
      </div>
      <div className="progress"><div style={{ width: `${frac * 100}%` }} /></div>
      <div className="kpi-row">
        <Kpi label="good frames" value={`${r.frames_good} / ${r.target_good}`} />
        <Kpi label="all frames" value={r.frames_total} />
        <Kpi label="code" value={r.dominant_code ?? '—'} />
        <Kpi label="clock T" value={r.clock_t_us ? `${r.clock_t_us.toFixed(3)} µs` : '—'} />
        <Kpi label="foreign (ignored)" value={r.foreign_frames} tone={r.foreign_frames ? 'warn' : undefined} />
      </div>
      {Object.keys(r.reject_reasons).length > 0 && (
        <div className="hint">rejected by quality gate: {Object.entries(r.reject_reasons).map(([k, v]) => `${k} ${v}`).join(' · ')}</div>
      )}
    </div>
  );
}
