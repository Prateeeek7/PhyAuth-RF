'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { api, ModelInfo, Report } from '../../lib/api';
import { ConfusionMatrix, EmbeddingMap, HBarList, RocChart } from '../charts';
import { useApp } from '../shell/AppContext';
import { Badge, Field, Kpi, PageHead, Panel, num, pct } from '../ui';
import { EdgeView } from './EdgeView';

const MODEL_NAME: Record<string, string> = { edge: 'EdgeMLP (physical features, on-chip)', fusion: 'FingerprintNet (1D-ResNet ⊕ features)' };

export function ModelLabView() {
  const { live, notify, devices, online } = useApp();
  const training = live.training;
  const [report, setReport] = useState<Report | null>(null);
  const [info, setInfo] = useState<ModelInfo | null>(null);
  const [epochs, setEpochs] = useState(60);
  const [view, setView] = useState<'edge' | 'fusion'>('edge');

  const reload = useCallback(() => {
    api.get<Report>('/api/models/report').then(setReport).catch(() => setReport(null));
    api.get<ModelInfo>('/api/models/info').then(setInfo).catch(() => undefined);
  }, []);
  useEffect(() => { reload(); }, [reload, online]);
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

  const t = training ?? live.status?.training;
  const running = t?.status === 'RUNNING';
  const m = report?.models[view];
  const variants = new Set(devices.filter((d) => d.kind === 'variant').map((d) => d.device_id));

  return (
    <>
      <PageHead title="Model lab"
        sub="Train on enrolled devices, then evaluate on held-out presses. Attackers are never seen in training (zero-shot)."
        actions={<>
          <Field label="Max epochs"><input className="eng-input" style={{ width: 100 }} type="number" min={5} max={500} value={epochs} onChange={(e) => setEpochs(parseInt(e.target.value))} /></Field>
          <div style={{ alignSelf: 'flex-end' }}><button className="eng-btn eng-btn-primary lg" disabled={running} onClick={train}>{running ? 'Training…' : 'Train both models'}</button></div>
        </>} />

      {t && t.status !== 'IDLE' && t.status !== 'COMPLETED' && (
        <Panel title="Training" sub={`${t.progress.stage ?? ''} ${t.progress.epoch ? `· epoch ${t.progress.epoch}/${t.progress.total_epochs}` : ''}`}
          right={<Badge tone={t.status === 'FAILED' ? 'danger' : 'info'}>{t.status}</Badge>}>
          {running && <div className="progress"><div style={{ width: `${(100 * (t.progress.epoch ?? 0)) / (t.progress.total_epochs || 1)}%` }} /></div>}
          {t.error && <p style={{ color: 'var(--danger)' }}>{t.error}</p>}
        </Panel>
      )}

      {!report || !m ? (
        <Panel title="Held-out evaluation"><div className="empty">No report yet. Train a model first.</div></Panel>
      ) : (
        <>
          {report.meta.simulated_data && <p className="warn-box">This report was produced from <b>simulated</b> recordings. Quote hardware results only from real captures.</p>}
          <section className="eng-panel">
            <div className="panel-header">
              <div>
                <h2 className="panel-title">{MODEL_NAME[view]}</h2>
                <div className="panel-sub">{report.meta.parameters[view].toLocaleString()} parameters · split <b>{report.meta.split_strategy}</b> · test {report.meta.frames.test} frames + {report.meta.frames.impostor_test} non-enrolled frames</div>
              </div>
              <div className="panel-toolbar">
                {(['edge', 'fusion'] as const).map((k) => (
                  <button key={k} className={`eng-btn ${view === k ? 'eng-btn-primary' : ''}`} onClick={() => setView(k)}>{k === 'edge' ? 'Edge model' : 'Fusion model'}</button>
                ))}
              </div>
            </div>
            <div className="panel-content">
              <div className="kpi-row" style={{ marginTop: 0 }}>
                <Kpi big label="Closed-set accuracy" value={pct(m.closed_set.accuracy)} />
                <Kpi big label="EER (frame)" value={pct(m.verification.frame.eer, 2)} />
                <Kpi big label="AUC (frame)" value={num(m.verification.frame.auc, 4)} />
                <Kpi big label="False accept (press)" value={pct(m.verification.burst.far, 2)} tone={(m.verification.burst.far ?? 0) <= 0.01 ? 'ok' : 'warn'} />
                <Kpi big label="False reject (press)" value={pct(m.verification.burst.frr, 1)} tone={(m.verification.burst.frr ?? 0) <= 0.05 ? 'ok' : 'warn'} />
              </div>
            </div>
          </section>

          <div className="split-side-r stretch">
            <Panel title="Attack resistance" sub="Per button press, never seen in training" flush>
              <table className="eng-table">
                <thead><tr><th>Transmitter</th><th>Type</th><th>Claims</th><th className="num">Presses</th><th>Rejected</th><th>+ Liveness</th></tr></thead>
                <tbody>
                  {m.attacks.map((a) => {
                    const variant = variants.has(a.device);
                    return (
                      <tr key={a.device}>
                        <td style={{ fontWeight: 600 }}>{a.device}</td>
                        <td className="hint">{variant ? 'same remote, other button' : a.kind === 'code_clone' ? 'clone / replay (same code)' : 'unknown transmitter'}</td>
                        <td>{a.claimed ?? <span className="muted">nearest</span>}</td>
                        <td className="num">{a.bursts}</td>
                        <td>{variant
                          ? <Badge tone={(a.rejection_rate ?? 1) <= 0.05 ? 'success' : 'warning'}>accepted {pct(1 - (a.rejection_rate ?? 0))}</Badge>
                          : <Badge tone={(a.rejection_rate ?? 0) >= 0.95 ? 'success' : 'danger'}>{pct(a.rejection_rate)}</Badge>}</td>
                        <td>{variant || a.combined_rejection_rate == null ? <span className="muted">—</span>
                          : <Badge tone={a.combined_rejection_rate >= 0.95 ? 'success' : 'danger'}>{pct(a.combined_rejection_rate)}</Badge>}</td>
                      </tr>
                    );
                  })}
                  {view === 'edge' && report.variants?.map((v) => (
                    <tr key={`v-${v.device}`}>
                      <td style={{ fontWeight: 600 }}>{v.device}</td>
                      <td className="hint">same remote as {v.owner}, other button</td>
                      <td>{v.owner}</td>
                      <td className="num">{v.presses}</td>
                      <td><Badge tone={(v.acceptance_rate ?? 0) >= 0.95 ? 'success' : 'warning'}>accepted {pct(v.acceptance_rate)}</Badge></td>
                      <td><span className="muted">genuine</span></td>
                    </tr>
                  ))}
                  {!m.attacks.length && !report.variants?.length && <tr><td colSpan={6} className="empty">Record non-enrolled transmitters to measure this.</td></tr>}
                </tbody>
              </table>
            </Panel>

            <Panel title="Runtime" sub={info?.ready ? `version ${info.version}` : 'no model loaded'}>
              {info?.ready ? (
                <div className="stack" style={{ gap: 12 }}>
                  <Field label="Active model (live decisions)">
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
                  <div className="hint">Enrolled: {info.classes.join(', ')}</div>
                </div>
              ) : <div className="empty">Train a model first.</div>}
            </Panel>
          </div>

          <div className="cols-2 stretch">
            <Panel title="ROC: genuine vs impostor" sub="Log false-accept axis">
              <RocChart series={[
                { name: `${view} · per press`, roc: m.verification.burst.roc, color: '#00E676' },
                { name: `${view} · per frame`, roc: m.verification.frame.roc, color: '#22C3E6' },
                ...(view === 'edge' ? [{ name: 'fusion · per press', roc: report.models.fusion.verification.burst.roc, color: '#BA68C8' }] : []),
              ]} height={300} />
            </Panel>
            <Panel title="Confusion matrix" sub="Closed set, test frames">
              <ConfusionMatrix labels={m.closed_set.labels} matrix={m.closed_set.confusion} />
              {m.by_distance.length > 0 && (
                <table className="eng-table" style={{ marginTop: 16 }}>
                  <thead><tr><th>Distance</th><th className="num">Frames</th><th className="num">Accuracy</th><th className="num">Genuine FRR (frame)</th></tr></thead>
                  <tbody>
                    {m.by_distance.map((d) => (
                      <tr key={d.distance_m}><td>{d.distance_m} m</td><td className="num">{d.frames}</td><td className="num">{pct(d.accuracy)}</td><td className="num">{pct(d.frr)}</td></tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Panel>
          </div>

          <div className="cols-2 stretch">
            <Panel title="Which impairments carry identity?" sub="Rise in frame EER when one feature is shuffled (edge model)">
              <HBarList items={report.feature_importance.map((f) => ({ label: f.feature, value: f.delta_eer ?? 0 }))} format={(v) => `+${(v * 100).toFixed(1)}%`} />
            </Panel>
            <Panel title="Embedding space" sub={`PCA of test frames${report.embedding_map.explained ? ` · ${pct(report.embedding_map.explained)} of variance` : ''} · ✕ = not enrolled`}>
              <EmbeddingMap points={report.embedding_map.points} height={300} />
            </Panel>
          </div>

          {report.liveness && (
            <Panel title="Liveness: cold-start clock drift per press" sub="Switches on only for devices whose accept window excludes zero drift" flush>
              <table className="eng-table">
                <thead><tr><th>Device</th><th>Check</th><th className="num">Learned drift</th><th className="num">Tolerance</th><th className="num">Test presses</th><th className="num">Genuine rejected</th></tr></thead>
                <tbody>
                  {Object.entries(report.liveness.profiles).map(([d, p]) => {
                    const g = report.liveness?.genuine_test[d];
                    return (
                      <tr key={d}>
                        <td style={{ fontWeight: 600 }}>{d}</td>
                        <td>{p.active ? <Badge tone="success">active</Badge> : <Badge tone="idle">off</Badge>} <span className="hint">{p.reason}</span></td>
                        <td className="num">{p.median_ppm != null ? `${num(p.median_ppm, 0)} ± ${num(p.sd_ppm ?? null, 0)} ppm` : '—'}</td>
                        <td className="num">{p.active ? `± ${num(p.tolerance_ppm ?? null, 0)} ppm` : '—'}</td>
                        <td className="num">{g?.presses ?? '—'}</td>
                        <td className="num">{g ? g.rejected : '—'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Panel>
          )}
        </>
      )}
      <EdgeView />
    </>
  );
}
