'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { api, Device } from '../lib/api';
import { useLive } from '../lib/useLive';
import { Badge, Notify } from '../components/ui';
import { LiveView } from '../components/views/LiveView';
import { CaptureView } from '../components/views/CaptureView';
import { AnalysisView } from '../components/views/AnalysisView';
import { ModelLabView } from '../components/views/ModelLabView';
import { EdgeView } from '../components/views/EdgeView';
import { AttackView } from '../components/views/AttackView';
import { DevicesView } from '../components/views/DevicesView';
import { HardwareView } from '../components/views/HardwareView';

const TABS = [
  ['live', 'Live'],
  ['capture', 'Capture'],
  ['analysis', 'Signal analysis'],
  ['model', 'Model lab'],
  ['edge', 'Edge deploy'],
  ['attack', 'Attack lab'],
  ['devices', 'Devices'],
  ['hardware', 'Hardware'],
] as const;
type Tab = (typeof TABS)[number][0];

interface Notice { id: number; msg: string; level: string }

export default function Home() {
  const live = useLive();
  const [tab, setTab] = useState<Tab>('live');
  const [devices, setDevices] = useState<Device[]>([]);
  const [notices, setNotices] = useState<Notice[]>([]);

  const notify: Notify = useCallback((msg, level = 'info') => {
    const id = Date.now() + Math.random();
    setNotices((n) => [...n.slice(-3), { id, msg, level }]);
    setTimeout(() => setNotices((n) => n.filter((x) => x.id !== id)), level === 'danger' ? 8000 : 4000);
  }, []);

  const reloadDevices = useCallback(() => {
    api.get<Device[]>('/api/devices').then(setDevices).catch(() => undefined);
  }, []);
  useEffect(() => { reloadDevices(); }, [reloadDevices]);
  // codes are learned when a recording finishes
  useEffect(() => {
    if (live.recording && live.recording.state !== 'recording') reloadDevices();
  }, [live.recording?.state]); // eslint-disable-line react-hooks/exhaustive-deps

  const labelOf = useMemo(() => {
    const m = new Map<string, string>();
    devices.filter((d) => !d.is_authorized && d.code).forEach((d) => m.set(d.code!, d.device_id));
    devices.filter((d) => d.is_authorized && d.code).forEach((d) => m.set(d.code!, d.device_id));
    return (code: string) => m.get(code) ?? code;
  }, [devices]);

  const st = live.status;
  const rxMode = st?.receiver.mode;

  return (
    <div className="app-layout">
      <header className="command-ribbon">
        <nav className="ribbon-tabs" aria-label="Sections">
          <span className="brand">PHYAUTH-RF</span>
          {TABS.map(([k, label]) => (
            <button key={k} className={`ribbon-tab-btn ${tab === k ? 'active' : ''}`} onClick={() => setTab(k)}>{label}</button>
          ))}
          <div className="top-status">
            <Badge tone={live.connected ? 'success' : 'danger'}>{live.connected ? 'backend online' : 'backend offline'}</Badge>
            <Badge tone={rxMode === 'hardware' ? 'success' : rxMode === 'simulation' ? 'warning' : 'danger'}>
              {rxMode === 'hardware' ? `ESP32 ${st?.receiver.port}` : rxMode === 'simulation' ? 'SIMULATOR' : 'no receiver'}
            </Badge>
            <Badge tone={st?.model.ready ? 'info' : 'idle'}>{st?.model.ready ? `model ${st.model.version} · ${st.model.active_model}` : 'no model'}</Badge>
          </div>
        </nav>
      </header>

      <main className="app-main">
        {!live.connected && (
          <p className="warn-box" style={{ margin: 12 }}>
            Cannot reach the backend at the configured API address. Start it with <code>.venv/bin/python -m backend.main</code> (port 8000).
          </p>
        )}
        {tab === 'live' && <LiveView status={st} frames={live.frames} decisions={live.decisions} rxStats={live.rxStats} devices={devices} notify={notify} />}
        {tab === 'capture' && <CaptureView status={st} devices={devices} recording={live.recording} notify={notify} />}
        {tab === 'analysis' && <AnalysisView frames={live.frames} labelOf={labelOf} />}
        {tab === 'model' && <ModelLabView status={st} training={live.training} notify={notify} />}
        {tab === 'edge' && <EdgeView status={st} decisions={live.decisions} notify={notify} />}
        {tab === 'attack' && <AttackView devices={devices} decisions={live.decisions} notify={notify} />}
        {tab === 'devices' && <DevicesView devices={devices} reload={reloadDevices} notify={notify} />}
        {tab === 'hardware' && <HardwareView status={st} rxStats={live.rxStats} notify={notify} />}
      </main>

      <div className="notices" role="status" aria-live="polite">
        {notices.map((n) => <div key={n.id} className={`notice notice-${n.level}`}>{n.msg}</div>)}
      </div>
    </div>
  );
}
