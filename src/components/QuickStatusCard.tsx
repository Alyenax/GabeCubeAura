import type { CSSProperties, ReactNode } from 'react';

export const QUICK_ZONES = {
  control: {accent: '#8FC9F2', background: '#223B50', focus: '#355875'},
  bar: {accent: '#71DFCE', background: '#214139', focus: '#315B51'},
  matrix: {accent: '#C6AFF3', background: '#352F48', focus: '#504565'},
} as const;

/** Decorative grouping; native Decky controls keep their navigation hierarchy. */
export function QuickZone({zone, children}: {zone: keyof typeof QUICK_ZONES; children: ReactNode}) {
  const palette = QUICK_ZONES[zone];
  return <div data-gca-quick-zone={zone} style={{
    '--gca-zone-accent': palette.accent, '--gca-zone-bg': palette.background,
    '--gca-zone-focus': palette.focus, width: '100%', boxSizing: 'border-box',
    borderLeft: `3px solid ${palette.accent}`, borderRadius: 8,
    background: palette.background, marginBottom: 14, padding: '8px 0',
  } as CSSProperties}>{children}</div>;
}

/** Decorative only: no extra gamepad focus target or global Decky CSS. */
export function QuickStatusCard({ children, tone = 'good' }: {
  children: ReactNode; tone?: 'good' | 'waiting' | 'error';
}) {
  return <div data-gca-quick-card={tone} style={{ width: '100%', boxSizing: 'border-box',
    padding: '8px 0', borderRadius: 6,
    color: tone === 'error' ? '#FFD0C7' : '#F0F5FA',
    fontSize: '.88em', lineHeight: 1.4, overflowWrap: 'anywhere' }}>
    {children}
  </div>;
}
