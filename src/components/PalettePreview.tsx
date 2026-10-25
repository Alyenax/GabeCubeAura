import type { RGB } from "../types";
import type {LedPreviewChannel} from '../led_preview';
import {useLiveLedColors} from './LiveLedPreview';

export function PalettePreview({ colors: fallback, source }: { colors?: RGB[]; source?: LedPreviewChannel }) {
  const colors = useLiveLedColors(source, fallback);
  const frame = colors && colors.length === 17 ? colors : Array.from({ length: 17 }, () => [0, 0, 0] as RGB);
  return (
    <div style={{ display: "flex", gap: 2, width: "100%", padding: "5px 0" }}>
      {frame.map(([r, g, b], index) => (
        <div key={index} style={{
          flex: 1,
          minWidth: 0,
          height: 18,
          borderRadius: 2,
          background: `rgb(${r},${g},${b})`,
          border: "1px solid rgba(255,255,255,.16)",
        }} />
      ))}
    </div>
  );
}

