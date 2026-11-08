import {useEffect,useRef,useState} from 'react';
import {DialogBody,DialogHeader,ModalRoot,showModal} from '@decky/ui';
import {ButtonItem,DialogButton,DropdownItem,Localized,PanelSectionRow} from '../localized_ui';
import {getStatus,setFaceplateRouting,setSetting} from '../api';
import {clockCountdown,CLOCK_TRANSFER_NOTICE,selectedClock,type ClockContext} from '../faceplate_clock';
import type {Status} from '../types';

function ClockPicker({initial,context,onSaved,close}:{initial:Status;context:ClockContext;onSaved:(s:Status)=>void;close:()=>void}){
  const[busy,setBusy]=useState(false),[error,setError]=useState('');const pending=useRef(false);
  const entries=initial.faceplate_clock?.catalog??[];
  async function choose(id:string){
    if(pending.current)return;pending.current=true;setBusy(true);setError('');
    try{
      // Re-read before writing the revisioned routes: a modal may remain open
      // while Home/game, an external service or another settings page changes.
      let next=await getStatus();
      if(!next.faceplate_clock?.catalog.some(entry=>entry.id===id))throw new Error('Clock unavailable');
      next=await setSetting('faceplate_clock_'+context,id);
      next=await setFaceplateRouting(context==='home'?'clock':next.faceplate.routing.routes.home,
        context==='game'?'clock':next.faceplate.routing.routes.game,next.faceplate.routing.preference_revision);
      onSaved(next);close();
    }catch{setError('The clock could not be selected. Please retry.');}
    finally{pending.current=false;setBusy(false);}
  }
  return <ModalRoot onCancel={close}><DialogHeader><Localized>Choose a clock</Localized></DialogHeader><DialogBody>
    <Localized><p>{CLOCK_TRANSFER_NOTICE}</p></Localized>
    {entries.length===0?<Localized><p>Standard clocks are being prepared. No clock is included in this build yet.</p></Localized>:null}
    {entries.map(entry=><ButtonItem key={entry.id} label={entry.label} disabled={busy}
      description={entry.private?'Private Lab study. Original game artwork belongs to its respective owners.':undefined}
      onClick={()=>void choose(entry.id)}>{entry.id===selectedClock(initial,context)?'Selected':'Choose'}</ButtonItem>)}
    {error?<Localized><p role="alert">{error}</p></Localized>:null}
    <DialogButton disabled={busy} onClick={close}>Close</DialogButton>
  </DialogBody></ModalRoot>;
}

export function openClockPicker(status:Status,setStatus:(s:Status)=>void,context:ClockContext){
  let modal:ReturnType<typeof showModal>|undefined;
  modal=showModal(<ClockPicker initial={status} context={context} onSaved={setStatus} close={()=>modal?.Close()}/>);
}

export function ClockCountdowns({status}:{status:Status}){
  const clock=status.faceplate_clock;
  const[elapsed,setElapsed]=useState(0);
  const base=useRef({server:clock?.server_now??0,mono:performance.now()});
  useEffect(()=>{base.current={server:clock?.server_now??0,mono:performance.now()};setElapsed(0);},[clock?.server_now]);
  useEffect(()=>{const timer=window.setInterval(()=>setElapsed((performance.now()-base.current.mono)/1000),250);return()=>window.clearInterval(timer);},[]);
  if(!clock)return null;
  const now=base.current.server+elapsed;
  const valid=clock.state!=='paused'&&clock.state!=='expired'&&!(clock.valid_until!=null&&now>=clock.valid_until);
  const selected=clock.catalog.find(entry=>entry.id===clock.selected);
  const at=(epoch:number|null)=>epoch==null?'':new Date(epoch*1000).toLocaleTimeString(undefined,{hour12:false});
  return <div role="status" aria-label="Clock schedule" style={{fontSize:'.85em',lineHeight:1.6}}>
    {selected?<Localized><div>Active clock: <span>{selected.label}</span></div></Localized>:null}
    <Localized><div>Next GIF transfer: <span title={at(clock.next_gif_at)}>{clockCountdown(valid?clock.next_gif_at:null,now)}</span></div></Localized>
    <Localized><div>Next scheduled movement: <span title={at(clock.next_movement_at)}>{clockCountdown(valid?clock.next_movement_at:null,now)}</span></div></Localized>
    <Localized><div>{clock.state==='preparing'?'Preparing clock…':clock.state==='waiting'?'Waiting for the scheduled transfer':clock.state==='transferring'?'Transferring clock…':!valid?'Clock paused or awaiting synchronization':clock.state==='acknowledged'?'Schedule estimated; display timing not measured.':'Clock awaiting synchronization'}</div></Localized>
    {clock.error?<Localized><div>{clock.error}</div></Localized>:null}
  </div>;
}

export function FaceplateClockSettings({status,setStatus,context}:{status:Status;setStatus:(s:Status)=>void;context:ClockContext}){
  const entry=status.faceplate_clock?.catalog.find(item=>item.id===selectedClock(status,context));
  return <>
    <PanelSectionRow><ButtonItem label="Choose a clock" onClick={()=>openClockPicker(status,setStatus,context)}>{entry?.label??'Choose'}</ButtonItem></PanelSectionRow>
    {entry?<ClockTransferSettings status={status} setStatus={setStatus} context={context}/>:null}
    {entry&&!entry.private?<ClockAppearance status={status} setStatus={setStatus} context={context}/>:null}
    <PanelSectionRow><Localized><small>{CLOCK_TRANSFER_NOTICE}</small></Localized></PanelSectionRow>
    <PanelSectionRow><ClockCountdowns status={status}/></PanelSectionRow>
  </>;
}

export function ClockAppearance({status,setStatus,context}:{status:Status;setStatus:(s:Status)=>void;context:ClockContext}){
  const [busy,setBusy]=useState(false),[error,setError]=useState('');const pending=useRef(false);
  async function save(option:'palette'|'format',value:string){
    if(pending.current)return;pending.current=true;setBusy(true);setError('');
    try{setStatus(await setSetting('faceplate_clock_'+option+'_'+context,value));}
    catch{setError('Could not save clock appearance. Please retry.');}
    finally{pending.current=false;setBusy(false);}
  }
  const analog=status.faceplate_clock?.catalog.find(item=>item.id===selectedClock(status,context))?.family==='analog';
  return <>
    <PanelSectionRow><DropdownItem label="Clock colours" disabled={busy}
      selectedOption={status['faceplate_clock_palette_'+context as 'faceplate_clock_palette_home']??'amber'}
      rgOptions={[{data:'amber',label:'Amber'},{data:'glacier',label:'Glacier blue'},{data:'rose',label:'Dusty rose'},
        {data:'sage',label:'Sage green'},{data:'lavender',label:'Lavender'},{data:'ivory',label:'Ivory'}]}
      onChange={option=>void save('palette',String(option.data))}/></PanelSectionRow>
    <PanelSectionRow><DropdownItem label="Clock format" disabled={busy}
      selectedOption={status['faceplate_clock_format_'+context as 'faceplate_clock_format_home']??'24'}
      rgOptions={analog?[{data:'24',label:'Without AM/PM'},{data:'12',label:'With AM/PM'}]:[{data:'24',label:'24 hours'},{data:'12',label:'12 hours (AM/PM)'}]}
      onChange={option=>void save('format',String(option.data))}/></PanelSectionRow>
    <PanelSectionRow><Localized><small>Clock dates follow the GCA language. Home and in-game colours and formats are saved separately.</small></Localized></PanelSectionRow>
    {error?<PanelSectionRow><Localized><div role="alert">{error}</div></Localized></PanelSectionRow>:null}
  </>;
}

export function ClockTransferSettings({status,setStatus,context}:{status:Status;setStatus:(s:Status)=>void;context:ClockContext}){
  const [busy,setBusy]=useState(false),[error,setError]=useState('');const pending=useRef(false);
  async function save(value:string){
    if(pending.current)return;pending.current=true;setBusy(true);setError('');
    try{setStatus(await setSetting('faceplate_clock_cadence_'+context,value));}
    catch{setError('Could not save clock transfer mode. Please retry.');}
    finally{pending.current=false;setBusy(false);}
  }
  return <>
    <PanelSectionRow><DropdownItem label="Clock transfer mode" disabled={busy}
      selectedOption={status['faceplate_clock_cadence_'+context as 'faceplate_clock_cadence_home']??'conservative'}
      rgOptions={[{data:'conservative',label:'Conservative · about 15/hour'},{data:'minute',label:'Fixed minute · about 60/hour'}]}
      onChange={option=>void save(String(option.data))}/></PanelSectionRow>
    <PanelSectionRow><Localized><small>Fixed minute keeps the time and date unchanged inside each GIF while animations continue. It uses more transfers. Home and games are saved separately.</small></Localized></PanelSectionRow>
    {error?<PanelSectionRow><Localized><div role="alert">{error}</div></Localized></PanelSectionRow>:null}
  </>;
}
