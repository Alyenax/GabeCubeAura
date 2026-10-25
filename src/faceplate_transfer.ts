import type {Status} from './types';

export type FaceplateTransferNotice={label:string;detail:string;active:boolean;tone:'waiting'|'good'|'error'};

/** Read the existing status stream. No timers, USB probes or guessed progress. */
export function faceplateTransferNotice(status:Status):FaceplateTransferNotice|null{
  const p=status.faceplate,w=p.automation,r=p.routing;
  if(!p.available||p.busy||!status.signalbar_enabled||status.current_display==='displays_off'||!status.faceplate_lab_enabled)return null;
  if(!w||!r?.preparation)return null;
  if(p.power_recovery?.suspended||(p.powered===false&&p.phase==='powered-off'))return null;
  const delayed:FaceplateTransferNotice={label:'Refresh delayed to protect the Faceplate.',
    detail:'The latest image is waiting. See Faceplate diagnostics for details.',active:false,tone:'waiting'};
  const pending=r.preparation.state==='pending'||r.preparation.state==='preparing';
  // Uploading is a real coordinator phase. Worker busy alone also covers rendering.
  // A queued new request takes precedence over an old transaction's receipt.
  const sending=(p.phase==='uploading'&&(w.busy||(!w.queued&&!pending)))||
    (p.delivery?.state==='sending'&&w.busy);
  if(sending)return {label:'Transferring to Faceplate…',detail:'Please wait.',active:true,tone:'waiting'};
  if(p.delivery?.state==='deferred'&&r.preparation.error?.startsWith('Flash protection:'))return delayed;
  if(w.busy||w.queued||pending||p.phase==='rendering')return {
    label:'Preparing image…',detail:'Please wait.',active:true,tone:'waiting'};
  if(p.power_recovery?.route_state==='retry-waiting')return {
    label:'Faceplate confirmation not received.',
    detail:'One automatic retry is scheduled. Please wait.',active:true,tone:'waiting'};
  if(r.preparation.state==='unconfirmed'||p.phase==='sent-unconfirmed')return {
    label:'Faceplate confirmation not received.',
    detail:'The image may have been received. See Faceplate diagnostics for details.',active:false,tone:'waiting'};
  if(p.delivery?.state==='deferred')return delayed;
  if(r.preparation.state==='error'||p.phase==='error'||w.last_error){
    return {label:p.delivery?.state==='failed'?'Transfer to Faceplate failed.':'Image preparation or transfer failed.',
      detail:'See Faceplate diagnostics for details.',active:false,tone:'error'};
  }
  if(p.powered===false)return null;
  if(p.delivery?.state==='confirmed'&&r.preparation.state==='ready'&&r.desired_content_key&&
      r.desired_content_key===r.effective_content_key)return {
    label:'Transfer confirmed by Faceplate.',detail:'',active:false,tone:'good'};
  return null;
}
