import {useRef,useState} from 'react';
import {ButtonItem,PanelSectionRow,Localized} from '../localized_ui';
import {BUILD_VERSION} from '../build_version';

export interface DiagnosticDocument {path:string;text:string;saved:boolean;error_code?:string}
/** One capture, one document. Writing or clipboard failure never discards it. */
export function DiagnosticExport({create}:{create:()=>Promise<DiagnosticDocument>}){
  const [busy,setBusy]=useState(false),[result,setResult]=useState<DiagnosticDocument|null>(null);
  const [message,setMessage]=useState('');
  const text=useRef<HTMLTextAreaElement|null>(null),inFlight=useRef(false);
  const generate=async()=>{
    if(inFlight.current)return;
    inFlight.current=true;setBusy(true);setMessage('');
    try{setResult(await create());}
    catch{setResult({path:'',saved:false,text:JSON.stringify({schema:'gabecubeaura-client-diagnostic-v1',frontend_version:BUILD_VERSION,backend_report_available:false},null,2)});
      setMessage('The backend report is unavailable. You can still copy this client report.');}
    finally{inFlight.current=false;setBusy(false);}
  };
  const copy=async()=>{
    if(!result)return;
    try{
      if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(result.text);setMessage('Diagnostic copied. Paste it directly into the issue.');return;}
    }catch{/* The selectable text remains available. */}
    text.current?.focus();text.current?.select();
    try{if(document.execCommand('copy')){setMessage('Diagnostic copied. Paste it directly into the issue.');return;}}catch{/* Manual selection remains possible. */}
    setMessage('Select and copy the diagnostic text below.');
  };
  return <>
    <PanelSectionRow><ButtonItem label="Export a local diagnostic"
      description="Creates one redacted report. Attach the file to the issue or copy its text. Nothing is uploaded."
      onClick={()=>void generate()}>{busy?'Preparing diagnostic…':'Export'}</ButtonItem></PanelSectionRow>
    {busy?<PanelSectionRow><div role="status"><Localized>Preparing one local report…</Localized></div></PanelSectionRow>:null}
    {result?<>
      <PanelSectionRow><div role="status"><Localized>{result.saved?'Diagnostic saved. Attach GabeCubeAura-diagnostic.json to the issue, or copy the text below.':'The file could not be saved. Copy the diagnostic text below.'}</Localized>
        {result.path?<div style={{overflowWrap:'anywhere'}} translate="no">{result.path}</div>:null}
      </div></PanelSectionRow>
      <PanelSectionRow><ButtonItem label="Copy diagnostic text" onClick={()=>void copy()}>Copy</ButtonItem></PanelSectionRow>
      <PanelSectionRow><textarea ref={text} readOnly value={result.text} aria-label="Diagnostic text"
        translate="no" style={{width:'100%',boxSizing:'border-box',minHeight:160,maxHeight:260,resize:'vertical',fontSize:12}}/></PanelSectionRow>
    </>:null}
    {message?<PanelSectionRow><div role="status"><Localized>{message}</Localized></div></PanelSectionRow>:null}
  </>;
}
