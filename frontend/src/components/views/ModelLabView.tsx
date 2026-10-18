'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { api, HubStatus, ModelInfo, Report, TrainingState } from '../../lib/api';
import { ConfusionMatrix, EmbeddingMap, HBarList, RocChart } from '../charts';
import { Badge, Field, Kpi, Notify, Panel, num, pct } from '../ui';

const MODEL_NAME: Record<string, string> = { edge: 'EdgeMLP (physical features, on-chip)', fusion: 'FingerprintNet (1D-ResNet ⊕ features)' };

export function ModelLabView({ status, training, notify }: { status: HubStatus | null; training: TrainingState | null; notify: Notify }) {
  const [report, setReport] = useState<Report | null>(null);
  const [info, setInfo] = useState<ModelInfo | null>(null);
  const [epochs, setEpochs] = useState(60);
  const [view, setView] = useState<'edge' | 'fusion'>('edge');

  const reload = useCallback(() => {
    api.get<Report>('/api/models/report').then(setReport).catch(() => setReport(null));
    api.get<ModelInfo>('/api/models/info').then(setInfo).catch(() => undefined);
  }, []);
  useEffect(() => { reload(); }, [reload]);
  useEffect(() => {
    if (training?.status === 'COMPLETED' || training?.status === 'FAILED') reload();
    if (training?.status === 'FAILED') notify(`Training failed: ${training.error}`, 'danger');
  }, [training?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const train = async () => {
    try {
      await api.post('/api/models/train', { epochs });
      notify('Training started', 'info');
    } catch (e) {
      notify(String(e), 'danger');
    }
  };
  const setRuntime = async (body: Record<string, unknown>) => {
    try {
      setInfo(await api.post<ModelInfo>('/api/models/runtime', body));
    } catch (e) {
      notify(String(e), 'danger');
    }
  };

  const t = training ?? status?.training;
  const running = t?.status === 'RUNNING';
  const m = report?.models[view];

  return (
    <div className="grid-2">
      <Panel title="Train">
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <Field label="Max epochs (early stopping)">
            <input className="eng-input" type="number" min={5} max={500} value={epochs} onChange={(e) => setEpochs(parseInt(e.target.value))} />
          </Field>
          <button className="eng-btn eng-btn-primary" disabled={running} onClick={train}>{running ? 'Training…' : 'Train both models'}</button>
        </div>
        {t && t.status !== 'IDLE' && (
          <div style={{ marginTop: 10 }}>
            <div className="hint">
              <Badge tone={t.status === 'COMPLETED' ? 'success' : t.status === 'FAILED' ? 'danger' : 'info'}>{t.status}</Badge>{' '}
              {t.progress.stage} {t.progress.epoch ? `epoch ${t.progress.epoch}/${t.progress.total_epochs}` : ''}
              {t.progress.val_accuracy !== undefined && ` · val acc ${pct(t.progress.val_accuracy)} · val loss ${num(t.progress.val_loss, 3)}`}
            </div>
            {running && <div className="progress"><div style={{ width: `${(100 * (t.progress.epoch ?? 0)) / (t.progress.total_epochs || 1)}%` }} /></div>}
            {t.error && <p style={{ color: 'var(--danger)', fontSize: 12 }}>{t.error}</p>}
          </div>
        )}
        <p className="hint" style={{ marginTop: 10 }}>
          Trains on every <i>enrolled</i> device in <code>data/</code>, with a burst-level split (no frame of a test button press is seen in training), cross-session when possible, and physical augmentation (slicer bias, clock drift). Loss: cross-entropy + batch-hard triplet. Thresholds are one-class and calibrated on validation only, so attacker results are zero-shot.
        </p>
        {info?.ready && (
          <div style={{ marginTop: 12, borderTop: '1px solid var(--grid-color)', paddingTop: 10 }}>
            <div className="eng-label">Runtime (live decisions)</div>
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
              <Field label="Active model">
                <select className="eng-select" value={info.active_model} onChange={(e) => setRuntime({ active_model: e.target.value })}>
                  <option value="edge">{MODEL_NAME.edge}</option>
                  <option value="fusion">{MODEL_NAME.fusion}</option>
                </select>
              </Field>
              <Field label={`Threshold scale ×${info.threshold_scale.toFixed(2)} (lower = stricter)`}>
                <input type="range" min={0.5} max={2} step={0.05} value={info.threshold_scale}
                  onChange={(e) => setRuntime({ threshold_scale: parseFloat(e.target.value) })} />
              </Field>
              <Field label="Start-up drift liveness">
                <select className="eng-select" value={info.liveness_enabled ? '1' : '0'} onChange={(e) => setRuntime({ liveness: e.target.value === '1' })}>
                  <option value="1">on</option>
                  <option value="0">off (fingerprint only)</option>
                </select>
              </Field>
            </div>
            <div className="hint">model version {info.version} · enrolled: {info.classes.join(', ')}</div>
          </div>
        )}
      </Panel>

      <Panel title="Held-out evaluation" right={report && (
        <div style={{ display: 'flex', gap: 6 }}>
          {(['edge', 'fusion'] as const).map((k) => (
            <button key={k} className={`eng-btn ${view === k ? 'eng-btn-primary' : ''}`} onClick={() => setView(k)}>{k}</button>
          ))}
        </div>
      )}>
        {!report || !m ? <p className="hint">No report yet. Train a model first.</p> : (
          <>
            {report.meta.simulated_data && <p className="warn-box">This report was produced from <b>simulated</b> recordings. Quote hardware results only from real captures.</p>}
            <div className="hint">{MODEL_NAME[view]} · {report.meta.parameters[view].toLocaleString()} parameters · split <b>{report.meta.split_strategy}</b> · test {report.meta.frames.test} frames + {report.meta.frames.impostor_test} attacker frames</div>
            <div className="kpi-row">
              <Kpi label="closed-set accuracy" value={pct(m.closed_set.accuracy)} />
              <Kpi label="EER (frame)" value={pct(m.verification.frame.eer, 2)} />
              <Kpi label="AUC (frame)" value={num(m.verification.frame.auc, 4)} />
              <Kpi label="FAR (press)" value={pct(m.verification.burst.far, 2)} tone={(m.verification.burst.far ?? 0) <= 0.01 ? 'ok' : 'bad'} />
              <Kpi label="FRR (press)" value={pct(m.verification.burst.frr, 1)} tone={(m.verification.burst.frr ?? 0) <= 0.05 ? 'ok' : 'warn'} />
              {m.verification.burst_combined_frr != null && (
                <Kpi label="FRR (press, + liveness)" value={pct(m.verification.burst_combined_frr, 1)}
                  tone={m.verification.burst_combined_frr <= 0.05 ? 'ok' : 'warn'} hint="Genuine presses rejected by fingerprint or liveness (= live engine)" />
              )}
            </div>
            <div className="eng-label" style={{ marginTop: 10 }}>Attack resistance (zero-shot, per button press)</div>
            <table className="eng-table">
              <thead><tr><th>transmitter</th><th>attack</th><th>claims</th><th>presses</th><th>rejected (fingerprint)</th><th>+ liveness</th></tr></thead>
              <tbody>
                {m.attacks.map((a) => (
                  <tr key={a.device}>
                    <td>{a.device}</td>
                    <td>{a.kind === 'code_clone' ? 'clone / replay (same code)' : 'unknown transmitter'}</td>
                    <td>{a.claimed ?? 'nearest profile'}</td>
                    <td>{a.bursts}</td>
                    <td><Badge tone={(a.rejection_rate ?? 0) >= 0.95 ? 'success' : 'danger'}>{pct(a.rejection_rate)}</Badge></td>
                    <td>{a.combined_rejection_rate == null ? '—' : <Badge tone={a.combined_rejection_rate >= 0.95 ? 'success' : 'danger'}>{pct(a.combined_rejection_rate)}</Badge>}</td>
                  </tr>
                ))}
                {!m.attacks.length && <tr><td colSpan={6} className="hint">Record the ESP32 node as CLONE_A (clone of your fob) and EMU_3 (unknown device), both not enrolled, to measure this.</td></tr>}
              </tbody>
            </table>
          </>
        )}
      </Panel>

      {report && m && (
        <>
          <Panel title="ROC — genuine vs impostor">
            <RocChart series={[
              { name: `${view} · per press`, roc: m.verification.burst.roc, color: '#00E676' },
              { name: `${view} · per frame`, roc: m.verification.frame.roc, color: '#00BCD4' },
              ...(view === 'edge' ? [{ name: 'fusion · per press', roc: report.models.fusion.verification.burst.roc, color: '#BA68C8' }] : []),
            ]} />
          </Panel>
          <Panel title="Confusion matrix (closed set, test)">
            <ConfusionMatrix labels={m.closed_set.labels} matrix={m.closed_set.confusion} />
            {m.by_distance.length > 0 && (
              <table className="eng-table" style={{ marginTop: 12 }}>
                <thead><tr><th>distance</th><th>frames</th><th>accuracy</th><th>genuine FRR (frame)</th></tr></thead>
                <tbody>
                  {m.by_distance.map((d) => (
                    <tr key={d.distance_m}><td>{d.distance_m} m</td><td>{d.frames}</td><td>{pct(d.accuracy)}</td><td>{pct(d.frr)}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>
          <Panel title="Which impairments carry identity? (permutation importance)">
            <HBarList items={report.feature_importance.map((f) => ({ label: f.feature, value: f.delta_eer ?? 0 }))} format={(v) => `+${(v * 100).toFixed(1)}%`} />
            <p className="hint" style={{ marginTop: 6 }}>Increase in frame EER when one feature is shuffled across the test set (edge model).</p>
          </Panel>
          {report.liveness && (
            <Panel title="Liveness: cold-start clock drift per press">
              <table className="eng-table">
                <thead><tr><th>device</th><th>check</th><th>learned drift</th><th>tolerance</th><th>test presses</th><th>genuine rejected</th></tr></thead>
                <tbody>
                  {Object.entries(report.liveness.profiles).map(([d, p]) => {
                    const g = report.liveness?.genuine_test[d];
                    return (
                      <tr key={d}>
                        <td>{d}</td>
                        <td>{p.active ? <Badge tone="success">active</Badge> : <Badge tone="idle">off</Badge>}<div className="hint">{p.reason}</div></td>
                        <td>{p.median_ppm != null ? `${num(p.median_ppm, 0)} ± ${num(p.sd_ppm ?? null, 0)} ppm` : '—'}</td>
                        <td>{p.active ? `± ${num(p.tolerance_ppm ?? null, 0)} ppm` : '—'}</td>
                        <td>{g?.presses ?? '—'}</td>
                        <td>{g ? g.rejected : '—'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <table className="eng-table" style={{ marginTop: 10 }}>
                <thead><tr><th>attacker</th><th>claims</th><th>measured drift</th><th>caught by liveness</th></tr></thead>
                <tbody>
                  {Object.entries(report.liveness.impostor_test).map(([d, r]) => (
                    <tr key={d}><td>{d}</td><td>{r.claimed ?? '—'}</td><td>{num(r.median_ppm, 0)} ppm</td>
                      <td>{r.rejected == null ? <span className="hint">n/a (no claimed code)</span> : `${r.rejected} / ${r.presses}`}</td></tr>
                  ))}
                </tbody>
              </table>
              <p className="hint" style={{ marginTop: 6 }}>
                A fob is unpowered until pressed, so its RC clock settles during the first frames of every press. The ESP32 node runs from an always-on crystal and does not.
                The check switches on only for devices whose own training presses show a clear drift.
              </p>
            </Panel>
          )}
          <Panel title="Embedding space (PCA of test frames)">
            <EmbeddingMap points={report.embedding_map.points} />
            <p className="hint">Dots: enrolled devices. Crosses: not-enrolled transmitters (clones, unknown fobs). {report.embedding_map.explained ? `First two components explain ${pct(report.embedding_map.explained)} of variance.` : ''}</p>
          </Panel>
        </>
      )}
    </div>
  );
}
