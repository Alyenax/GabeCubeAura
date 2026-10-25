import {useEffect,useRef,useState} from 'react';
import {DialogButton,Field,Focusable,Localized,PanelSection,PanelSectionRow,SliderField,TextField,ToggleField} from '../localized_ui';
import {QuickInlineChoice} from './QuickInlineChoice';
import {CompactLedPreview} from './LiveLedPreview';
import {extendFreeTimer,getQuickArtwork,setFaceplatePower,setFaceplateRouting,setGameDisplay,setLightBarBrightness,setSetting,startFreeTimer,stopFreeTimer} from '../api';
import {gameDisplayOptions} from '../game_display_options';
import {quickFaceOptions,homeFaceChoice,showArtworkPreparationHint} from '../faceplate_choices';

import {trailingSetting} from '../trailingSetting';
import {faceplateTransferNotice} from '../faceplate_transfer';
import {quickPanelState} from '../quick_panel';
import type {ArtworkPayload,RGB,Status} from '../types';
import {COMPACT_QUICK_CSS} from './compact_quick_style';
import {reportQuickUI} from '../quick_panel_ui';
import {playerCitySummary} from '../player_city';
import {presetSummary,quickAmbienceOptions} from '../lighting_presets';
export {QUICK_AMBIENCES} from '../lighting_presets';

type EndAction='none'|'sleep'|'shutdown';
export function personalTimer(status:Status){return status.personal_timer??{active:status.countdown.active&&status.countdown.source==='free',remaining_seconds:status.countdown.source==='free'?status.countdown.remaining_seconds:0};}
export function quickFaceChoice(status:Status){
  if(status.faceplate.powered===false)return 'off';
  const route=status.game.appid>0?status.faceplate.routing.routes.game:status.faceplate.routing.routes.home;
  return status.game.appid<=0?homeFaceChoice(status):route;
}
const clock=(seconds:number)=>`${Math.floor(Math.max(0,seconds)/60)}:${String(Math.floor(Math.max(0,seconds)%60)).padStart(2,'0')}`;

function TimerEditor({minutes:initial,disabled,onStart,onClose}:{minutes:number;disabled:boolean;onStart:(minutes:number,action:EndAction)=>Promise<boolean>;onClose:()=>void}){
  const[duration,setDuration]=useState(String(Math.max(1,Math.min(240,initial)))),[action,setAction]=useState<EndAction>('none');
  const minutes=Number(duration),valid=/^\d+$/.test(duration)&&Number.isInteger(minutes)&&minutes>=1&&minutes<=240;
  const settled=useRef(false);
  const start=async()=>{
    if(settled.current||!valid||disabled)return;
    settled.current=true;
    if(await onStart(minutes,action))onClose();else settled.current=false;
  };
  return <div className="gca-compact-editor" role="group" aria-label="Start a timer">
      <Focusable className="gca-compact-timer-actions" flow-children="row">
        <DialogButton disabled={disabled} onClick={()=>setDuration('30')}>30 min</DialogButton><DialogButton disabled={disabled} onClick={()=>setDuration('60')}>1 hr</DialogButton>
      </Focusable>
      <TextField label="Duration in minutes" disabled={disabled} value={duration} mustBeNumeric rangeMin={1} rangeMax={240} onChange={event=>setDuration(event.target.value)}/>
      {!valid?<Localized><p role="alert">Choose 1–240 whole minutes.</p></Localized>:null}
      <QuickInlineChoice label="When finished" disabled={disabled} selectedOption={action}
        rgOptions={[{data:'none',label:'Do nothing'},{data:'sleep',label:'Put console to sleep'},{data:'shutdown',label:'Shut down console'}]}
        onChange={option=>setAction(option.data as EndAction)}/>
      <Localized><p>{action==='shutdown'?'The console will shut down when this personal timer ends. Save your game before the deadline.':action==='sleep'?'The console will sleep when this personal timer ends. Save your game before the deadline.':'The timer will not change the console’s power state.'}</p></Localized>
      <Focusable className="gca-compact-timer-actions" flow-children="row">
        <DialogButton disabled={disabled} onClick={()=>{if(settled.current||disabled)return;settled.current=true;reportQuickUI('timer','cancelled');onClose();}}>Cancel</DialogButton>
        <DialogButton disabled={disabled||!valid} onClick={()=>void start()}>{action==='none'?'Start':'Confirm and start'}</DialogButton>
      </Focusable>
  </div>;
}

/** Native Decky focus targets, real status, no preview-triggered hardware writes. */
export function CompactQuickPanel({status,setStatus,colors,onOpenGame,onOpenSettings,onOpenArtwork,onMutationChange,active=true}:{active?:boolean;status:Status;setStatus:(value:Status)=>void;colors:RGB[];onOpenGame:()=>void;onOpenSettings:()=>void;onOpenArtwork:()=>void;onMutationChange?:(active:boolean)=>void}){
  const[busy,setBusy]=useState(false),[error,setError]=useState('');
  const[errorAction,setErrorAction]=useState('');
  const[art,setArt]=useState<ArtworkPayload|null>(null),[brightness,setBrightness]=useState(status.light_bar_day_brightness);
  const[faceBrightness,setFaceBrightness]=useState(status.faceplate_brightness);
  const latestFaceBrightness=useRef(faceBrightness);latestFaceBrightness.current=faceBrightness;
  const[editingTimer,setEditingTimer]=useState(false);
  const alive=useRef(true),working=useRef(false);
  const latest=useRef(status);latest.current=status;
  const locked=status.onboarding_completed!==true;
  const canUse=()=>alive.current&&latest.current.onboarding_completed===true;
  const setLatest=useRef(setStatus);setLatest.current=setStatus;
  const mutation=useRef(onMutationChange);mutation.current=onMutationChange;
  const saveBrightness=useRef<ReturnType<typeof trailingSetting<number,Status>>|null>(null);
  if(!saveBrightness.current)saveBrightness.current=trailingSetting(async value=>{
    if(latest.current.onboarding_completed!==true)return latest.current;
    mutation.current?.(true);
    try{const next=await setLightBarBrightness('light_bar_day_brightness',value,'day');if(canUse())setLatest.current(next);return next;}
    catch(reason){if(canUse()){setErrorAction('');setError('Brightness could not be saved. Try again.');setBrightness(latest.current.light_bar_day_brightness);}throw reason;}
    finally{mutation.current?.(false);}
  },250);
  const saveFaceBrightness=useRef<ReturnType<typeof trailingSetting<number,Status>>|null>(null);
  if(!saveFaceBrightness.current)saveFaceBrightness.current=trailingSetting(async value=>{
    if(latest.current.onboarding_completed!==true)return latest.current;
    mutation.current?.(true);
    try{const next=await setSetting('faceplate_brightness',value);if(canUse()&&latestFaceBrightness.current===value)setLatest.current(next);return next;}
    catch(reason){if(canUse()&&latestFaceBrightness.current===value){setErrorAction('faceplate-brightness');setError('JSAUX brightness could not be saved. Try again.');setFaceBrightness(latest.current.faceplate_brightness);}throw reason;}
    finally{mutation.current?.(false);}
  },400);
  useEffect(()=>{alive.current=true;reportQuickUI('panel','mounted');return()=>{alive.current=false;void saveBrightness.current?.flush().catch(()=>undefined);void saveFaceBrightness.current?.flush().catch(()=>undefined);};},[]);
  useEffect(()=>{if(!saveBrightness.current?.pending())setBrightness(status.light_bar_day_brightness);},[status.light_bar_day_brightness]);
  useEffect(()=>{if(!saveFaceBrightness.current?.pending())setFaceBrightness(status.faceplate_brightness);},[status.faceplate_brightness]);

  useEffect(()=>{if(locked){
    saveBrightness.current?.cancel();saveFaceBrightness.current?.cancel();
    setBrightness(status.light_bar_day_brightness);setFaceBrightness(status.faceplate_brightness);
    setEditingTimer(false);setError('');
  }},[locked]);

  const artRequest=useRef({key:'',attempts:0,busy:false,found:false});
  useEffect(()=>{
    if(!active)return;
    const key=`${status.game.appid}:${status.artwork_source}`;
    if(artRequest.current.key!==key){artRequest.current={key,attempts:0,busy:false,found:false};setArt(null);}
    const request=artRequest.current;
    if(status.game.appid<=0||request.busy||request.found||request.attempts>=3)return;
    request.busy=true;request.attempts++;
    void getQuickArtwork(status.game.appid,status.artwork_source).then(next=>{
      if(!alive.current||artRequest.current!==request)return;
      request.found=next.appid===status.game.appid&&next.found&&Boolean(next.data_uri);setArt(next);
    }).catch(()=>undefined).finally(()=>{request.busy=false;});
  },[status,active]);
  const run=async(task:()=>Promise<void>,action='',choice=''):Promise<boolean>=>{
    if(working.current||!canUse())return false;working.current=true;mutation.current?.(true);setBusy(true);setError('');setErrorAction(action);
    if(action)reportQuickUI(action,'requested',choice);
    try{await saveBrightness.current?.flush();await saveFaceBrightness.current?.flush().catch(()=>undefined);if(!canUse())return false;await task();if(action)reportQuickUI(action,'saved',choice);return true;}
    catch{if(action)reportQuickUI(action,'failed',choice);if(alive.current)setError(action==='timer'?'The timer could not be started. Try again.':action==='ambience'?'The ambience could not be saved. Try again.':action==='faceplate'?'The JSAUX choice could not be applied. Try again.':'Action could not be completed. Try again or open Settings.');return false;}
    finally{working.current=false;mutation.current?.(false);if(alive.current)setBusy(false);}
  };
  const update=async(task:Promise<Status>)=>{const next=await task;if(canUse())setStatus(next);};
  const timer=personalTimer(status),face=status.faceplate,game=status.game.appid>0;
  const controlsBusy=busy||locked;
  const pending=controlsBusy||!status.signalbar_enabled;
  const faceBusy=Boolean(face.busy)||!face.available||pending;
  const french=status.ui_language==='fr';
  const faceOptions=quickFaceOptions(game,french);
  const faceChoice=quickFaceChoice(status);
  const artworkGuidance=showArtworkPreparationHint(status);
  const reportedTransfer=faceplateTransferNotice(status);
  // A rejected choice may leave the previous scene's receipt in status.
  // Keep current progress/errors visible, but never confirm the failed choice.
  const transfer=busy&&errorAction==='faceplate'
    ? {label:'Saving display choice…',detail:'Please wait.',active:true,tone:'waiting'}
    : ((error&&errorAction==='faceplate')||artworkGuidance)&&reportedTransfer?.tone==='good'?null:reportedTransfer;
  const presets=quickAmbienceOptions(status.display_preset);
  const openTimer=()=>{
    if(!canUse()||working.current||editingTimer||busy)return;
    setError('');reportQuickUI('timer','opened');setEditingTimer(true);
  };
  const selectFace=async(value:string)=>{
    if(value==='off'){await update(setFaceplatePower(false));return;}
    let next=latest.current;
    next=await setFaceplateRouting(game?homeFaceChoice(next):value as Status['faceplate']['routing']['routes']['home'],game?value as 'dashboard'|'weather'|'artwork'|'artwork-dashboard'|'player-city':next.faceplate.routing.routes.game,next.faceplate.routing.preference_revision);
    if(!canUse())return;
    if(next.faceplate.powered===false)next=await setFaceplatePower(true);
    if(canUse())setStatus(next);
  };
  const frame=status.signalbar_enabled&&status.active&&colors.length===17?colors:Array.from({length:17},()=>[0,0,0] as RGB);
  return <div id="gca-compact-root"><style>{COMPACT_QUICK_CSS}</style>
    <section className="gca-compact-visual"><PanelSection><PanelSectionRow>
      {game?<DialogButton className="gca-compact-art-link" aria-label="Game display…" disabled={locked} onClick={()=>{if(canUse())onOpenGame();}}>
        {artRequest.current.key===`${status.game.appid}:${status.artwork_source}`&&art?.appid===status.game.appid&&art.found&&art.data_uri?<img src={art.data_uri} alt={status.game.title} className="gca-compact-game-art"/>:<Localized><div className="gca-compact-art-empty">No game artwork available yet.</div></Localized>}
        <span className="gca-compact-game-title" translate="no">{status.game.title}</span>
      </DialogButton>:<Localized><span className="gca-compact-game-title">Home</span></Localized>}
      <div className="gca-compact-led-caption"><Localized><span>Light bar</span></Localized><Localized><span role="status">{status.thermal_protection.active?'Protected':!status.signalbar_enabled?'Off':status.active?'Live':'Idle'}</span></Localized></div>
      <CompactLedPreview colors={frame} active={active}/>
    </PanelSectionRow></PanelSection></section>
    <section className="gca-compact-master"><PanelSection><PanelSectionRow><ToggleField label="Lighting" checked={status.signalbar_enabled} disabled={controlsBusy}
      onChange={value=>void run(()=>update(setSetting('signalbar_enabled',value)))}/></PanelSectionRow></PanelSection></section>
    <section className="gca-compact-light"><PanelSection><PanelSectionRow><div className="gca-compact-slider"><SliderField label="Brightness" value={Math.round(brightness/255*100)} min={0} max={100} step={1} valueSuffix=" %" showValue disabled={pending}
      onChange={value=>{if(!canUse()||pending||!Number.isFinite(value))return;setError('');const next=Math.round(value/100*255);setBrightness(next);saveBrightness.current?.push(next);}}/></div></PanelSectionRow><PanelSectionRow>
      <QuickInlineChoice label="Ambience" rgOptions={presets} selectedOption={status.display_preset} disabled={pending}
        onMenuWillOpen={()=>reportQuickUI('ambience','opening')}
        onMenuOpened={()=>reportQuickUI('ambience','opened')}
        onChange={option=>{if(!canUse())return;const value=String(option.data);reportQuickUI('ambience','selected',value);void run(async()=>{const next=await setSetting('display_preset',value);if(canUse())setStatus(next);if(next.display_preset!==value)throw new Error('Preset was not saved');},'ambience',value);}}/>
      </PanelSectionRow>{game?<PanelSectionRow><QuickInlineChoice label="In-game light bar"
        rgOptions={gameDisplayOptions(face.available, status.current_display)} selectedOption={status.current_display} disabled={pending}
        onChange={option=>{const value=String(option.data);void run(()=>update(setGameDisplay(status.game.appid,value)));}}/>
      </PanelSectionRow>:null}<PanelSectionRow><Localized><small className="gca-preset-summary">{presetSummary(status.display_preset)}</small></Localized>
      {error&&errorAction==='ambience'?<Localized><small className="gca-compact-action-error" role="alert">{error}</small></Localized>:null}</PanelSectionRow></PanelSection></section>
    <section className="gca-compact-timer"><PanelSection><PanelSectionRow><Field label="Timer" childrenLayout="below">
      {timer.active?<output className="gca-compact-clock" aria-label="Time remaining">{clock(timer.remaining_seconds)}</output>:editingTimer?null:<DialogButton disabled={controlsBusy} onClick={openTimer}>Start…</DialogButton>}</Field>
      {editingTimer&&!timer.active?<TimerEditor minutes={status.free_timer_minutes} disabled={controlsBusy} onClose={()=>{if(alive.current)setEditingTimer(false);}}
        onStart={(minutes,action)=>run(()=>update(startFreeTimer(minutes,action)),'timer',action)}/>:null}
      {timer.active?<><Focusable className="gca-compact-timer-actions" flow-children="row"><DialogButton disabled={controlsBusy||timer.remaining_seconds>225*60} onClick={()=>void run(()=>update(extendFreeTimer(15)))}>+15 min</DialogButton><DialogButton disabled={controlsBusy} onClick={()=>void run(()=>update(stopFreeTimer()))}>Stop</DialogButton></Focusable>
        <Localized><small>{['armed','ready','executing'].includes(status.timer_end_action.phase)?status.timer_end_action.action==='shutdown'?'Shut down when finished':'Sleep when finished':'No action when finished'}</small></Localized></>:null}
      {status.countdown.active&&status.countdown.source==='parental'?<Localized><small>Steam Families limit takes priority.</small></Localized>:null}
      {error&&errorAction==='timer'?<Localized><small className="gca-compact-action-error" role="alert">{error}</small></Localized>:null}
    </PanelSectionRow></PanelSection></section>
    {quickPanelState(status).faceplateControls?<section className="gca-compact-faceplate"><PanelSection title="JSAUX"><PanelSectionRow><QuickInlineChoice label="JSAUX screen" rgOptions={faceOptions} selectedOption={faceChoice} disabled={faceBusy}
      onMenuWillOpen={()=>reportQuickUI('faceplate','opening')}
      onMenuOpened={()=>reportQuickUI('faceplate','opened')}
      onChange={option=>{if(!canUse())return;const value=String(option.data);reportQuickUI('faceplate','selected',value);void run(()=>selectFace(value),'faceplate',value);}}/>
      {transfer?<div className={transfer.tone==='error'?'gca-compact-action-error':undefined} role="status" aria-live="polite" aria-atomic="true" data-faceplate-transfer={transfer.active?'active':'settled'}>
        <Localized><small>{transfer.label}</small></Localized>
        {transfer.detail?<Localized><small>{transfer.detail}</small></Localized>:null}
      </div>:null}
      {artworkGuidance?<div className="gca-compact-artwork-guidance" data-artwork-guidance>
        <Localized><small role="status">If no artwork is ready for this display, the Faceplate keeps its current image. Create and apply artwork in the Artwork tab.</small></Localized>
        <DialogButton className="gca-compact-wide" disabled={controlsBusy} onClick={()=>{if(canUse()&&!working.current)onOpenArtwork();}}>Create artwork</DialogButton>
      </div>:null}
      {faceChoice==='player-city'?<small role="status">{playerCitySummary(status)}</small>:null}
      </PanelSectionRow><PanelSectionRow><div className="gca-compact-slider"><SliderField label="JSAUX brightness" value={faceBrightness} min={5} max={100} step={5} valueSuffix=" %" showValue disabled={faceBusy||face.powered===false}
        onChange={value=>{if(!canUse()||faceBusy||face.powered===false||!Number.isFinite(value))return;const next=Math.max(5,Math.min(100,Math.round(value/5)*5));latestFaceBrightness.current=next;setFaceBrightness(next);setError('');saveFaceBrightness.current?.push(next);}}/></div>
      {face.busy?<Localized><small>In use by another app</small></Localized>:null}
      {error&&['faceplate','faceplate-brightness'].includes(errorAction)?<Localized><small className="gca-compact-action-error" role="alert">{error}</small></Localized>:null}</PanelSectionRow></PanelSection></section>:null}
    {status.thermal_protection.active||status.debug?.engine_running===false?<Localized><small role="status">{status.thermal_protection.active?'Thermal protection':'Display engine stopped'}</small></Localized>:null}
    {status.timer_end_action.phase==='failed'?<Localized><small role="alert">The timer ended, but Steam did not confirm the power action. No automatic retry.</small></Localized>:null}
    {error&&!['timer','ambience','faceplate','faceplate-brightness'].includes(errorAction)?<div className="gca-compact-error" role="alert"><Localized><small>{error}</small></Localized><DialogButton className="gca-compact-wide" disabled={locked} onClick={()=>{if(canUse())onOpenSettings();}}>Settings</DialogButton></div>:null}
  </div>;
}
