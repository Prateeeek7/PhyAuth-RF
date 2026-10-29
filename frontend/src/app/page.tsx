'use client';

import React, { useEffect, useState } from 'react';
import { useApp } from '../components/shell/AppContext';
import { PageHead } from '../components/ui';
import { LiveView } from '../components/views/LiveView';
import { CaptureView } from '../components/views/CaptureView';
import { ModelLabView } from '../components/views/ModelLabView';
import { AttackView } from '../components/views/AttackView';
import { DevicesView } from '../components/views/DevicesView';
import { HardwareView } from '../components/views/HardwareView';

const NAV = [
  { group: 'Operate', items: [['live', 'Live']] },
  { group: 'Build', items: [['capture', 'Capture'], ['model', 'Model lab & deploy']] },
  { group: 'Test', items: [['attack', 'Attack lab']] },
  { group: 'Setup', items: [['devices', 'Devices'], ['hardware', 'Hardware']] },
] as const;
type View = (typeof NAV)[number]['items'][number][0];
const ICON: Record<View, string> = { live: '◉', capture: '●', model: '◆', attack: '⚠', devices: '▤', hardware: '⚙' };
const KEY = 'phyauth.view';

export default function FingerprintingWorkspace() {
  const { live, devices, notify } = useApp();
  const [view, setView] = useState<View>('live');

  useEffect(() => {
    try {
      const saved = localStorage.getItem(KEY) as View | null;
      if (saved && saved in ICON) setView(saved); // eslint-disable-line react-hooks/set-state-in-effect
    } catch { /* storage unavailable */ }
  }, []);
  const go = (v: View) => {
    setView(v);
    try { localStorage.setItem(KEY, v); } catch { /* ignore */ }
  };

  return (
    <div className="workspace">
      <aside className="sidebar" aria-label="Sections">
        {NAV.map((g) => (
          <div key={g.group}>
            <div className="nav-group-title">{g.group}</div>
            {g.items.map(([k, label]) => (
              <button key={k} className={`nav-item ${view === k ? 'active' : ''}`} onClick={() => go(k)} title={label}>
                <span aria-hidden>{ICON[k]}</span><span className="nav-label">{label}</span>
              </button>
            ))}
          </div>
        ))}
        <div className="sidebar-foot">
          {live.status?.model.ready ? <>Model {live.status.model.version}<br />{live.status.model.classes?.join(' · ')}</> : 'No model trained yet'}
        </div>
      </aside>
      <main className="content">
        {!live.connected && (
          <p className="warn-box offline-banner">
            Cannot reach the backend. Start it with <code>PHYAUTH_AUTO_SIMULATION=0 .venv/bin/python -m backend.main</code> (port 8000).
          </p>
        )}
        <div className="page">
          {view === 'live' && <LiveView />}
          {view === 'capture' && <CaptureView />}
          {view === 'model' && <ModelLabView />}
          {view === 'attack' && <>
            <PageHead title="Attack lab" sub="Test the receiver against a copy of an enrolled remote sent by the ESP32 transmitter node." />
            <AttackView devices={devices} decisions={live.decisions} notify={notify} />
          </>}
          {view === 'devices' && <DevicesView />}
          {view === 'hardware' && <HardwareView />}
        </div>
      </main>
    </div>
  );
}
