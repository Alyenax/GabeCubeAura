import {useState} from 'react';
import {DropdownItem, Localized, PanelSection, PanelSectionRow, ToggleField} from '../localized_ui';
import {setSetting} from '../api';
import type {Status} from '../types';
import {faceplateControlLabel} from '../faceplate_control';

export function FaceplatePrioritySettings({status,setStatus}:{status:Status;setStatus:(value:Status)=>void}) {
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState('');
  const write=async(key:string,value:string|boolean)=>{
    if(saving)return;
    setSaving(true);setError('');
    try{setStatus(await setSetting(key,value));}
    catch{setError('Faceplate control could not be confirmed. Check the current setting and try again.');}
    finally{setSaving(false);}
  };
  const mode=status.faceplate_control_mode??'automatic';
  return <PanelSection>
    <PanelSectionRow><DropdownItem label="Faceplate control"
      description="Choose whether GCA or another application may use the Faceplate. Saved displays and brightness are preserved."
      selectedOption={mode} disabled={saving}
      rgOptions={[{data:'automatic',label:'Automatic'},{data:'gca-priority',label:'GCA Priority'},{data:'other-app',label:'Other app'}]}
      onChange={option=>void write('faceplate_control_mode',String(option.data))}/></PanelSectionRow>
    <PanelSectionRow><Localized><div role="status" aria-live="polite">
      <div>{faceplateControlLabel(status)}</div>
      {mode==='automatic'?<small>Follows your saved displays without reserving USB between transfers.</small>:
       mode==='other-app'?<small>GCA stops USB commands. The current image may keep playing.</small>:
       <small>Keeps the USB connection reserved. Already-open or privileged applications may still interfere.</small>}
      {status.faceplate_control?.error?<small>{status.faceplate_control.error}</small>:null}
    </div></Localized></PanelSectionRow>
    {mode==='gca-priority'?<>
      <PanelSectionRow><ToggleField label="Allow Decky Animated Screensaver"
        description="Decky Animated Screensaver may display screensavers through GCA when connected."
        disabled={saving} checked={status.faceplate_allow_das??true}
        onChange={value=>void write('faceplate_allow_das',value)}/></PanelSectionRow>
      <PanelSectionRow><ToggleField label="Allow Decky Vocal Assistant"
        description="Decky Vocal Assistant may display temporary faces through GCA. Voice functions remain independent."
        disabled={saving} checked={status.faceplate_allow_dva??true}
        onChange={value=>void write('faceplate_allow_dva',value)}/></PanelSectionRow>
      <PanelSectionRow><Localized><small>Power off, sleep and protection rules remain in effect.</small></Localized></PanelSectionRow>
    </>:null}
    {error?<PanelSectionRow><Localized><div role="alert">{error}</div></Localized></PanelSectionRow>:null}
  </PanelSection>;
}
