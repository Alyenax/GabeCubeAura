import type { ReactNode } from 'react';
import { ButtonItem } from '../localized_ui';

/** One native full-width action, not a label beside a second button. */
export function QuickAction({ children, onClick, disabled=false }: { children: ReactNode; onClick: () => void; disabled?:boolean }) {
  return <ButtonItem layout="below" disabled={disabled} onClick={()=>{if(!disabled)onClick();}}>{children}</ButtonItem>;
}

/** Layout only; Steam retains its native focus ring and button states. */
export const QUICK_CONTROL_CSS = `.gca-quick-gear{min-width:0;flex-shrink:0}`;
