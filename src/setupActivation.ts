import type {Status} from './types';
import type {SetupDraft} from './onboardingApi';

type Code='disconnected'|'blocked'|'timeout'|'unconfirmed';
class SetupActivationError extends Error {constructor(readonly code:Code){super(code);}}

/** A saved route/power intention is not a USB receipt for its content. */
export function setupDisplayConfirmed(s:Status){
  const p=s.faceplate,r=p.routing;
  const game=s.game.appid>0;
  const choice=game?r.routes.game:r.routes.home;
  const scene=!game&&choice==='dashboard'&&s.faceplate_dashboard_home_source==='artwork'?'artwork-dashboard':choice;
  return p.powered===true&&p.delivery?.state==='confirmed'&&r.preparation.state==='ready'&&
    r.desired_scene===scene&&r.effective_scene===scene&&Boolean(r.desired_content_key)&&
    r.effective_content_key===r.desired_content_key;
}

export async function finishSetupWithFaceplate(choices:Partial<SetupDraft>,deps:{
  apply:(choices:Partial<SetupDraft>)=>Promise<Status>;read:()=>Promise<Status>;
  publish:(s:Status)=>void;alive:()=>boolean;waiting:()=>void;
  now?:()=>number;pause?:(ms:number)=>Promise<void>;timeoutMs?:number;
}):Promise<Status|undefined>{
  let state=await deps.apply(choices);if(!deps.alive())return;
  deps.publish(state);
  if(choices.faceplate_requested!==true)return state;
  const now=deps.now??Date.now,deadline=now()+(deps.timeoutMs??90000);
  const pause=deps.pause??(ms=>new Promise(resolve=>setTimeout(resolve,ms)));
  while(!setupDisplayConfirmed(state)){
    if(!deps.alive())return;
    if(!state.faceplate_setup_completed||!state.faceplate.available)throw new SetupActivationError('disconnected');
    if(!state.faceplate_lab_enabled||!state.signalbar_enabled||state.current_display==='displays_off'||state.faceplate.power_recovery?.suspended)
      throw new SetupActivationError('blocked');
    if(state.faceplate.power_recovery?.route_state==='unconfirmed')throw new SetupActivationError('unconfirmed');
    if(now()>=deadline)throw new SetupActivationError('timeout');
    deps.waiting();await pause(750);if(!deps.alive())return;
    state=await deps.read();if(!deps.alive())return;deps.publish(state);
  }
  return state;
}

export function setupActivationMessage(error:unknown,fr:boolean){
  if(!(error instanceof SetupActivationError))return String(error).replace(/^Error:\s*/,'');
  const messages:Record<Code,[string,string]>={
    disconnected:['Reconnectez la Faceplate, puis validez à nouveau. Son affichage n’a pas encore été confirmé.','Reconnect the Faceplate, then confirm again. Its display has not been confirmed yet.'],
    blocked:['L’activation est suspendue ou les affichages sont désactivés. Réactivez-les, puis validez à nouveau.','Activation is suspended or displays are disabled. Enable them, then confirm again.'],
    timeout:['Les réglages sont enregistrés, mais le transfert choisi n’est pas confirmé. Le guide reste ouvert : vous pouvez réessayer.','Settings are saved, but the selected transfer is not confirmed. Setup stays open so you can retry.'],
    unconfirmed:['La Faceplate n’a pas confirmé le transfert après la reprise automatique. Vous pouvez réessayer ici.','The Faceplate did not confirm the transfer after the automatic retry. You can retry here.'],
  };
  return messages[error.code][fr?0:1];
}
