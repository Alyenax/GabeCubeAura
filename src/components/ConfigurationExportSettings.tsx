import {useRef,useState} from 'react';
import {ButtonItem,Localized,PanelSectionRow} from '../localized_ui';
import {exportConfiguration} from '../api';

export function ConfigurationExportSettings({disabled=false,onBusyChange}:{disabled?:boolean;onBusyChange:(busy:boolean)=>void}) {
  const pending=useRef(false);
  const [busy,setBusy]=useState(false);
  const [path,setPath]=useState('');
  const [error,setError]=useState('');
  async function save() {
    if (pending.current || disabled) return;
    pending.current=true;setBusy(true);onBusyChange(true);setPath('');setError('');
    try {const result=await exportConfiguration();if(!result.path)throw new Error('The export did not return a file location.');setPath(result.path);}
    catch(reason) {setError(String(reason).replace(/^Error:\s*/,''));}
    finally {pending.current=false;setBusy(false);onBusyChange(false);}
  }
  return <>
    <PanelSectionRow><ButtonItem label="Export configuration JSON"
      description="Saves a JSON file locally on this Steam Machine. Its exact location is shown below after export."
      disabled={disabled||busy} onClick={()=>void save()}>{busy?'Exporting configuration…':'Export JSON'}</ButtonItem></PanelSectionRow>
    {busy?<PanelSectionRow><Localized><div role="status" aria-live="polite">Exporting configuration…</div></Localized></PanelSectionRow>:null}
    {path?<PanelSectionRow><Localized><div role="status" aria-live="polite" style={{fontSize:'.82em',overflowWrap:'anywhere'}}>
      <div>Configuration exported. Saved locally at:</div><div translate="no">{path}</div>
      <div>Use Import JSON to restore this file.</div>
    </div></Localized></PanelSectionRow>:null}
    {error?<PanelSectionRow><Localized><div role="alert" style={{fontSize:'.82em',color:'#ff9e9e',overflowWrap:'anywhere'}}>
      <div>Configuration export failed.</div><div>{error}</div>
    </div></Localized></PanelSectionRow>:null}
  </>;
}
