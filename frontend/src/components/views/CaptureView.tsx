'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api, RecordingStatus, SimDevice } from '../../lib/api';
import { useApp } from '../shell/AppContext';
import { Badge, Field, Kpi, PageHead, Panel } from '../ui';

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

export function CaptureView() {
  const { live, devices, notify, online } = useApp();
  const status = live.status;
  const recording = live.recording;
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

  useEffect(() => { reload(); }, [reload, online]);
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
  const deviceId = form.device_id || devices.find((d) => d.is_authorized && d.code)?.device_id || devices[0]?.device_id || '';
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
    <>
      <PageHead title="Capture" sub="Record labelled button presses for training and testing. Code-lock keeps other 433 MHz devices out of the data." />
      <div className="split-side stretch">
      <Panel title="Record labelled frames" sub="One device, one session, one distance per recording">
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
        <div className="btn-row" style={{ marginTop: 14 }}>
          <button className="eng-btn eng-btn-primary lg" disabled={!!active || !devices.length} onClick={start}>Start recording</button>
          <button className="eng-btn eng-btn-danger" disabled={!active} onClick={stop}>Stop</button>
        </div>
        {dev && (
          <p className="hint" style={{ marginTop: 8 }}>
            {dev.code ? <>Code-lock active: only frames decoding to <code>{dev.code}</code> are stored. Other 433 MHz devices nearby are ignored.</>
              : <>The code of {dev.device_id} is not known yet. It is learned from this recording and locked after 8 consistent frames.</>}
          </p>
        )}
        <div className="divider" />
        <div>
          <div className="section-label">ESP32 transmitter node (one board plays EMU_1..3 and the clone)</div>
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

      <div className="stack fill-col">
      {recording && (
        <Panel title="Recording progress" sub={`${recording.device_id} · session ${recording.session_id}`}>
          <RecordingProgress r={recording} />
        </Panel>
      )}
      <Panel className="grow" title="Dataset" sub="Usable frames on disk, after the quality gate" right={<button className="eng-btn" onClick={reload}>Refresh</button>}>
        {summary && (
          <>
            <div className="kpi-row" style={{ marginTop: 0 }}>
              <Kpi label="usable frames" value={summary.frames} />
              <Kpi label="files" value={summary.files.length} />
              <Kpi label="split" value={sessionsPerDevice.length && Math.min(...sessionsPerDevice) >= 2 ? 'cross-session' : 'temporal'}
                hint="With ≥2 sessions per device the newest session becomes the test set" />
            </div>
            <div className="table-scroll" style={{ marginTop: 12 }}>
            <table className="eng-table">
              <thead><tr><th>Device</th><th className="num">Frames</th><th className="num">Presses</th><th>Sessions</th><th>Code</th><th>Rejected</th></tr></thead>
              <tbody>
                {Object.entries(summary.devices).map(([d, s]) => (
                  <tr key={d}>
                    <td style={{ fontWeight: 600 }}>{d}</td><td className="num">{s.frames}</td><td className="num">{s.bursts}</td><td>{s.sessions.join(', ')}</td><td><code>{s.top_code}</code></td>
                    <td className="hint">{Object.entries(s.rejected).map(([k, v]) => `${k}:${v}`).join(' ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </>
        )}
      </Panel>
      </div>
      </div>

      <Panel title="Protocol for credible results">
        <div className="checklist">
          <ol>
            <li>≥ 150 good frames (≈15 presses) per device per session. Record <i>every button</i> the remote is used with (ON and OFF: the lock pattern uses both).</li>
            <li>≥ 2 sessions per device on different days or times (temperature and battery drift). This enables cross-session testing.</li>
            <li>Vary the distance across the working range (0.75 m, 1 m, 1.25 m with the SRX882 spring antenna) and how the remote is held, so the model learns hardware, not channel.</li>
            <li>With one remote: enroll FOB_A plus EMU_1 and EMU_2 (ESP32 node profiles) so training has ≥ 2 classes.</li>
            <li>Record CLONE_A (node replaying FOB_A) and EMU_3 as <i>not enrolled</i>. They are used only as zero-shot attackers in testing.</li>
            <li>Release the button between presses: every press must start the remote from cold (liveness).</li>
          </ol>
        </div>
      </Panel>

      <Panel title="Recordings" sub="Made through this dashboard" flush>
        <div className="table-scroll tall">
          <table className="eng-table">
            <thead><tr><th>Time</th><th>Device</th><th>Session</th><th className="num">Dist</th><th className="num">Orient</th><th className="num">Good / total</th><th>Code</th><th className="num">T (µs)</th><th>Source</th><th>File</th><th /></tr></thead>
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
              {!recs.length && <tr><td colSpan={11} className="empty">No recordings yet</td></tr>}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}

function RecordingProgress({ r }: { r: RecordingStatus }) {
  const frac = Math.min(1, r.frames_good / r.target_good);
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
        <span>{r.device_id} · {r.session_id} · <Badge tone={r.state === 'recording' ? 'info' : r.state === 'done' ? 'success' : 'warning'}>{r.state}</Badge></span>
        <span className="hint">{r.elapsed_s}s / {r.timeout_s}s</span>
      </div>
      <div className="progress"><div style={{ width: `${frac * 100}%` }} /></div>
      <div className="kpi-row tight">
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
