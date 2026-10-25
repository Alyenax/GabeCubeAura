import type {Status} from './types';
import type {SetupDraft} from './onboardingApi';
export type PresetPreview = Status['display_preset_preview'];
// Serialize mutations across setup lifetimes. An outgoing page's queued stop
// must finish before the next page starts; reads never hold this queue.
let writes:Promise<unknown>=Promise.resolve();
let sequence=0;
function serial<T>(work:()=>Promise<T>){const next=writes.catch(()=>undefined).then(work);writes=next.catch(()=>undefined);return next;}

export function createSetupPreview(deps:{
  start:(preset:SetupDraft['preset'],owner:string)=>Promise<Status>;
  stop:(owner:string)=>Promise<unknown>;read:()=>Promise<Status>;
  frame:(preview:PresetPreview)=>void;failed:()=>void;
  interval?:typeof setInterval;clear?:typeof clearInterval;now?:()=>number;
}){
  const now=deps.now??Date.now,owner=`setup-${now().toString(36)}-${++sequence}-${Math.random().toString(36).slice(2,10)}`;
  let alive=true,requested=false,reading=false,timer:ReturnType<typeof setInterval>|undefined,deadline=0;
  const clear=()=>{if(timer!==undefined)(deps.clear??clearInterval)(timer);timer=undefined;};
  const accept=(state:Status)=>{
    if(!alive)return;
    const preview=state.display_preset_preview;
    if(!preview?.active){clear();deps.frame({...preview,active:false,colors:[]});return;}
    if(preview.owner!==owner){clear();deps.frame({active:false,preset:'',remaining_s:0,phase:'',colors:[]});return;}
    deps.frame(preview);
  };
  const poll=async()=>{
    if(!alive||reading)return;
    if(now()>=deadline){clear();deps.frame({active:false,preset:'',remaining_s:0,phase:'',colors:[]});return;}
    reading=true;
    try{const state=await deps.read();accept(state);}catch{if(alive){clear();deps.failed();}}
    finally{reading=false;}
  };
  return {
    owner,
    start:(preset:SetupDraft['preset'])=>serial(async()=>{
      if(!alive)return;
      requested=true;deadline=now()+12000;
      try{
        const state=await deps.start(preset,owner);
        if(!alive)return;
        accept(state);
        if(state.display_preset_preview?.active&&state.display_preset_preview.owner===owner)
          timer=(deps.interval??setInterval)(()=>void poll(),250);
      }catch{if(alive)deps.failed();}
    }),
    stop:()=>{alive=false;clear();return serial(async()=>{if(requested)await deps.stop(owner);}).catch(()=>undefined);},
  };
}
