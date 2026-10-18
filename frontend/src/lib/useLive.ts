'use client';

import { useEffect, useRef, useState } from 'react';
import { API_BASE, Decision, FrameEvent, HubStatus, RecordingStatus, TrainingState, WS_URL, api } from './api';

export interface LiveState {
  connected: boolean;
  status: HubStatus | null;
  frames: FrameEvent[];
  decisions: Decision[];
  rxStats: Record<string, number> | null;
  recording: RecordingStatus | null;
  training: TrainingState | null;
}

const MAX_FRAMES = 200;
const MAX_DECISIONS = 100;

/** One shared WebSocket to the backend hub with auto-reconnect. */
export function useLive(): LiveState {
  const [state, setState] = useState<LiveState>({
    connected: false, status: null, frames: [], decisions: [], rxStats: null, recording: null, training: null,
  });
  const pending = useRef<FrameEvent[]>([]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let closed = false;

    // Seed buffers after a page reload
    api.get<{ frames: FrameEvent[]; decisions: Decision[] }>('/api/events/live')
      .then((d) => setState((s) => ({ ...s, frames: d.frames.slice(-MAX_FRAMES), decisions: d.decisions })))
      .catch(() => undefined);

    // Batch frame events (a key press produces ~25 frames/s)
    const flush = setInterval(() => {
      if (!pending.current.length) return;
      const batch = pending.current;
      pending.current = [];
      setState((s) => ({ ...s, frames: [...s.frames, ...batch].slice(-MAX_FRAMES) }));
    }, 150);

    const connect = () => {
      ws = new WebSocket(WS_URL);
      ws.onopen = () => setState((s) => ({ ...s, connected: true }));
      ws.onclose = () => {
        setState((s) => ({ ...s, connected: false }));
        if (!closed) timer = setTimeout(connect, 2000);
      };
      ws.onerror = () => ws?.close();
      ws.onmessage = (ev) => {
        let msg: { type: string } & Record<string, unknown>;
        try {
          msg = JSON.parse(ev.data);
        } catch {
          return;
        }
        switch (msg.type) {
          case 'frame':
            pending.current.push(msg as unknown as FrameEvent);
            break;
          case 'decision':
            setState((s) => ({ ...s, decisions: [msg as unknown as Decision, ...s.decisions].slice(0, MAX_DECISIONS) }));
            break;
          case 'status':
            setState((s) => ({ ...s, status: msg as unknown as HubStatus, recording: (msg as unknown as HubStatus).recording ?? s.recording, training: (msg as unknown as HubStatus).training }));
            break;
          case 'rx_stats':
            setState((s) => ({ ...s, rxStats: msg as unknown as Record<string, number> }));
            break;
          case 'recording':
            setState((s) => ({ ...s, recording: msg as unknown as RecordingStatus }));
            break;
          case 'training':
            setState((s) => ({ ...s, training: msg as unknown as TrainingState }));
            break;
        }
      };
    };
    connect();
    return () => {
      closed = true;
      clearInterval(flush);
      if (timer) clearTimeout(timer);
      ws?.close();
    };
  }, []);

  return state;
}

export { API_BASE };
