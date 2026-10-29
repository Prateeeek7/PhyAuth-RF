'use client';

import React, { useEffect, useState } from 'react';
import { api, PortInfo } from '../../lib/api';
import { useApp } from '../shell/AppContext';
import { Badge, Field, Kpi, PageHead, Panel } from '../ui';

export function HardwareView() {
  const { live, notify } = useApp();
  const status = live.status;
  const rxStats = live.rxStats;
  const [ports, setPorts] = useState<PortInfo[]>([]);
  const [port, setPort] = useState('');
  const [baud, setBaud] = useState(921600);
  const [gap, setGap] = useState(4000);
  const [glitch, setGlitch] = useState(80);
  const rx = status?.receiver;
  const hello = rx?.hello as Record<string, string | number> | null;

  const refresh = () => api.get<PortInfo[]>('/api/hardware/ports').then((p) => {
    setPorts(p);
    const likely = p.find((x) => x.likely_esp32);
    const current = p.find((x) => x.device === status?.receiver.port);
    if (!port) setPort((current ?? likely)?.device ?? '');
  }).catch(() => undefined);
  useEffect(() => { refresh(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const call = async (p: string, body?: unknown, ok?: string) => {
    try {
      await api.post(p, body);
      if (ok) notify(ok, 'success');
    } catch (e) {
      notify(String(e), 'danger');
    }
  };

  return (
    <>
      <PageHead title="Hardware" sub="Connect the receiver, check the radio front-end and tune the firmware. Wiring: docs/HARDWARE.md." />
      <div className="cols-2 stretch">
      <Panel title="Receiver connection">
        <div className="kpi-row two" style={{ marginTop: 0 }}>
          <Kpi label="mode" value={rx?.mode ?? '—'} tone={rx?.mode === 'hardware' ? 'ok' : rx?.mode === 'simulation' ? 'warn' : 'bad'} />
          <Kpi label="port" value={rx?.port ? rx.port.replace('/dev/cu.', '') : '—'} hint={rx?.port ?? undefined} />
          <Kpi label="firmware" value={hello ? `v${hello.ver}` : '—'} hint={hello ? `${hello.fw} ${hello.ver} · ${hello.board ?? ''}` : undefined} />
          <Kpi label="last frame" value={rx?.last_frame_age_s != null ? `${rx.last_frame_age_s}s ago` : '—'} />
        </div>
        {rx?.last_error && <p style={{ color: 'var(--warning)', fontSize: 12 }}>last error: {rx.last_error}</p>}
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap', marginTop: 10 }}>
          <Field label="Serial port">
            <select className="eng-select" value={port} onChange={(e) => setPort(e.target.value)}>
              <option value="">select…</option>
              {ports.map((p) => <option key={p.device} value={p.device}>{p.device} {p.likely_esp32 ? '★' : ''} {p.description}</option>)}
            </select>
          </Field>
          <Field label="Baud">
            <select className="eng-select" value={baud} onChange={(e) => setBaud(parseInt(e.target.value))}>
              <option value={921600}>921600 (firmware v2)</option>
              <option value={460800}>460800</option>
              <option value={115200}>115200 (legacy v1)</option>
            </select>
          </Field>
          <button className="eng-btn" onClick={refresh}>Rescan</button>
          <button className="eng-btn eng-btn-primary" disabled={!port} onClick={() => call('/api/hardware/connect', { port, baud }, `Connecting ${port}`)}>Connect</button>
          <button className="eng-btn" onClick={() => call('/api/hardware/disconnect', undefined, 'Disconnected')}>Disconnect</button>
          <button className="eng-btn" onClick={() => call('/api/hardware/simulate', undefined, 'Virtual RF lab started')}>Use simulator</button>
        </div>
        <p className="hint" style={{ marginTop: 6 }}>★ = looks like a CP2102/CH340 ESP32 bridge. Opening the port resets the board; the firmware then prints a hello line.</p>
      </Panel>

      <Panel title="Receiver front-end (live)">
        <div className="kpi-row">
          <Kpi label="edges total" value={rxStats?.edges ?? '—'} />
          <Kpi label="noise edges/s" value={rxStats?.noise_eps ?? '—'} />
          <Kpi label="frames out" value={rxStats?.frames ?? '—'} />
          <Kpi label="too short" value={rxStats?.rejected ?? '—'} />
          <Kpi label="overflow" value={rxStats?.overflow ?? '—'} tone={(rxStats?.ring_overflow ?? 0) > 0 ? 'bad' : undefined} />
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap', marginTop: 10 }}>
          <Field label="Inter-frame gap (µs)"><input className="eng-input" type="number" value={gap} onChange={(e) => setGap(parseInt(e.target.value))} /></Field>
          <button className="eng-btn" onClick={() => call('/api/hardware/command', { command: `SET GAP ${gap}` }, 'gap set')}>Apply</button>
          <Field label="Glitch merge (µs)"><input className="eng-input" type="number" value={glitch} onChange={(e) => setGlitch(parseInt(e.target.value))} /></Field>
          <button className="eng-btn" onClick={() => call('/api/hardware/command', { command: `SET GLITCH ${glitch}` }, 'glitch set')}>Apply</button>
        </div>
        {hello && <div className="hint" style={{ marginTop: 6 }}>firmware: gap {hello.gap_us} µs · glitch {hello.glitch_us} µs · min pulses {hello.min_pulses} · clock {Number(hello.clk_hz) / 1e6} MHz {hello.sim ? <Badge tone="warning">SIMULATED</Badge> : null}</div>}
      </Panel>

      </div>
    </>
  );
}
