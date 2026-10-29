'use client';

import React from 'react';

export type Notify = (msg: string, level?: 'info' | 'success' | 'warning' | 'danger') => void;

export function Panel({ title, sub, right, children, style, flush, className }: {
  title: string; sub?: React.ReactNode; right?: React.ReactNode; children: React.ReactNode;
  style?: React.CSSProperties; flush?: boolean; className?: string;
}) {
  return (
    <section className={`eng-panel ${className ?? ''}`} style={style}>
      <div className="panel-header">
        <div>
          <h2 className="panel-title">{title}</h2>
          {sub && <div className="panel-sub">{sub}</div>}
        </div>
        {right && <div className="panel-toolbar">{right}</div>}
      </div>
      <div className={`panel-content ${flush ? 'flush' : ''}`}>{children}</div>
    </section>
  );
}

export function PageHead({ title, sub, actions }: { title: string; sub?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1 className="page-title">{title}</h1>
        {sub && <p className="page-sub">{sub}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

export function Kpi({ label, value, hint, tone, big }: { label: string; value: React.ReactNode; hint?: string; tone?: 'ok' | 'bad' | 'warn'; big?: boolean }) {
  const color = tone === 'ok' ? 'var(--accent)' : tone === 'bad' ? 'var(--danger)' : tone === 'warn' ? 'var(--warning)' : 'var(--text-primary)';
  return (
    <div className={`kpi ${big ? 'big' : ''}`} title={hint}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value" style={{ color }}>{value}</div>
    </div>
  );
}

export function Badge({ tone, children }: { tone: 'success' | 'danger' | 'warning' | 'idle' | 'info'; children: React.ReactNode }) {
  return <span className={`eng-badge eng-badge-${tone}`}>{children}</span>;
}

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="field">
      <span className="eng-label">{label}</span>
      {children}
    </label>
  );
}

export const pct = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? '—' : `${(v * 100).toFixed(d)}%`);
export const num = (v: number | null | undefined, d = 2) => (v === null || v === undefined || Number.isNaN(v) ? '—' : v.toFixed(d));

export function verdictTone(v: string | undefined): 'success' | 'danger' | 'warning' | 'idle' {
  if (v === 'AUTHENTIC') return 'success';
  if (v === 'SPOOF_SUSPECTED') return 'danger';
  if (v === 'UNKNOWN_DEVICE') return 'warning';
  return 'idle';
}

export const VERDICT_TEXT: Record<string, string> = {
  AUTHENTIC: 'Authentic',
  SPOOF_SUSPECTED: 'Spoof suspected',
  UNKNOWN_DEVICE: 'Unknown device',
};

export function timeOf(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString();
}
