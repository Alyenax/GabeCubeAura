import type {Status} from './types';
import {translate} from './i18n';

/** One presentation order for Settings and QAM; Off remains a power action. */
const SHARED_FACEPLATE_OPTIONS = [
  {data:'artwork',label:'Artwork'},
  {data:'artwork-dashboard',label:'Dashboard Artwork'},
  {data:'weather',label:'Weather'},
  {data:'dashboard',label:'Dashboard Weather'},
];
export const FACEPLATE_HOME_OPTIONS = [
  ...SHARED_FACEPLATE_OPTIONS,
  {data:'native-clock',label:'Native Clock (24h)'},
];
export const FACEPLATE_GAME_OPTIONS = [
  {data:'player-city',label:'Steam Players City'},
  ...SHARED_FACEPLATE_OPTIONS,
];
export function homeFaceChoice(status:Status) {
  const route=status.faceplate.routing.routes.home;
  // Preserve existing assignments until the user explicitly selects a new route.
  return route==='dashboard'&&status.faceplate_dashboard_home_source==='artwork'?'artwork-dashboard':route;
}
export function isDashboardChoice(value:string) { return value==='dashboard'||value==='artwork-dashboard'; }
export function quickFaceOptions(game:boolean,french=false) {
  return [...(game?FACEPLATE_GAME_OPTIONS:FACEPLATE_HOME_OPTIONS),{data:'off',label:french?'Éteint':'Off'}]
    .map(option=>({...option,label:translate(option.label,french?'fr':'en')}));
}

/** Guidance until this route is ready; a transfer receipt is not a library scan. */
export function showArtworkPreparationHint(status:Status) {
  const p=status.faceplate,r=p.routing,game=status.game.appid>0;
  if(!p.available||p.powered===false||!r?.routes)return false;
  const choice=game?r.routes.game:homeFaceChoice(status);
  if(choice!=='artwork'&&choice!=='artwork-dashboard')return false;
  const expected=game?r.routes.game:r.routes.home;
  const ready=(game||p.home_artwork_prepared===true)&&r.preparation?.state==='ready'&&
    r.desired_scene===expected&&r.effective_scene===expected&&Boolean(r.desired_content_key)&&
    r.effective_content_key===r.desired_content_key;
  return !ready;
}
