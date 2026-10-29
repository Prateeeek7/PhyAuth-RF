'use client';

import React, { useEffect, useState } from 'react';
import { api, SimDevice } from '../../lib/api';
import { LogicTrace, ResidualBars, ScoreMeter, deviceColor } from '../charts';
import { useApp } from '../shell/AppContext';
import { Badge, Kpi, PageHead, Panel, VERDICT_TEXT, num, timeOf, verdictTone } from '../ui';

export function LiveView() {
  const { live } = useApp();
  const { status, frames, decisions } = live;
  const last = decisions[0];
  const lastFrame = [...frames].reverse().find((f) => f.ok) ?? frames[frames.length - 1] ?? null;
  const sim = status?.simulation;
  const modelReady = status?.model.ready;

  return (
    <>
      <PageHead title="Live authentication"
        sub="Every button press is decoded, fingerprinted and decided: on the laptop and on the ESP32 itself." />

      <section className={`verdict verdict-${last ? verdictTone(last.verdict) : 'idle'}`}>
        {last ? (
          <div className="verdict-grid">
            <div>
              <div className="verdict-title">{VERDICT_TEXT[last.verdict] ?? last.verdict}</div>
              <div className="verdict-sub">
                {last.claim_source === 'code'
                  ? <>code <code>{last.code}</code> claims <b>{last.claimed}</b></>
                  : <>code <code>{last.code}</code> not enrolled · fingerprint matches <b>{last.claimed ?? '—'}</b></>}
                {' · '}{timeOf(last.time)} {last.simulated && <Badge tone="warning">SIMULATED</Badge>}
              </div>
            </div>
            <div>
              <ScoreMeter score={last.score} />
              <div className="kpi-row tight">
                <Kpi label="Score (≤ 1 passes)" value={num(last.score, 2)} tone={last.score <= 1 ? 'ok' : 'bad'} />
                <Kpi label="Frames fused" value={last.frames} />
                <Kpi label="Clock T" value={`${num(last.clock_t_us, 2)} µs`} />
                <Kpi label="Decided on" value={last.source === 'edge' ? 'ESP32' : 'Laptop'} />
                <Kpi label="Start-up drift" value={last.drift_ppm == null ? '—' : `${num(last.drift_ppm, 0)} ppm`}
                  tone={last.liveness == null ? undefined : last.liveness === 'ok' ? 'ok' : 'bad'} />
              </div>
            </div>
          </div>
        ) : (
          <div className="empty">{modelReady ? 'Waiting for the first button press…' : 'No trained model yet: record devices in Capture, then train in Model lab. Frames are still decoded below.'}</div>
        )}
      </section>

      <div className="split-main">
        <Panel title="Last frame" sub="Pulse train and per-pulse timing residuals"
          right={lastFrame ? <Badge tone={lastFrame.ok ? 'success' : 'idle'}>{lastFrame.quality}</Badge> : null}>
          <LogicTrace frame={lastFrame} />
          <ResidualBars frame={lastFrame} height={120} />
          {lastFrame && (
            <div className="kpi-row tight">
              <Kpi label="Decoded code" value={lastFrame.code || '—'} />
              <Kpi label="Clock T" value={`${num(lastFrame.clock_t_us, 3)} µs`} />
              <Kpi label="Bit jitter" value={`${num(lastFrame.features?.pair_jitter_ppm ?? null, 0)} ppm`} />
              <Kpi label="Frame score" value={num(lastFrame.score, 2)} tone={lastFrame.score === undefined ? undefined : lastFrame.frame_accept ? 'ok' : 'bad'} />
            </div>
          )}
        </Panel>
        <div className="stack">
          <ReceiverHealth />
          {sim && <VirtualLab />}
        </div>
      </div>

      <Panel title="Decision log" sub={`${decisions.length} recent decisions`} flush>
        <div className="table-scroll tall">
          <table className="eng-table">
            <thead>
              <tr><th>Time</th><th>Verdict</th><th>Device</th><th>Code</th><th className="num">Score</th><th>Liveness</th><th className="num">Frames</th><th>Decided by</th>{sim && <th>Pressed</th>}</tr>
            </thead>
            <tbody>
              {decisions.slice(0, 60).map((d, i) => (
                <tr key={i}>
                  <td className="muted">{timeOf(d.time)}</td>
                  <td><Badge tone={verdictTone(d.verdict)}>{VERDICT_TEXT[d.verdict] ?? d.verdict}</Badge></td>
                  <td style={{ color: deviceColor(d.claimed), fontWeight: 600 }}>{d.claimed ?? '—'}</td>
                  <td><code>{d.code}</code></td>
                  <td className="num">{num(d.score, 2)}</td>
                  <td>{d.liveness == null ? <span className="muted">n/a</span> : <Badge tone={d.liveness === 'ok' ? 'success' : 'danger'}>{d.liveness === 'ok' ? 'ok' : 'no drift'}</Badge>}</td>
                  <td className="num">{d.frames}</td>
                  <td>{d.source === 'edge' ? 'ESP32' : 'Laptop'}</td>
                  {sim && <td>{d.sim_source ?? '—'}</td>}
                </tr>
              ))}
              {!decisions.length && <tr><td colSpan={9} className="empty">No decisions yet</td></tr>}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}

function ReceiverHealth() {
  const { live } = useApp();
  const rx = live.status?.receiver;
  const q = live.status?.quality ?? {};
  const total = Object.values(q).reduce((a, b) => a + b, 0);
  const rejected = Object.entries(q).filter(([k]) => k !== 'ok');
  return (
    <Panel title="Receiver health" sub={rx?.port ?? 'not connected'}>
      <div className="kpi-row two" style={{ marginTop: 0 }}>
        <Kpi label="Link" value={rx?.mode ?? '—'} tone={rx?.mode === 'hardware' ? 'ok' : rx?.mode === 'simulation' ? 'warn' : 'bad'} />
        <Kpi label="Frames" value={rx?.frames_rx ?? 0} />
        <Kpi label="Noise edges/s" value={live.rxStats?.noise_eps ?? '—'} />
        <Kpi label="Decoded OK" value={total ? `${((100 * (q.ok ?? 0)) / total).toFixed(0)}%` : '—'} />
      </div>
      {rejected.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div className="section-label">Rejected by the quality gate</div>
          {rejected.map(([k, v]) => (
            <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '3px 0' }}>
              <span className="hint">{k.replace(/_/g, ' ')}</span><span style={{ fontFamily: 'var(--font-mono)' }}>{v}</span>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

function VirtualLab() {
  const { notify, devices } = useApp();
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
    <Panel title="Virtual RF lab" sub="Simulator: press a virtual transmitter" right={<Badge tone="warning">SIMULATED</Badge>}>
      <div className="btn-row">
        {sim.map((s) => (
          <button key={s.name} className={`eng-btn ${s.kind === 'crystal_clone' ? 'eng-btn-danger' : ''}`} onClick={() => press(s.name)}
            title={`${s.kind} · code ${s.code} · T ${s.clock_t_us} µs${registered.has(s.name) ? '' : ' · not registered'}`}>
            {s.name}
          </button>
        ))}
      </div>
      <div className="divider" />
      <div className="btn-row" style={{ alignItems: 'center' }}>
        <button className="eng-btn" onClick={toggle}>{auto ? 'Pause autoplay' : 'Resume autoplay'}</button>
        <label className="hint" style={{ flex: 1, minWidth: 160 }}>
          Distance {dist} m
          <input type="range" min={0.5} max={12} step={0.5} value={dist} onChange={(e) => setDist(parseFloat(e.target.value))} />
        </label>
      </div>
    </Panel>
  );
}
