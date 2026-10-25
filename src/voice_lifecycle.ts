import { callable } from '@decky/api';

const report=callable<[instance:string,kind:string,category:string],boolean>('voice_frontend_lifecycle');
let current='';
export const reportVoiceNotificationFailure=()=>{if(current)void report(current,'notification-failed','Error').catch(()=>undefined);};

/** Only GCA-origin errors; no global messages, stack text or page contents. */
export function startVoiceLifecycle() {
  const id=Array.from(crypto.getRandomValues(new Uint8Array(8)),n=>n.toString(16).padStart(2,'0')).join('');
  current=id;
  let stopped=false, errors=0;
  const send=(kind:string,category='')=>{if(!stopped)void report(id,kind,category).catch(()=>undefined);};
  const owned=(file:string)=>/gabecubeaura/i.test(file);
  const onError=(event:ErrorEvent)=>{
    if(errors>=8||!owned(event.filename||event.error?.stack||''))return;
    errors++;send('error',event.error?.name||'Error');
  };
  const onRejection=(event:PromiseRejectionEvent)=>{
    if(errors>=8||!owned(String(event.reason?.stack||'')))return;
    errors++;send('rejection',event.reason?.name||'Error');
  };
  window.addEventListener('error',onError);
  window.addEventListener('unhandledrejection',onRejection);
  let pinging=false;
  const heartbeat=window.setInterval(()=>{
    if(stopped||pinging)return;
    pinging=true;void report(id,'heartbeat','').catch(()=>undefined).finally(()=>{pinging=false;});
  },5000);
  send('mounted');
  return {stop(){send('unmounted');stopped=true;if(current===id)current='';window.removeEventListener('error',onError);
    window.removeEventListener('unhandledrejection',onRejection);window.clearInterval(heartbeat);}};
}
