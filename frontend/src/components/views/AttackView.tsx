'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { api, Decision, Device, PortInfo, SimDevice } from '../../lib/api';
import { Badge, Field, Notify, Panel, VERDICT_TEXT, num, timeOf, verdictTone } from '../ui';

interface AttackStatus {
  connected: boolean;
  port: string | null;
  log: Record<string, unknown>[];
  simulation: boolean;
  sim_devices: SimDevice[];
  ports: PortInfo[];
}

export function AttackView({ devices, decisions, notify }: { devices: Device[]; decisions: Decision[]; notify: Notify }) {
  const [st, setSt] = useState<AttackStatus | null>(null);
  const [port, setPort] = useState('');
  const [target, setTarget] = useState('');
  const [manual, setManual] = useState('INFO');
  const reload = useCallback(() => api.get<AttackStatus>('/api/attack/status').then(setSt).catch(() => undefined), []);
  useEffect(() => {
    reload();
    const t = setInterval(reload, 3000);
    return () => clearInterval(t);
  }, [reload]);
  const victims = devices.filter((d) => d.is_authorized && d.code);
  const victim = target || victims[0]?.device_id || '';

  const call = async (p: string, body?: unknown, ok?: string) => {
    try {
      const r = await api.post<Record<string, unknown>>(p, body);
      if (ok) notify(ok + (r && 'sent' in r ? ` → ${r.sent}` : r && 'pressed' in r ? ` → ${r.pressed}` : ''), 'info');
      reload();
    } catch (e) {
      notify(String(e), 'danger');
    }
  };

  return (
    <div className="split-side stretch">
      <Panel title="Clone / replay attack">
        <div className="form-grid">
          <Field label="Victim (enrolled device with learned code)">
            <select className="eng-select" value={victim} onChange={(e) => setTarget(e.target.value)}>
              {victims.map((d) => <option key={d.device_id} value={d.device_id}>{d.device_id} · {d.code}</option>)}
            </select>
          </Field>
        </div>
        <button className="eng-btn eng-btn-danger" style={{ marginTop: 8 }} disabled={!victim}
          onClick={() => call('/api/attack/clone', { target_device_id: victim, frames: 10 }, 'Clone transmitted')}>
          Launch clone attack
        </button>
        <p className="hint" style={{ marginTop: 6 }}>
          {st?.connected ? <>Hardware: sends <code>CLONE &lt;code&gt; &lt;T&gt;</code> to the ESP32 transmitter node on {st.port}.</>
            : st?.simulation ? <>Simulator: presses the virtual crystal-clocked clone of the victim.</>
              : <>Connect the transmitter node below.</>}
        </p>

        <div style={{ borderTop: '1px solid var(--grid-color)', marginTop: 12, paddingTop: 10 }}>
          <div className="eng-label">Transmitter node (ESP32 + STX882, 115200 baud)</div>
          {st?.connected ? (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <Badge tone="success">connected {st.port}</Badge>
              <button className="eng-btn" onClick={() => call('/api/attack/tx/disconnect')}>Disconnect</button>
            </div>
          ) : (
            <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
              <Field label="Port">
                <select className="eng-select" value={port} onChange={(e) => setPort(e.target.value)}>
                  <option value="">select…</option>
                  {st?.ports.map((p) => <option key={p.device} value={p.device}>{p.device} {p.likely_esp32 ? '★' : ''} {p.description}</option>)}
                </select>
              </Field>
              <button className="eng-btn" disabled={!port} onClick={() => call('/api/attack/tx/connect', { port, baud: 115200 }, 'Transmitter connected')}>Connect</button>
            </div>
          )}
          {st?.connected && (
            <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
              <input className="eng-input" style={{ width: 200 }} value={manual} onChange={(e) => setManual(e.target.value)} />
              <button className="eng-btn" onClick={() => call('/api/attack/tx/command', { command: manual }, 'sent')}>Send</button>
              {['PRESS', 'AUTO 0', 'PROFILE 1', 'PROFILE 2', 'PROFILE 3'].map((c) => (
                <button key={c} className="eng-btn" onClick={() => call('/api/attack/tx/command', { command: c }, 'sent')}>{c}</button>
              ))}
            </div>
          )}
          {st?.connected && (
            <pre className="code-block" style={{ maxHeight: 140, overflow: 'auto', marginTop: 8 }}>
              {st.log.slice(-12).map((l) => JSON.stringify(l)).join('\n')}
            </pre>
          )}
        </div>
      </Panel>

      {st?.simulation && (
        <Panel title="Virtual transmitters (simulator)">
          <table className="eng-table">
            <thead><tr><th>name</th><th>type</th><th>code</th><th>true T (µs)</th><th /></tr></thead>
            <tbody>
              {st.sim_devices.map((s) => (
                <tr key={s.name}>
                  <td>{s.name}</td><td>{s.kind === 'crystal_clone' ? <Badge tone="danger">ESP32 clone</Badge> : s.kind === 'emulated' ? 'ESP32 node (profile)' : 'RC-oscillator fob'}</td>
                  <td><code>{s.code}</code></td><td>{s.clock_t_us.toFixed(3)}</td>
                  <td><button className="eng-btn" onClick={() => call('/api/hardware/sim/press', { name: s.name }, 'pressed')}>Press</button></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="hint">Mirrors the real kit: one fob and one ESP32 + STX882 node that plays EMU_1..3 and the clone. The clone copies the victim&apos;s code and clock period to 0.01 µs.</p>
        </Panel>
      )}

      <Panel title="Recent decisions">
        <table className="eng-table">
          <thead><tr><th>time</th><th>verdict</th><th>claimed</th><th>score</th>{st?.simulation && <th>pressed</th>}</tr></thead>
          <tbody>
            {decisions.slice(0, 15).map((d, i) => (
              <tr key={i}>
                <td>{timeOf(d.time)}</td>
                <td><Badge tone={verdictTone(d.verdict)}>{VERDICT_TEXT[d.verdict]}</Badge></td>
                <td>{d.claimed}</td><td>{num(d.score)}</td>
                {st?.simulation && <td>{d.sim_source}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}
