'use client';

import React from 'react';

/** Animated padlock: the shackle lifts when unlocked; colour follows the lock state. */
export function Padlock({ state, size = 260 }: { state: string; size?: number }) {
  const open = state === 'UNLOCKED';
  const color =
    state === 'UNLOCKED' ? 'var(--accent)'
      : state === 'LOCKOUT' ? 'var(--warning)'
        : state === 'LEARN' ? 'var(--accent-secondary)'
          : state === 'DISABLED' ? 'var(--text-faint)' : 'var(--danger)';
  return (
    <div className={open ? 'lock-glow-ok' : ''} style={{ width: size, height: size, display: 'grid', placeItems: 'center' }}>
      <svg viewBox="-20 -50 250 280" width={size * 0.9} height={size} overflow="visible" role="img" aria-label={`lock ${state.toLowerCase()}`}>
        <g style={{ transition: 'transform 0.45s cubic-bezier(.2,.9,.3,1.3)', transform: open ? 'translate(28px,-26px) rotate(18deg)' : 'none', transformOrigin: '140px 100px' }}>
          <path d="M55 100 V70 a45 45 0 0 1 90 0 V100" fill="none" stroke={color} strokeWidth="16" strokeLinecap="round" />
        </g>
        <rect x="25" y="95" width="150" height="115" rx="18" fill="var(--bg-raised)" stroke={color} strokeWidth="6" />
        <circle cx="100" cy="142" r="14" fill={color} />
        <rect x="94" y="148" width="12" height="32" rx="5" fill={color} />
        {state === 'LOCKOUT' && <text x="100" y="205" textAnchor="middle" fontSize="16" fontWeight="700" fill={color}>WAIT</text>}
      </svg>
    </div>
  );
}
