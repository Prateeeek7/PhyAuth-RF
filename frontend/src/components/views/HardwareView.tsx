'use client';

import React, { useEffect, useState } from 'react';
import { api, HubStatus, PortInfo } from '../../lib/api';
import { Badge, Field, Kpi, Notify, Panel } from '../ui';

export function HardwareView({ status, rxStats, notify }: { status: HubStatus | null; rxStats: Record<string, number> | null; notify: Notify }) {
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
    if (likely && !port) setPort(likely.device);
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
    <div className="grid-2">
      <Panel title="Receiver connection">
        <div className="kpi-row">
          <Kpi label="mode" value={rx?.mode ?? '—'} tone={rx?.mode === 'hardware' ? 'ok' : rx?.mode === 'simulation' ? 'warn' : 'bad'} />
          <Kpi label="port" value={rx?.port ?? '—'} />
          <Kpi label="firmware" value={hello ? `${hello.fw} ${hello.ver}` : '—'} />
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

      <Panel title="Wiring" style={{ gridColumn: '1 / -1' }}>
        <div className="grid-2" style={{ padding: 0 }}>
          <pre className="code-block">{`RECEIVER  ESP32 (either board)  ←→  SRX882
  3V3  ──────────────────────────  VCC   (3.3 V only: DATA must stay 3.3 V logic)
  GND  ──────────────────────────  GND
  GPIO14 ────────────────────────  DATA
  3V3  ──────────────────────────  CS    (CS low = receiver asleep)
  ANT: spring coil or 17.3 cm wire (¼ λ @ 433.92 MHz)

  verdict on the on-board LED, no extra parts:
    ESP32    blue LED GPIO2: solid = authentic, blink = rejected
    ESP32-S3 RGB LED:  green = authentic, blinking red = rejected
  flash: pio run -e esp32dev|esp32s3 -t upload`}</pre>
          <pre className="code-block">{`TRANSMITTER / ATTACKER  ESP32 (the other board)  ←→  STX882
  5V (VIN) ──────────────────────  VCC
  GND  ──────────────────────────  GND
  GPIO4 ─────────────────────────  DATA
  ANT: spring coil or 17.3 cm wire
  BOOT button = one press · on-board LED lights while sending

Keep TX and RX ≥ 50 cm apart (the SRX882 saturates
when closer); vary 1 m … 5 m during data collection.
ESP32-S3: either USB-C port works (UART and native USB).`}</pre>
        </div>
      </Panel>
    </div>
  );
}
