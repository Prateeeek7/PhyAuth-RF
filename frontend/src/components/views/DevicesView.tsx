'use client';

import React, { useState } from 'react';
import { api } from '../../lib/api';
import { useApp } from '../shell/AppContext';
import { Badge, Field, PageHead, Panel } from '../ui';

const EMPTY = { device_id: '', name: '', model_info: 'EV1527 433 MHz key fob', is_authorized: true, kind: 'fob', code: '' };

export function DevicesView() {
  const { devices, reloadDevices: reload, notify } = useApp();
  const [form, setForm] = useState(EMPTY);

  const create = async () => {
    try {
      await api.post('/api/devices', { ...form, code: form.code || null });
      setForm(EMPTY);
      reload();
      notify(`Registered ${form.device_id}`, 'success');
    } catch (e) {
      notify(String(e), 'danger');
    }
  };
  const patch = async (id: string, body: Record<string, unknown>) => {
    try {
      await api.patch(`/api/devices/${id}`, body);
      reload();
    } catch (e) {
      notify(String(e), 'danger');
    }
  };
  const remove = async (id: string) => {
    if (!confirm(`Remove ${id} from the registry? Recordings stay on disk.`)) return;
    await api.del(`/api/devices/${id}`).catch((e) => notify(String(e), 'danger'));
    reload();
  };

  return (
    <>
      <PageHead title="Devices" sub="The registry of transmitters: who is enrolled, and which code each one claims." />
      <div className="split-side">
      <Panel title="Register transmitter">
        <div className="form-grid">
          <Field label="Device ID (A-Z, 0-9, _)">
            <input className="eng-input" value={form.device_id} placeholder="FOB_A" onChange={(e) => setForm({ ...form, device_id: e.target.value.toUpperCase() })} />
          </Field>
          <Field label="Name">
            <input className="eng-input" value={form.name} placeholder="Blue key fob #1" onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <Field label="Hardware">
            <input className="eng-input" value={form.model_info} onChange={(e) => setForm({ ...form, model_info: e.target.value })} />
          </Field>
          <Field label="Type">
            <select className="eng-select" value={form.kind} onChange={(e) => {
              const kind = e.target.value;
              setForm({ ...form, kind, is_authorized: kind === 'fob' || kind === 'emulated' });
            }}>
              <option value="fob">Genuine fob</option>
              <option value="emulated">Emulated (ESP32 profile)</option>
              <option value="attacker">Attacker / clone</option>
              <option value="unknown">Unknown (unenrolled fob)</option>
              <option value="variant">Same remote, other button</option>
            </select>
          </Field>
          <Field label="Enrolled (authorized)">
            <select className="eng-select" value={form.is_authorized ? '1' : '0'} onChange={(e) => setForm({ ...form, is_authorized: e.target.value === '1' })}>
              <option value="1">yes: gets a fingerprint profile</option>
              <option value="0">no: impostor / test only</option>
            </select>
          </Field>
          <Field label="Code (optional, learned automatically)">
            <input className="eng-input" value={form.code} placeholder="e.g. 4f6d97/24" onChange={(e) => setForm({ ...form, code: e.target.value })} />
          </Field>
        </div>
        <button className="eng-btn eng-btn-primary" style={{ marginTop: 10 }} disabled={!form.device_id || !form.name} onClick={create}>Register</button>
        <p className="hint" style={{ marginTop: 8 }}>
          Lab for one remote + one ESP32/STX882 node: <b>FOB_A</b> (your 433 MHz remote, fob, enrolled) · <b>EMU_1</b>, <b>EMU_2</b> (the ESP32 node in PROFILE 1 / 2, emulated, enrolled: they give the model classes to separate) · <b>CLONE_A</b> (the ESP32 node replaying FOB_A, attacker, not enrolled) · <b>EMU_3</b> (PROFILE 3, unknown, not enrolled).
        </p>
      </Panel>

      <Panel title="Registry" sub={`${devices.length} devices`} flush>
        <div>
          <table className="eng-table">
            <thead><tr><th>ID</th><th>name</th><th>type</th><th>code (claim)</th><th>enrolled</th><th /></tr></thead>
            <tbody>
              {devices.map((d) => (
                <tr key={d.device_id}>
                  <td>{d.device_id}</td>
                  <td>{d.name}<div className="hint">{d.model_info}</div></td>
                  <td>{d.kind}</td>
                  <td>
                    <input className="eng-input" style={{ width: 120 }} defaultValue={d.code ?? ''} placeholder="learned on record"
                      onBlur={(e) => e.target.value !== (d.code ?? '') && patch(d.device_id, { code: e.target.value })} />
                  </td>
                  <td>
                    <button className="eng-btn" onClick={() => patch(d.device_id, { is_authorized: !d.is_authorized })}>
                      {d.is_authorized ? <Badge tone="success">enrolled</Badge> : <Badge tone="idle">no</Badge>}
                    </button>
                  </td>
                  <td><button className="eng-btn eng-btn-danger" onClick={() => remove(d.device_id)}>Remove</button></td>
                </tr>
              ))}
              {!devices.length && <tr><td colSpan={6} className="hint">No devices registered</td></tr>}
            </tbody>
          </table>
        </div>
        <p className="hint" style={{ padding: "10px 16px", borderTop: "1px solid var(--grid-color)" }}>Changing enrollment takes effect for profiles after the next training run.</p>
      </Panel>
      </div>
    </>
  );
}
