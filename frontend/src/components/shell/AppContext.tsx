'use client';

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api, Device } from '../../lib/api';
import { LiveState, useLive } from '../../lib/useLive';
import type { Notify } from '../ui';

interface Notice { id: number; msg: string; level: string }

interface AppState {
  live: LiveState;
  devices: Device[];
  reloadDevices: () => void;
  notify: Notify;
  labelOf: (code: string) => string;
  /** Increments every time the backend (re)connects: use as an effect dependency to refetch. */
  online: number;
}

const Ctx = createContext<AppState | null>(null);

export function useApp(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error('useApp outside AppProvider');
  return v;
}

/** One WebSocket, device registry and notifications shared by both workspaces. */
export function AppProvider({ children }: { children: React.ReactNode }) {
  const live = useLive();
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

  // Refetch everything that was loaded while the backend was unreachable.
  const online = live.epoch;
  useEffect(() => { reloadDevices(); }, [reloadDevices, online]);
  useEffect(() => {
    if (live.recording && live.recording.state !== 'recording') reloadDevices();
  }, [live.recording?.state]); // eslint-disable-line react-hooks/exhaustive-deps

  const labelOf = useMemo(() => {
    const m = new Map<string, string>();
    devices.filter((d) => !d.is_authorized && d.code).forEach((d) => m.set(d.code!, d.device_id));
    devices.filter((d) => d.is_authorized && d.code).forEach((d) => m.set(d.code!, d.device_id));
    return (code: string) => m.get(code) ?? code;
  }, [devices]);

  const value = useMemo(() => ({ live, devices, reloadDevices, notify, labelOf, online }),
    [live, devices, reloadDevices, notify, labelOf, online]);

  return (
    <Ctx.Provider value={value}>
      {children}
      <div className="notices" role="status" aria-live="polite">
        {notices.map((n) => <div key={n.id} className={`notice notice-${n.level}`}>{n.msg}</div>)}
      </div>
    </Ctx.Provider>
  );
}
