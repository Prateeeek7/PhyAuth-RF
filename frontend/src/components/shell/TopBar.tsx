'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import React from 'react';
import { useApp } from './AppContext';

function Pill({ tone, label, value, extra }: { tone: 'ok' | 'bad' | 'warn' | 'info' | 'idle'; label: string; value?: string; extra?: boolean }) {
  return (
    <span className={`pill ${tone} ${extra ? 'pill-extra' : ''}`} title={value ? `${label}: ${value}` : label}>
      <i />{label}{value && <b>{value}</b>}
    </span>
  );
}

export function TopBar() {
  const path = usePathname();
  const { live } = useApp();
  const st = live.status;
  const rx = st?.receiver;
  const lock = live.lock;
  const lockTone = lock?.state === 'UNLOCKED' ? 'ok' : lock?.state === 'LOCKED' ? 'bad' : lock?.state === 'LOCKOUT' ? 'warn' : 'idle';

  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark">RF</span>
        <span>PhyAuth-RF<small>physical-layer authentication · 433 MHz</small></span>
      </div>
      <nav className="ws-switch" aria-label="Workspace">
        <Link href="/" className={path === '/' ? 'active' : ''}>RF Fingerprinting</Link>
        <Link href="/lock" className={path?.startsWith('/lock') ? 'active' : ''}>Smart Lock</Link>
      </nav>
      <div className="status-pills">
        <Pill tone={live.connected ? 'ok' : 'bad'} label={live.connected ? 'Backend' : 'Backend offline'} />
        <Pill tone={rx?.mode === 'hardware' ? 'ok' : rx?.mode === 'simulation' ? 'warn' : 'bad'}
          label={rx?.mode === 'hardware' ? 'Receiver' : rx?.mode === 'simulation' ? 'Simulator' : 'No receiver'}
          value={rx?.mode === 'hardware' ? (rx.port ?? '').replace('/dev/cu.', '') : undefined} />
        <Pill tone={st?.model.ready ? 'info' : 'idle'} label="Model" value={st?.model.ready ? st.model.version ?? '' : 'none'} extra />
        {lock && <Pill tone={lockTone} label="Lock" value={lock.state.toLowerCase()} extra />}
      </div>
    </header>
  );
}
