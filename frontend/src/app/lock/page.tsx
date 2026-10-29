'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { api, LockReport } from '../../lib/api';
import { Padlock } from '../../components/lock/Padlock';
import { useApp } from '../../components/shell/AppContext';
import { Badge, Field, Panel, num, timeOf } from '../../components/ui';

const KEY_NAME = (k: number) => (k === 8 ? 'ON' : k === 4 ? 'OFF' : k >= 0 ? `K${k}` : '');
const LOCKOUT_BASE_S = 30;

const EVENT: Record<string, { title: string; tone: 'ok' | 'bad' | 'warn' | 'info' | 'idle'; icon: string }> = {
  progress: { title: 'Press accepted', tone: 'info', icon: '•' },
  unlock: { title: 'Unlocked', tone: 'ok', icon: '✓' },
  lock: { title: 'Locked by pattern', tone: 'bad', icon: '🔒' },
  auto_relock: { title: 'Auto re-locked', tone: 'bad', icon: '⟲' },
  fail: { title: 'Wrong pattern', tone: 'bad', icon: '✕' },
  foreign: { title: 'Press rejected by fingerprint (attempt will fail)', tone: 'bad', icon: '!' },
  abandoned: { title: 'Unfinished attempt cleared', tone: 'idle', icon: '⌛' },
  lockout: { title: 'Too many failures: lockout', tone: 'warn', icon: '⏸' },
  lockout_end: { title: 'Lockout over', tone: 'idle', icon: '⏵' },
  ignored: { title: 'Press ignored (unclear)', tone: 'idle', icon: '·' },
  learn_step: { title: 'Learn: press recorded', tone: 'info', icon: '•' },
  learn_confirm: { title: 'Learn: now repeat it', tone: 'info', icon: '↻' },
  learned: { title: 'Pattern saved', tone: 'ok', icon: '★' },
  learn_mismatch: { title: 'Learn: did not match', tone: 'warn', icon: '↺' },
};
const TONE_BG: Record<string, string> = {
  ok: 'rgba(0,230,118,0.15)', bad: 'rgba(255,92,92,0.15)', warn: 'rgba(255,193,7,0.15)', info: 'rgba(34,195,230,0.15)', idle: 'rgba(255,255,255,0.06)',
};
const TONE_FG: Record<string, string> = {
  ok: 'var(--accent)', bad: 'var(--danger)', warn: 'var(--warning)', info: 'var(--accent-secondary)', idle: 'var(--text-secondary)',
};

export default function LockWorkspace() {
  const { live, devices, notify, online } = useApp();
  const [history, setHistory] = useState<LockReport[]>([]);
  const [seed, setSeed] = useState<LockReport | null>(null);
  const lock = live.lock ?? seed;   // last known state until the live link reports
  const [showKeys, setShowKeys] = useState(false);
  const [tlOpen, setTlOpenState] = useState(false);
  useEffect(() => {
    try { if (localStorage.getItem('phyauth.timeline') === 'open') setTlOpenState(true); } catch { /* ignore */ } // eslint-disable-line react-hooks/set-state-in-effect
  }, []);
  const setTlOpen = (v: boolean) => {
    setTlOpenState(v);
    try { localStorage.setItem('phyauth.timeline', v ? 'open' : 'closed'); } catch { /* ignore */ }
  };
  const [now, setNow] = useState(() => Date.now() / 1000);

  const reload = useCallback(() => {
    api.get<{ state: LockReport | null; events: LockReport[] }>('/api/lock/status')
      .then((r) => { setHistory(r.events); setSeed(r.state); }).catch(() => undefined);
    api.post('/api/lock/refresh').catch(() => undefined);
  }, []);
  useEffect(() => { reload(); }, [reload, online]);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() / 1000), 500);
    return () => clearInterval(t);
  }, []);

  const events = useMemo(() => {
    const seen = new Set<string>();
    return [...live.lockEvents, ...history].filter((e) => {
      const k = `${e.time}-${e.event}-${e.n}`;
      if (seen.has(k)) return false;
      seen.add(k);
      return e.event !== 'none';
    }).sort((a, b) => (b.time ?? 0) - (a.time ?? 0));
  }, [live.lockEvents, history]);

  const st = lock?.state ?? 'DISABLED';
  const len = lock?.len ?? 0;
  const n = lock?.n ?? 0;
  const lastEvent = events[0];
  const failedRecently = lastEvent && ['fail', 'lockout'].includes(lastEvent.event) && now - (lastEvent.time ?? 0) < 1.2;

  // Presses of the attempt in progress: button and whether the fingerprint rejected it
  const attempt = useMemo(() => {
    const out: { key: number; rejected: boolean }[] = [];
    for (const e of events) {
      if (e.event === 'progress' || e.event === 'learn_step' || e.event === 'foreign') out.unshift({ key: e.key, rejected: e.event === 'foreign' });
      else break;
    }
    return out.slice(-Math.max(n, 0));
  }, [events, n]);
  const attemptKeys = attempt.map((a) => a.key);

  const lastUnlock = events.find((e) => e.event === 'unlock');
  const relockLeft = st === 'UNLOCKED' && lock?.relock_s && lastUnlock?.time ? Math.max(0, lock.relock_s - (now - lastUnlock.time)) : null;
  const lastLockout = events.find((e) => e.event === 'lockout');
  const lockoutLeft = st === 'LOCKOUT' && lastLockout?.time
    ? Math.max(0, LOCKOUT_BASE_S * 2 ** Math.min(3, Math.max(0, (lastLockout.fails ?? 3) - 3)) - (now - lastLockout.time)) : null;

  const lastDecision = live.decisions[0];
  const fpOk = lastDecision ? lastDecision.verdict === 'AUTHENTIC' : null;

  const subtitle =
    st === 'LEARN' ? 'Enter your pattern on the remote, wait 4 s, then enter it again to confirm.'
      : st === 'LOCKOUT' ? `Too many failed attempts. Try again in ${num(lockoutLeft, 0)} s.`
        : st === 'UNLOCKED' ? (relockLeft != null ? `Re-locks automatically in ${num(relockLeft, 0)} s, or enter the pattern to lock now.` : 'Enter the pattern to lock again.')
          : st === 'LOCKED' ? `Enter the ${len}-press pattern on ${lock?.owner ?? 'the remote'}.`
            : 'No pattern stored yet. Set one in the panel on the right.';

  return (
    <main className="content">
      {!live.connected && <p className="warn-box offline-banner">Backend offline: start it to see the lock.</p>}
      <div className="lock-page">
        <div className="lock-main">
          <section className="eng-panel lock-stage-panel">
            <div className={`lock-stage ${failedRecently ? 'shake' : ''}`}>
              <div style={{ display: 'grid', placeItems: 'center' }}><Padlock state={st} /></div>
              <div>
                <div className={`lock-state ${st.toLowerCase()}`}>{st === 'DISABLED' ? 'NOT SET UP' : st}</div>
                <p className="page-sub" style={{ marginTop: 10, fontSize: 16 }}>{subtitle}</p>
                {len > 0 && st !== 'LEARN' && (
                  <div className="dots" aria-label={`${n} of ${len} presses`}>
                    {Array.from({ length: len }).map((_, i) => (
                      <span key={i} className={`dot-slot ${i < n ? 'filled' : ''} ${failedRecently || attempt[i]?.rejected ? 'fail' : ''}`}>
                        {showKeys && i < attemptKeys.length ? KEY_NAME(attemptKeys[i]) : ''}
                      </span>
                    ))}
                  </div>
                )}
                {st === 'LEARN' && (
                  <div className="dots">
                    {attemptKeys.map((k, i) => <span key={i} className={`key-chip ${k === 8 ? 'on' : 'off'}`}>{showKeys ? KEY_NAME(k) : '•'}</span>)}
                  </div>
                )}
                <div className="btn-row">
                  <button className="eng-btn eng-btn-danger" disabled={st !== 'UNLOCKED'} onClick={() => api.post('/api/lock/now').then(() => notify('Locked', 'info')).catch((e) => notify(String(e), 'danger'))}>Lock now</button>
                  <label className="eng-btn" style={{ cursor: 'pointer' }}>
                    <input type="checkbox" checked={showKeys} onChange={(e) => setShowKeys(e.target.checked)} style={{ marginRight: 6 }} />
                    Show buttons (demo)
                  </label>
                </div>
              </div>
            </div>
          </section>

          <div className="factor-grid">
            <div className={`factor ${fpOk == null ? '' : fpOk ? 'ok' : 'bad'}`}>
              <div className="factor-head">
                <span className="factor-title">Factor 1 · something you have</span>
                {fpOk != null && <Badge tone={fpOk ? 'success' : 'danger'}>{fpOk ? 'genuine' : 'rejected'}</Badge>}
              </div>
              <div className="factor-value">Radio fingerprint of the remote</div>
              <p className="hint" style={{ marginTop: 6 }}>
                {lastDecision
                  ? <>Last press: <b>{lastDecision.claimed ?? 'unknown'}</b> · score {num(lastDecision.score, 2)} (≤ 1 passes) · {timeOf(lastDecision.time)}</>
                  : 'Waiting for a button press.'}
              </p>
            </div>
            <div className={`factor ${st === 'UNLOCKED' ? 'ok' : (lock?.fails ?? 0) > 0 ? 'bad' : ''}`}>
              <div className="factor-head">
                <span className="factor-title">Factor 2 · something you know</span>
                <Badge tone={st === 'UNLOCKED' ? 'success' : 'idle'}>{len ? `${n}/${len}` : 'not set'}</Badge>
              </div>
              <div className="factor-value">Secret ON/OFF press pattern</div>
              <p className="hint" style={{ marginTop: 6 }}>
                {len ? <>Failed attempts: <b>{lock?.fails ?? 0}</b> of 3 before lockout · judged after all {len} presses</> : 'Set a pattern to enable the lock.'}
              </p>
            </div>
          </div>

        </div>

        <div className="lock-side">
          <section className={`eng-panel tl-panel ${tlOpen ? 'open' : ''}`}>
            <button className="tl-toggle" onClick={() => setTlOpen(!tlOpen)} aria-expanded={tlOpen}>
              <span>
                <span className="panel-title">Timeline</span>
                <span className="panel-sub" style={{ display: 'block' }}>
                  {lastEvent ? <>{(EVENT[lastEvent.event] ?? { title: lastEvent.event }).title} · {lastEvent.time ? timeOf(lastEvent.time) : ''}</> : 'No events yet'}
                </span>
              </span>
              <span className="tl-count">{events.length}<span className={`chev ${tlOpen ? 'up' : ''}`}>▾</span></span>
            </button>
            {tlOpen && (
              <div className="tl-fill">
                <div className="timeline">
                  {events.slice(0, 80).map((e, i) => {
                    const meta = EVENT[e.event] ?? { title: e.event, tone: 'idle', icon: '·' };
                    return (
                      <div key={i} className="tl-item">
                        <span className="tl-icon" style={{ background: TONE_BG[meta.tone], color: TONE_FG[meta.tone] }}>{meta.icon}</span>
                        <div>
                          <div className="tl-title">{meta.title}{showKeys && e.key >= 0 ? ` · ${KEY_NAME(e.key)}` : ''}</div>
                          <div className="tl-sub">{e.state.toLowerCase()}{e.len ? ` · ${e.n}/${e.len}` : ''}{e.fails ? ` · failures ${e.fails}` : ''}</div>
                        </div>
                        <span className="tl-time">{e.time ? timeOf(e.time) : ''}</span>
                      </div>
                    );
                  })}
                  {!events.length && <div className="empty">No lock events yet</div>}
                </div>
              </div>
            )}
          </section>
          <LockSettings owners={devices.filter((d) => d.is_authorized).map((d) => d.device_id)} current={lock} />
        </div>
      </div>
    </main>
  );
}

function LockSettings({ owners, current }: { owners: string[]; current: LockReport | null }) {
  const { notify } = useApp();
  const [owner, setOwner] = useState('');
  const [draft, setDraft] = useState<string[]>([]);
  const [relock, setRelock] = useState(15);
  const who = owner || current?.owner || owners[0] || 'FOB_A';
  const call = (p: string, body?: unknown, ok?: string) =>
    api.post(p, body).then(() => ok && notify(ok, 'info')).catch((e) => notify(String(e), 'danger'));

  return (
    <Panel title="Settings" sub="Stored in the ESP32's flash">
      <div className="stack" style={{ gap: 14 }}>
        <Field label="Owner remote">
          <select className="eng-select" value={who} onChange={(e) => setOwner(e.target.value)}>
            {owners.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </Field>
        <div>
          <div className="section-label">Teach with the remote</div>
          <button className="eng-btn eng-btn-primary" onClick={() => call('/api/lock/learn', { owner: who }, 'Learn mode: enter the pattern, wait 4 s, repeat it')}>Start learn mode</button>
        </div>
        <div>
          <div className="section-label">Or compose it here ({draft.length}/12)</div>
          <div className="dots" style={{ margin: '4px 0 8px', gap: 6 }}>
            {draft.map((k, i) => <span key={i} className={`key-chip ${k === 'ON' ? 'on' : 'off'}`}>{k}</span>)}
            {!draft.length && <span className="muted">empty</span>}
          </div>
          <div className="btn-row">
            <button className="eng-btn" disabled={draft.length >= 12} onClick={() => setDraft([...draft, 'ON'])}>+ ON</button>
            <button className="eng-btn" disabled={draft.length >= 12} onClick={() => setDraft([...draft, 'OFF'])}>+ OFF</button>
            <button className="eng-btn" disabled={!draft.length} onClick={() => setDraft(draft.slice(0, -1))}>Undo</button>
            <button className="eng-btn eng-btn-primary" disabled={draft.length < 4}
              onClick={() => call('/api/lock/set', { owner: who, keys: draft }, 'Pattern stored').then(() => setDraft([]))}>Save</button>
          </div>
        </div>
        <div>
          <Field label="Auto re-lock (s, 0 = off)">
            <input className="eng-input" type="number" min={0} max={3600} value={relock} onChange={(e) => setRelock(parseInt(e.target.value) || 0)} />
          </Field>
        </div>
        <div className="btn-row">
          <button className="eng-btn" onClick={() => call('/api/lock/relock', { seconds: relock }, 'Re-lock time set')}>Apply re-lock</button>
          <button className="eng-btn eng-btn-danger" onClick={() => confirm('Remove the stored pattern?') && call('/api/lock/clear', undefined, 'Pattern removed')}>Remove pattern</button>
        </div>
      </div>
    </Panel>
  );
}
