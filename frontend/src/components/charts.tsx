'use client';

import React from 'react';
import type { FrameEvent } from '../lib/api';

// ---------------------------------------------------------------------------
// Shared palette
// ---------------------------------------------------------------------------
const SERIES = ['#00BCD4', '#FFB74D', '#BA68C8', '#81C784', '#F06292', '#4FC3F7', '#DCE775', '#A1887F'];
const AXIS = '#3a4250';
const LABEL = '#8B949E';
export const OK = '#00E676';
export const BAD = '#FF5252';
export const WARN = '#FFC107';

const colorCache = new Map<string, string>();
export function deviceColor(name: string | null | undefined): string {
  if (!name) return LABEL;
  if (!colorCache.has(name)) colorCache.set(name, SERIES[colorCache.size % SERIES.length]);
  return colorCache.get(name)!;
}

function Empty({ h, text }: { h: number; text: string }) {
  return (
    <div style={{ height: h, display: 'flex', alignItems: 'center', justifyContent: 'center', color: LABEL, fontSize: 12, fontFamily: 'var(--font-mono)' }}>
      {text}
    </div>
  );
}

const fmt = (v: number | null | undefined, d = 2) => (v === null || v === undefined || Number.isNaN(v) ? '—' : v.toFixed(d));

// ---------------------------------------------------------------------------
// Logic-analyser view of one frame
// ---------------------------------------------------------------------------
export function LogicTrace({ frame, height = 120 }: { frame: FrameEvent | null; height?: number }) {
  if (!frame || !frame.pulses_us.length) return <Empty h={height} text="Waiting for a frame…" />;
  const W = 900, H = height, padL = 8, padR = 8, top = 18, bot = H - 26;
  const total = frame.pulses_us.reduce((a, b) => a + b, 0);
  const sx = (W - padL - padR) / total;
  let x = padL;
  const segs: React.ReactElement[] = [];
  let d = `M ${padL} ${bot}`;
  frame.pulses_us.forEach((w, i) => {
    const high = i % 2 === 0;
    const y = high ? top : bot;
    d += ` L ${x} ${y} L ${x + w * sx} ${y}`;
    const r = frame.residuals[i];
    if (high && r !== undefined && Math.abs(r) > 0.02) {
      segs.push(<rect key={i} x={x} y={top} width={Math.max(1, w * sx)} height={bot - top} fill={r > 0 ? OK : BAD} opacity={Math.min(0.35, Math.abs(r))} />);
    }
    x += w * sx;
  });
  d += ` L ${x} ${bot}`;
  const T = frame.clock_t_us;
  const ticks: React.ReactElement[] = [];
  if (T) {
    const n = Math.floor(total / T);
    const step = Math.max(1, Math.ceil(n / 60));
    for (let k = 0; k <= n; k += step) {
      ticks.push(<line key={k} x1={padL + k * T * sx} x2={padL + k * T * sx} y1={bot + 2} y2={bot + 6} stroke={AXIS} />);
    }
  }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none" role="img" aria-label="Pulse train of the last frame">
      {segs}
      <path d={d} fill="none" stroke="#00BCD4" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
      {ticks}
      <text x={padL} y={12} fill={LABEL} fontSize={11} fontFamily="var(--font-mono)">
        {frame.n} pulses · {(total / 1000).toFixed(2)} ms · T = {fmt(T, 3)} µs · grid = 1T
      </text>
      <text x={W - padR} y={H - 6} fill={LABEL} fontSize={10} textAnchor="end" fontFamily="var(--font-mono)">
        shading: HIGH stretched (green) / shrunk (red) vs n·T
      </text>
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Per-pulse residual bars (w - nT)/T
// ---------------------------------------------------------------------------
export function ResidualBars({ frame, height = 140 }: { frame: FrameEvent | null; height?: number }) {
  if (!frame || !frame.ok) return <Empty h={height} text={frame ? `Frame rejected: ${frame.quality}` : 'Waiting for a frame…'} />;
  const r = frame.residuals;
  const W = 900, H = height, pad = 30, mid = H / 2;
  const maxAbs = Math.max(0.05, ...r.map((v) => Math.abs(v)));
  const bw = (W - pad) / r.length;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none" role="img" aria-label="Timing residual per pulse">
      <line x1={pad} x2={W} y1={mid} y2={mid} stroke={AXIS} />
      <text x={2} y={14} fill={LABEL} fontSize={10} fontFamily="var(--font-mono)">+{(maxAbs * 100).toFixed(0)}%T</text>
      <text x={2} y={H - 4} fill={LABEL} fontSize={10} fontFamily="var(--font-mono)">−{(maxAbs * 100).toFixed(0)}%T</text>
      {r.map((v, i) => {
        const h = (Math.abs(v) / maxAbs) * (mid - 6);
        return (
          <rect key={i} x={pad + i * bw + 1} width={Math.max(1, bw - 2)} y={v >= 0 ? mid - h : mid} height={h}
            fill={i % 2 === 0 ? '#00BCD4' : '#FFB74D'}>
            <title>{`pulse ${i} ${i % 2 === 0 ? 'HIGH' : 'LOW'} n=${frame.units[i]} residual=${(v * 100).toFixed(2)}% of T`}</title>
          </rect>
        );
      })}
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Pulse-width histogram (recent frames)
// ---------------------------------------------------------------------------
export function WidthHistogram({ frames, height = 180 }: { frames: FrameEvent[]; height?: number }) {
  const widths: number[] = [];
  const Ts: number[] = [];
  frames.forEach((f) => {
    f.pulses_us.forEach((w) => widths.push(w));
    if (f.ok && f.clock_t_us) Ts.push(f.clock_t_us);
  });
  if (!widths.length) return <Empty h={height} text="No pulses yet" />;
  const maxUs = Math.min(2500, Math.max(...widths));
  const bins = 100;
  const bw = maxUs / bins;
  const counts = new Array(bins).fill(0);
  widths.forEach((w) => {
    if (w <= maxUs) counts[Math.min(bins - 1, Math.floor(w / bw))]++;
  });
  const cmax = Math.max(...counts);
  const W = 900, H = height, pad = 24;
  const T = Ts.length ? Ts.slice().sort((a, b) => a - b)[Math.floor(Ts.length / 2)] : null;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none" role="img" aria-label="Pulse width histogram">
      {counts.map((c, i) => {
        const h = (Math.sqrt(c) / Math.sqrt(cmax)) * (H - pad - 10);
        return <rect key={i} x={(i / bins) * W} width={W / bins - 1} y={H - pad - h} height={h} fill="#00BCD4" opacity={0.85} />;
      })}
      {T && [1, 2, 3, 4].map((k) => k * T <= maxUs && (
        <g key={k}>
          <line x1={(k * T / maxUs) * W} x2={(k * T / maxUs) * W} y1={4} y2={H - pad} stroke={WARN} strokeDasharray="4 4" />
          <text x={(k * T / maxUs) * W + 3} y={14} fill={WARN} fontSize={11} fontFamily="var(--font-mono)">{k}T</text>
        </g>
      ))}
      {[0, 0.25, 0.5, 0.75, 1].map((f) => (
        <text key={f} x={f * W} y={H - 6} fill={LABEL} fontSize={10} textAnchor={f === 1 ? 'end' : f === 0 ? 'start' : 'middle'} fontFamily="var(--font-mono)">{Math.round(f * maxUs)} µs</text>
      ))}
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Clock period trend per decoded code
// ---------------------------------------------------------------------------
export function ClockTrend({ frames, labelOf, height = 200 }: { frames: FrameEvent[]; labelOf: (code: string) => string; height?: number }) {
  const pts = frames.filter((f) => f.ok && f.clock_t_us);
  if (pts.length < 2) return <Empty h={height} text="Need decoded frames" />;
  const W = 900, H = height, padL = 56, padB = 22;
  const ys = pts.map((p) => p.clock_t_us!);
  let lo = Math.min(...ys), hi = Math.max(...ys);
  const span = Math.max(hi - lo, 0.5);
  lo -= span * 0.1; hi += span * 0.1;
  const x = (i: number) => padL + (i / (pts.length - 1)) * (W - padL - 8);
  const y = (v: number) => 8 + (1 - (v - lo) / (hi - lo)) * (H - padB - 8);
  const codes = Array.from(new Set(pts.map((p) => p.code)));
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none" role="img" aria-label="Estimated clock period per frame">
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={padL} x2={W} y1={y(lo + f * (hi - lo))} y2={y(lo + f * (hi - lo))} stroke="#222831" />
            <text x={padL - 4} y={y(lo + f * (hi - lo)) + 3} fill={LABEL} fontSize={10} textAnchor="end" fontFamily="var(--font-mono)">{(lo + f * (hi - lo)).toFixed(1)}</text>
          </g>
        ))}
        {pts.map((p, i) => (
          <circle key={i} cx={x(i)} cy={y(p.clock_t_us!)} r={3} fill={deviceColor(labelOf(p.code))}>
            <title>{`${labelOf(p.code)}  T=${p.clock_t_us!.toFixed(3)} µs`}</title>
          </circle>
        ))}
        <text x={4} y={14} fill={LABEL} fontSize={10} fontFamily="var(--font-mono)">T (µs)</text>
      </svg>
      <Legend items={codes.map((c) => labelOf(c))} />
    </div>
  );
}

export function Legend({ items }: { items: string[] }) {
  const uniq = Array.from(new Set(items));
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, fontSize: 11, fontFamily: 'var(--font-mono)', color: LABEL, marginTop: 4 }}>
      {uniq.map((n) => (
        <span key={n} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 9, height: 9, background: deviceColor(n), display: 'inline-block' }} />{n}
        </span>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Score meter: distance / threshold (<= 1 accepts)
// ---------------------------------------------------------------------------
export function ScoreMeter({ score }: { score: number | null | undefined }) {
  const W = 300, H = 34, max = 3;
  const s = score ?? 0;
  const pos = (Math.min(s, max) / max) * W;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" aria-label={`Score ${fmt(score)} of threshold`}>
      <rect x={0} y={8} width={W / max} height={10} fill={OK} opacity={0.25} />
      <rect x={W / max} y={8} width={W - W / max} height={10} fill={BAD} opacity={0.18} />
      <line x1={W / max} x2={W / max} y1={2} y2={24} stroke={WARN} strokeWidth={2} />
      {score !== null && score !== undefined && <rect x={Math.max(0, pos - 2)} y={4} width={4} height={18} fill="#F3F4F6" />}
      <text x={0} y={33} fill={LABEL} fontSize={9} fontFamily="var(--font-mono)">0</text>
      <text x={W / max} y={33} fill={WARN} fontSize={9} textAnchor="middle" fontFamily="var(--font-mono)">threshold</text>
      <text x={W} y={33} fill={LABEL} fontSize={9} textAnchor="end" fontFamily="var(--font-mono)">≥{max}×</text>
    </svg>
  );
}

// ---------------------------------------------------------------------------
// ROC (FAR vs TAR), log-x
// ---------------------------------------------------------------------------
export function RocChart({ series, height = 260 }: { series: { name: string; roc: [number, number][]; color: string }[]; height?: number }) {
  const W = 420, H = height, padL = 40, padB = 30;
  const minFar = 1e-4;
  const x = (far: number) => padL + ((Math.log10(Math.max(far, minFar)) - Math.log10(minFar)) / -Math.log10(minFar)) * (W - padL - 8);
  const y = (tar: number) => 8 + (1 - tar) * (H - padB - 8);
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" aria-label="ROC curves">
        {[1e-4, 1e-3, 1e-2, 1e-1, 1].map((f) => (
          <g key={f}>
            <line x1={x(f)} x2={x(f)} y1={8} y2={H - padB} stroke="#222831" />
            <text x={x(f)} y={H - padB + 14} fill={LABEL} fontSize={10} textAnchor="middle" fontFamily="var(--font-mono)">{f >= 0.01 ? `${f * 100}%` : `${(f * 100).toFixed(f < 1e-3 ? 2 : 1)}%`}</text>
          </g>
        ))}
        {[0, 0.5, 0.9, 1].map((t) => (
          <g key={t}>
            <line x1={padL} x2={W - 8} y1={y(t)} y2={y(t)} stroke="#222831" />
            <text x={padL - 4} y={y(t) + 3} fill={LABEL} fontSize={10} textAnchor="end" fontFamily="var(--font-mono)">{t * 100}%</text>
          </g>
        ))}
        {series.map((s) => (
          <polyline key={s.name} fill="none" stroke={s.color} strokeWidth={2}
            points={s.roc.map(([f, t]) => `${x(f)},${y(t)}`).join(' ')} />
        ))}
        <text x={(W + padL) / 2} y={H - 2} fill={LABEL} fontSize={10} textAnchor="middle" fontFamily="var(--font-mono)">false accept rate (log)</text>
        <text x={10} y={(H - padB) / 2} fill={LABEL} fontSize={10} transform={`rotate(-90 10 ${(H - padB) / 2})`} textAnchor="middle" fontFamily="var(--font-mono)">true accept rate</text>
      </svg>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', fontSize: 11, fontFamily: 'var(--font-mono)', color: LABEL }}>
        {series.map((s) => (
          <span key={s.name} style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
            <span style={{ width: 14, height: 2, background: s.color, display: 'inline-block' }} />{s.name}
          </span>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Confusion matrix
// ---------------------------------------------------------------------------
export function ConfusionMatrix({ labels, matrix }: { labels: string[]; matrix: number[][] }) {
  if (!labels.length) return <Empty h={80} text="No test data" />;
  const rowSums = matrix.map((r) => r.reduce((a, b) => a + b, 0) || 1);
  return (
    <table className="eng-table" style={{ width: 'auto' }}>
      <thead>
        <tr>
          <th>true ↓ / pred →</th>
          {labels.map((l) => <th key={l} style={{ textAlign: 'center' }}>{l}</th>)}
        </tr>
      </thead>
      <tbody>
        {matrix.map((row, i) => (
          <tr key={labels[i]}>
            <td style={{ fontWeight: 600 }}>{labels[i]}</td>
            {row.map((v, j) => {
              const frac = v / rowSums[i];
              return (
                <td key={j} style={{ textAlign: 'center', fontFamily: 'var(--font-mono)', background: `rgba(${i === j ? '0,230,118' : '255,82,82'},${Math.min(0.6, frac * 0.7)})` }}>
                  {v}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ---------------------------------------------------------------------------
// 2-D embedding map (PCA)
// ---------------------------------------------------------------------------
export function EmbeddingMap({ points, height = 320 }: { points: { x: number; y: number; device: string; enrolled: boolean }[]; height?: number }) {
  if (!points.length) return <Empty h={height} text="No embeddings" />;
  const xs = points.map((p) => p.x), ys = points.map((p) => p.y);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const W = 520, H = height, pad = 12;
  const sx = (v: number) => pad + ((v - x0) / (x1 - x0 || 1)) * (W - 2 * pad);
  const sy = (v: number) => pad + (1 - (v - y0) / (y1 - y0 || 1)) * (H - 2 * pad);
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" aria-label="Embedding space, first two principal components">
        <rect x={0} y={0} width={W} height={H} fill="#0a0e14" />
        {points.map((p, i) => p.enrolled
          ? <circle key={i} cx={sx(p.x)} cy={sy(p.y)} r={2.6} fill={deviceColor(p.device)} opacity={0.75} />
          : <path key={i} d={`M ${sx(p.x) - 3} ${sy(p.y) - 3} L ${sx(p.x) + 3} ${sy(p.y) + 3} M ${sx(p.x) - 3} ${sy(p.y) + 3} L ${sx(p.x) + 3} ${sy(p.y) - 3}`} stroke={deviceColor(p.device)} strokeWidth={1.4} />)}
      </svg>
      <Legend items={points.map((p) => p.device + (p.enrolled ? '' : ' ✕ (not enrolled)'))} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Horizontal bars (feature importance)
// ---------------------------------------------------------------------------
export function HBarList({ items, format = (v: number) => v.toFixed(3) }: { items: { label: string; value: number }[]; format?: (v: number) => string }) {
  const max = Math.max(1e-9, ...items.map((i) => Math.abs(i.value)));
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {items.map((it) => (
        <div key={it.label} style={{ display: 'grid', gridTemplateColumns: '150px 1fr 60px', alignItems: 'center', gap: 8, fontSize: 11, fontFamily: 'var(--font-mono)' }}>
          <span style={{ color: LABEL, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{it.label}</span>
          <div style={{ background: '#161B22', height: 10 }}>
            <div style={{ width: `${(Math.max(0, it.value) / max) * 100}%`, height: '100%', background: '#00BCD4' }} />
          </div>
          <span style={{ textAlign: 'right' }}>{format(it.value)}</span>
        </div>
      ))}
    </div>
  );
}
