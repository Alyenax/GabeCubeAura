import {useRef,useState} from 'react';
import {ButtonItem,DropdownItem,Localized,PanelSectionRow,ToggleField} from '../localized_ui';
import {setSetting} from '../api';
import type {Status} from '../types';

export function HomeLibrarySettings({status,setStatus,sources}:{status:Status;setStatus:(status:Status)=>void;sources:{data:string;label:string}[]}){
  const [busy,setBusy]=useState(false),[error,setError]=useState('');const pending=useRef(false);
  async function save(key:string,value:unknown){
    if(pending.current)return;pending.current=true;setBusy(true);setError('');
    try{setStatus(await setSetting(key,value));}catch{setError('Could not save library playback settings.');}
    finally{pending.current=false;setBusy(false);}
  }
  return <>
    <PanelSectionRow><DropdownItem label="GIF library source" disabled={busy} rgOptions={sources}
      selectedOption={sources.some(item=>item.data===status.faceplate_home_library_source)?status.faceplate_home_library_source:'artwork'} onChange={option=>void save('faceplate_home_library_source',String(option.data))}/></PanelSectionRow>
    <PanelSectionRow><ToggleField label="Random order" disabled={busy} checked={status.faceplate_home_library_shuffle??false}
      description="Shows every prepared GIF before repeating."
      onChange={value=>void save('faceplate_home_library_shuffle',value)}/></PanelSectionRow>
    <PanelSectionRow><DropdownItem label="Change GIF every" disabled={busy} selectedOption={status.faceplate_home_library_interval??300}
      rgOptions={[{data:300,label:'5 minutes'},{data:900,label:'15 minutes'},{data:1800,label:'30 minutes'},{data:3600,label:'1 hour'}]}
      onChange={option=>void save('faceplate_home_library_interval',Number(option.data))}/></PanelSectionRow>
    <PanelSectionRow><Localized><small>Uses prepared local GIFs only. No download or conversion during playback.</small></Localized></PanelSectionRow>
    {error?<PanelSectionRow><Localized><div role="alert">{error}</div></Localized><ButtonItem label="Close" onClick={()=>setError('')}>Close</ButtonItem></PanelSectionRow>:null}
  </>;
}
