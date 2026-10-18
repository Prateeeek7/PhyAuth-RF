'use client';

import React, { useEffect, useState } from 'react';
import { api, Decision, Device, FrameEvent, HubStatus, SimDevice } from '../../lib/api';
import { LogicTrace, ResidualBars, ScoreMeter, deviceColor } from '../charts';
import { Badge, Kpi, Notify, Panel, VERDICT_TEXT, num, timeOf, verdictTone } from '../ui';

interface Props {
  status: HubStatus | null;
  frames: FrameEvent[];
  decisions: Decision[];
  rxStats: Record<string, number> | null;
  devices: Device[];
  notify: Notify;
}

export function LiveView({ status, frames, decisions, rxStats, devices, notify }: Props) {
  const last = decisions[0];
  const lastFrame = [...frames].reverse().find((f) => f.ok) ?? frames[frames.length - 1] ?? null;
  const sim = status?.simulation;
  const modelReady = status?.model.ready;

  return (
    <div className="grid-live">
      <Panel title="Authentication decision" right={last?.simulated ? <Badge tone="warning">SIMULATED</Badge> : null}>
        {!modelReady && (
          <p className="hint">No trained model yet. Register devices, record them in <b>Capture</b>, then train in <b>Model Lab</b>. Frames are still decoded below.</p>
        )}
        {last ? (
          <div className={`verdict verdict-${verdictTone(last.verdict)}`}>
            <div className="verdict-title">{VERDICT_TEXT[last.verdict] ?? last.verdict}</div>
            <div className="verdict-sub">
              {last.claim_source === 'code'
                ? <>code <code>{last.code}</code> claims <b>{last.claimed}</b></>
                : <>code <code>{last.code}</code> not enrolled · nearest fingerprint <b>{last.claimed ?? '—'}</b></>}
            </div>
            <ScoreMeter score={last.score} />
            <div className="kpi-row">
              <Kpi label="score (dist/thr)" value={num(last.score, 2)} tone={last.score <= 1 ? 'ok' : 'bad'} />
              <Kpi label="frames fused" value={last.frames} />
              <Kpi label="clock T" value={`${num(last.clock_t_us, 2)} µs`} />
              <Kpi label="decided on" value={last.source === 'edge' ? 'ESP32' : `host · ${last.model}`} />
              <Kpi label="start-up drift" value={last.drift_ppm == null ? '—' : `${num(last.drift_ppm, 0)} ppm`}
                hint="Cold-start clock drift over the first frames of the press (battery fobs drift, always-on crystal transmitters do not)"
                tone={last.liveness == null ? undefined : last.liveness === 'ok' ? 'ok' : 'bad'} />
            </div>
            {last.liveness && last.liveness !== 'ok' && (
              <div className="hint" style={{ color: 'var(--danger)' }}>
                Liveness failed: {last.fingerprint_ok ? 'the fingerprint matched, but ' : ''}the press showed no cold-start drift, so it is treated as a replay.
              </div>
            )}
            {last.sim_source && <div className="hint">virtual transmitter actually pressed: <b>{last.sim_source}</b></div>}
          </div>
        ) : (
          <p className="hint">Waiting for the first button press…</p>
        )}
      </Panel>

      <Panel title="Last frame — pulse train" right={lastFrame ? <Badge tone={lastFrame.ok ? 'success' : 'idle'}>{lastFrame.quality}</Badge> : null}>
        <LogicTrace frame={lastFrame} />
        <ResidualBars frame={lastFrame} height={110} />
        {lastFrame && (
          <div className="kpi-row">
            <Kpi label="decoded code" value={lastFrame.code || '—'} />
            <Kpi label="clock T" value={`${num(lastFrame.clock_t_us, 3)} µs`} />
            <Kpi label="bit-period jitter" value={`${num(lastFrame.features?.pair_jitter_ppm ?? null, 0)} ppm`} />
            <Kpi label="frame score" value={num(lastFrame.score, 2)} tone={lastFrame.score === undefined ? undefined : lastFrame.frame_accept ? 'ok' : 'bad'} />
          </div>
        )}
      </Panel>

      <Panel title="Decision log">
        <div className="table-scroll">
          <table className="eng-table">
            <thead>
              <tr><th>time</th><th>verdict</th><th>claimed</th><th>code</th><th>score</th><th>liveness</th><th>frames</th><th>by</th>{sim && <th>pressed</th>}</tr>
            </thead>
            <tbody>
              {decisions.slice(0, 40).map((d, i) => (
                <tr key={i}>
                  <td>{timeOf(d.time)}</td>
                  <td><Badge tone={verdictTone(d.verdict)}>{VERDICT_TEXT[d.verdict] ?? d.verdict}</Badge></td>
                  <td style={{ color: deviceColor(d.claimed) }}>{d.claimed ?? '—'}</td>
                  <td><code>{d.code}</code></td>
                  <td>{num(d.score, 2)}</td>
                  <td>{d.liveness == null ? <span className="hint">n/a</span> : <Badge tone={d.liveness === 'ok' ? 'success' : 'danger'}>{d.liveness === 'ok' ? 'ok' : 'no drift'}</Badge>}</td>
                  <td>{d.frames}</td>
                  <td>{d.source === 'edge' ? 'ESP32' : 'host'}</td>
                  {sim && <td>{d.sim_source ?? '—'}</td>}
                </tr>
              ))}
              {!decisions.length && <tr><td colSpan={9} className="hint">No decisions yet</td></tr>}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="Receiver">
        <ReceiverSummary status={status} rxStats={rxStats} />
        {sim && <VirtualLab notify={notify} devices={devices} />}
      </Panel>
    </div>
  );
}

function ReceiverSummary({ status, rxStats }: { status: HubStatus | null; rxStats: Record<string, number> | null }) {
  const rx = status?.receiver;
  const q = status?.quality ?? {};
  const total = Object.values(q).reduce((a, b) => a + b, 0);
  return (
    <div>
      <div className="kpi-row">
        <Kpi label="link" value={rx?.mode ?? '—'} tone={rx?.mode === 'hardware' ? 'ok' : rx?.mode === 'simulation' ? 'warn' : 'bad'} />
        <Kpi label="frames received" value={rx?.frames_rx ?? 0} />
        <Kpi label="RF noise edges/s" value={rxStats?.noise_eps ?? '—'} hint="SRX882 output toggles per second; high when the band is idle (AGC at max gain)" />
        <Kpi label="decoded OK" value={total ? `${((100 * (q.ok ?? 0)) / total).toFixed(0)}%` : '—'} />
      </div>
      <div className="hint" style={{ marginTop: 6 }}>
        rejected: {Object.entries(q).filter(([k]) => k !== 'ok').map(([k, v]) => `${k} ${v}`).join(' · ') || 'none'}
      </div>
    </div>
  );
}

function VirtualLab({ notify, devices }: { notify: Notify; devices: Device[] }) {
  const [sim, setSim] = useState<SimDevice[]>([]);
  const [auto, setAuto] = useState(true);
  const [dist, setDist] = useState(1);
  useEffect(() => {
    api.get<SimDevice[]>('/api/hardware/sim/devices').then(setSim).catch(() => undefined);
  }, []);
  const press = async (name: string) => {
    try {
      await api.post('/api/hardware/sim/press', { name, distance_m: dist, orientation_deg: 0 });
    } catch (e) {
      notify(String(e), 'danger');
    }
  };
  const toggle = async () => {
    try {
      await api.post('/api/hardware/sim/autoplay', { enabled: !auto, interval_s: 2.5 });
      setAuto(!auto);
    } catch (e) {
      notify(String(e), 'danger');
    }
  };
  const registered = new Set(devices.map((d) => d.device_id));
  return (
    <div style={{ marginTop: 12, borderTop: '1px solid var(--grid-color)', paddingTop: 10 }}>
      <div className="eng-label">Virtual RF lab (simulator) — press a transmitter</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, margin: '6px 0' }}>
        {sim.map((s) => (
          <button key={s.name} className={`eng-btn ${s.kind === 'crystal_clone' ? 'eng-btn-danger' : ''}`} onClick={() => press(s.name)}
            title={`${s.kind} · code ${s.code} · T ${s.clock_t_us} µs${registered.has(s.name) ? '' : ' · not registered'}`}>
            {s.name}
          </button>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <button className="eng-btn" onClick={toggle}>{auto ? 'Pause autoplay' : 'Resume autoplay'}</button>
        <label className="hint" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          distance {dist} m
          <input type="range" min={0.5} max={12} step={0.5} value={dist} onChange={(e) => setDist(parseFloat(e.target.value))} />
        </label>
      </div>
    </div>
  );
}
