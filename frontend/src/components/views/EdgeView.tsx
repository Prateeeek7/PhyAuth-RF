'use client';

import React, { useState } from 'react';
import { API_BASE, api, Decision, HubStatus } from '../../lib/api';
import { Badge, Kpi, Notify, Panel, VERDICT_TEXT, num, timeOf, verdictTone } from '../ui';

interface ExportInfo {
  version: string;
  devices: string[];
  codes: Record<string, string>;
  parameters: number;
  flash_bytes: number;
  path: string;
  flash_command: string;
  board_env?: string;
}

export function EdgeView({ status, decisions, notify }: { status: HubStatus | null; decisions: Decision[]; notify: Notify }) {
  const [exp, setExp] = useState<ExportInfo | null>(null);
  const hello = status?.receiver.hello as Record<string, string | number> | null;
  const edgeDecisions = decisions.filter((d) => d.source === 'edge');

  const doExport = async () => {
    try {
      setExp(await api.post<ExportInfo>('/api/models/edge/export'));
      notify('Header written. Flash the receiver to deploy it.', 'success');
    } catch (e) {
      notify(String(e), 'danger');
    }
  };
  const cmd = async (c: string) => {
    try {
      await api.post('/api/hardware/command', { command: c });
      notify(`sent ${c}`, 'info');
    } catch (e) {
      notify(String(e), 'danger');
    }
  };

  return (
    <div className="grid-2">
      <Panel title="1 · Export the trained model to firmware">
        <p className="hint">
          The EdgeMLP (11 → 32 → 16), the feature scaler and each enrolled device&apos;s Mahalanobis profile and code are written as C arrays to
          <code> firmware/esp32_receiver/src/phyauth_model.h</code>. No TensorFlow toolchain is needed. Feature extraction is the same C code that
          the test-suite checks against Python (<code>tests/test_c_parity.py</code>).
        </p>
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <button className="eng-btn eng-btn-primary" disabled={!status?.model.ready} onClick={doExport}>Export header</button>
          <a className="eng-btn" href={`${API_BASE}/api/models/edge/header`} target="_blank" rel="noreferrer">View / download .h</a>
        </div>
        {exp && (
          <div style={{ marginTop: 10 }}>
            <div className="kpi-row">
              <Kpi label="model version" value={exp.version} />
              <Kpi label="parameters" value={exp.parameters} />
              <Kpi label="flash (weights + profiles)" value={`${(exp.flash_bytes / 1024).toFixed(1)} KB`} />
            </div>
            <table className="eng-table">
              <thead><tr><th>enrolled device</th><th>claim code</th></tr></thead>
              <tbody>{exp.devices.map((d) => <tr key={d}><td>{d}</td><td><code>{exp.codes[d] || '— (identify-only)'}</code></td></tr>)}</tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="2 · Flash and switch mode">
        <pre className="code-block">{`cd firmware/esp32_receiver
${exp?.flash_command?.replace('cd firmware/esp32_receiver && ', '') ?? 'pio run -e esp32dev -t upload   # ESP32-S3 receiver: -e esp32s3'}
# or Arduino IDE: open esp32_receiver.ino`}</pre>
        <div className="kpi-row">
          <Kpi label="receiver firmware" value={hello ? `${hello.fw} ${hello.ver}` : '—'} />
          <Kpi label="edge model on chip" value={hello ? (hello.edge_model ? String(hello.model) : 'none') : '—'} tone={hello?.edge_model ? 'ok' : 'warn'} />
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
          <button className="eng-btn" onClick={() => cmd('MODE BOTH')} title="Stream frames and decide on-chip">MODE BOTH</button>
          <button className="eng-btn" onClick={() => cmd('MODE EDGE')} title="Only on-chip decisions are sent">MODE EDGE</button>
          <button className="eng-btn" onClick={() => cmd('MODE STREAM')} title="Host decides; chip streams frames">MODE STREAM</button>
          <button className="eng-btn" onClick={() => cmd('TEST')} title="Blink LEDs, beep, pulse relay">TEST outputs</button>
          <button className="eng-btn" onClick={() => cmd('LIVE ON')}>LIVE ON</button>
          <button className="eng-btn" onClick={() => cmd('LIVE OFF')}>LIVE OFF</button>
          <button className="eng-btn" onClick={() => cmd('INFO')}>INFO</button>
        </div>
        <p className="hint" style={{ marginTop: 8 }}>
          On-chip decisions light the on-board LED (ESP32: solid = authentic, blinking = rejected; ESP32-S3: green / blinking red) and, if fitted, the optional LEDs, buzzer and relay. The fingerprint and the start-up drift liveness check both run on the chip (<code>LIVE ON|OFF</code>). The node keeps working with the laptop unplugged (USB power bank).
        </p>
      </Panel>

      <Panel title="On-chip decisions (from the ESP32)" style={{ gridColumn: '1 / -1' }}>
        <div className="table-scroll">
          <table className="eng-table">
            <thead><tr><th>time</th><th>verdict</th><th>device</th><th>code</th><th>score</th><th>liveness</th><th>frames</th><th>T (µs)</th><th>inference</th></tr></thead>
            <tbody>
              {edgeDecisions.map((d, i) => (
                <tr key={i}>
                  <td>{timeOf(d.time)}</td>
                  <td><Badge tone={verdictTone(d.verdict)}>{VERDICT_TEXT[d.verdict] ?? d.verdict}</Badge></td>
                  <td>{d.claimed}</td><td><code>{d.code}</code></td><td>{num(d.score)}</td><td>{d.liveness ?? 'n/a'}</td><td>{d.frames}</td>
                  <td>{num(d.clock_t_us, 3)}</td><td>{d.infer_us ? `${d.infer_us} µs` : '—'}</td>
                </tr>
              ))}
              {!edgeDecisions.length && <tr><td colSpan={9} className="hint">No on-chip decisions yet. Export, flash, then use MODE BOTH. (Not available in the simulator.)</td></tr>}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
