'use client';

import React from 'react';
import { FrameEvent } from '../../lib/api';
import { ClockTrend, LogicTrace, ResidualBars, WidthHistogram } from '../charts';
import { Panel, num } from '../ui';

const FEATURE_DOC: Record<string, [string, string]> = {
  clock_T_us: ['µs', 'Elementary period T from bit-pair periods (H+L)/(nH+nL). Slicer-invariant; set by the encoder’s RC oscillator, ±several % between units.'],
  pair_jitter_ppm: ['ppm', 'Cycle-to-cycle oscillator jitter. RC oscillators ≫ crystal-clocked clones.'],
  duty_short_high: ['×T', 'Mean stretch of short HIGH pulses: PA turn-on/turn-off delay asymmetry plus slicer threshold.'],
  duty_long_high: ['×T', 'Same for long HIGH pulses (PA heating during long marks).'],
  high_jitter: ['×T', 'Spread of HIGH-pulse residuals: edge timing noise.'],
  first_edge_resid: ['×T', 'Residual of the first HIGH in the frame: start-up transient.'],
  drift_ppm_per_bit: ['ppm/bit', 'Slope of bit-period error across the frame: oscillator warm-up chirp.'],
  sync_ratio: ['×T', 'Preceding sync gap ÷ T (31 for EV1527); encoder-specific.'],
  tail_high_resid: ['×T', 'Residual of the trailing sync HIGH pulse.'],
  duty_short_low: ['×T', 'Mean error of short LOW gaps.'],
  duty_long_low: ['×T', 'Mean error of long LOW gaps.'],
};

export function AnalysisView({ frames, labelOf }: { frames: FrameEvent[]; labelOf: (code: string) => string }) {
  const ok = frames.filter((f) => f.ok);
  const last = ok[ok.length - 1] ?? null;
  return (
    <div className="grid-2">
      <Panel title="Pulse-width histogram (recent frames)">
        <WidthHistogram frames={frames.slice(-60)} />
        <p className="hint">EV1527 symbols cluster at 1T and 3T. Noise between transmissions spreads everywhere; the quality gate removes it.</p>
      </Panel>
      <Panel title="Clock period per frame">
        <ClockTrend frames={ok.slice(-150)} labelOf={labelOf} />
        <p className="hint">The ESP32 timestamps edges with its 240 MHz cycle counter (4.17 ns). Different units of the same fob model separate by microseconds.</p>
      </Panel>
      <Panel title="Last decoded frame">
        <LogicTrace frame={last} />
        <ResidualBars frame={last} />
      </Panel>
      <Panel title="Physical fingerprint features (last frame)">
        {last ? (
          <table className="eng-table">
            <thead><tr><th>feature</th><th style={{ textAlign: 'right' }}>value</th><th>unit</th><th>physical meaning</th></tr></thead>
            <tbody>
              {Object.entries(last.features).map(([k, v]) => (
                <tr key={k}>
                  <td><code>{k}</code></td>
                  <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{num(v, Math.abs(v ?? 0) > 100 ? 1 : 4)}</td>
                  <td className="hint">{FEATURE_DOC[k]?.[0]}</td>
                  <td className="hint">{FEATURE_DOC[k]?.[1]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="hint">No decoded frame yet</p>}
        <p className="hint" style={{ marginTop: 8 }}>
          None of these depend on <i>which</i> bits were sent. A clone replaying the right code still cannot reproduce them, so the model cannot cheat by learning the payload.
        </p>
      </Panel>
    </div>
  );
}
