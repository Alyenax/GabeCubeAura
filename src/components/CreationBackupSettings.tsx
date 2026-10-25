import {useRef,useState} from 'react';
import {ButtonItem,DropdownItem,Localized,PanelSectionRow} from '../localized_ui';
import {getFaceplateArtworkLibrary,exportCreation,type FaceplateArtworkLibraryEntry,type ConfigurationBackupResult} from '../api';

/** Local prepared creation export; no account or upload. */
export function CreationBackupSettings({connected}:{connected:boolean;open:(url:string)=>void}) {
  const pending=useRef(false);
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const [entries,setEntries]=useState<FaceplateArtworkLibraryEntry[]>([]);
  const [selected,setSelected]=useState('');
  const [saved,setSaved]=useState<ConfigurationBackupResult|null>(null);
  async function load() {
    if(pending.current||!connected)return;
    pending.current=true;setBusy(true);setError('');
    try {
      const result=await getFaceplateArtworkLibrary();
      const active=result.entries.filter(item=>item.active&&item.sha256);
      setEntries(active);setSelected('');setSaved(null);
      if(!active.length)setError('No active saved creation. Apply an artwork in the Artwork tab first.');
    } catch(reason){setError(String(reason).replace(/^Error:\s*/,''));}
    finally{pending.current=false;setBusy(false);}
  }
  async function save() {
    const item=entries.find(entry=>String(entry.appid)===selected);
    if(pending.current||!connected||!item)return;
    pending.current=true;setBusy(true);setError('');setSaved(null);
    try {setSaved(await exportCreation(item.appid,item.mode,item.sha256!));}
    catch(reason){setError(String(reason).replace(/^Error:\s*/,''));}
    finally{pending.current=false;setBusy(false);}
  }
  return <>
    <PanelSectionRow><ButtonItem label="Export a saved creation"
      description="Saves a selected creation on this machine, including its prepared GIF and Dashboard background."
      disabled={busy||!connected} onClick={()=>void load()}>Choose a saved creation</ButtonItem></PanelSectionRow>
    {entries.length?<>
      <PanelSectionRow><DropdownItem label="Active creation to export" disabled={busy} selectedOption={selected}
        rgOptions={[{data:'',label:'Choose a creation'},...entries.map(item=>({data:String(item.appid),label:`${item.name} · ${item.mode} · Active`}))]}
        onChange={option=>{setSelected(String(option.data));setSaved(null);setError('');}}/></PanelSectionRow>
      <PanelSectionRow><ButtonItem label="Export creation locally" disabled={busy||!connected||!selected}
        onClick={()=>void save()}>{busy?'Exporting creation…':'Export selected creation'}</ButtonItem></PanelSectionRow>
    </>:null}
    {error?<PanelSectionRow><Localized><div role="alert">{error}</div></Localized></PanelSectionRow>:null}
    {saved?<>
      <PanelSectionRow><Localized><div style={{fontSize:'.78em',overflowWrap:'anywhere'}}>
        <div>Creation saved locally. Nothing was sent.</div>
        <div>{saved.path}</div><div>SHA-256: {saved.digest}</div>
      </div></Localized></PanelSectionRow>

    </>:null}
  </>;
}
