import {createContext, useContext, useEffect, useState} from 'react';
import {getLedPreview} from '../api';
import {LedPreviewStream, type LedPreviewChannel} from '../led_preview';
import type {RGB} from '../types';

export const LedPreviewActivity = createContext(true);
const stream = new LedPreviewStream(getLedPreview);
let visibleUsers = 0;
const syncVisibility = () => stream.setVisible(document.visibilityState !== 'hidden');

export function useLiveLedColors(source: LedPreviewChannel | undefined, fallback: RGB[] | undefined, active = true) {
  const scopeActive = useContext(LedPreviewActivity);
  const enabled = Boolean(source && active && scopeActive);
  const [live, setLive] = useState<{source: LedPreviewChannel; frame: RGB[] | undefined} | null>(null);
  useEffect(() => {
    if (!enabled || !source) { setLive(null); return; }
    if (visibleUsers++ === 0) document.addEventListener('visibilitychange', syncVisibility);
    syncVisibility();
    const unsubscribe = stream.subscribe(source, frame => setLive({source, frame}));
    return () => {
      unsubscribe();
      if (--visibleUsers === 0) document.removeEventListener('visibilitychange', syncVisibility);
    };
  }, [source, enabled]);
  return enabled && live && live.source === source && live.frame ? live.frame : fallback;
}

export function CompactLedPreview({colors, active}: {colors: RGB[]; active: boolean}) {
  const live = useLiveLedColors('output', colors, active) ?? [];
  const frame = live.length === 17 ? live : Array.from({length: 17}, () => [0, 0, 0] as RGB);
  return <div className="gca-compact-led" role="img" aria-label="LED light bar preview">
    {frame.map((rgb, index) => <i key={index} style={{backgroundColor: `rgb(${rgb.join(',')})`}} />)}
  </div>;
}
