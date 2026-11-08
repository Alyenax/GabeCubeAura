import type {CSSProperties} from 'react';

/** Leave Steam's top bar and footer outside our fixed, internally scrolling page. */
export const STEAM_ROUTE_FRAME:CSSProperties={
  position:'fixed',top:'calc(max(56px, 3.5rem) + env(safe-area-inset-top, 0px))',
  bottom:'calc(max(96px, 6rem) + env(safe-area-inset-bottom, 0px))',left:0,right:0,
  width:'100%',height:'auto',minHeight:0,minWidth:0,boxSizing:'border-box',
  display:'flex',flexDirection:'column',overflow:'hidden',
};
