import {createContext,useContext,useEffect,useRef,type ReactNode} from 'react';
import {showModal,ConfirmModal,DialogButton,ScrollPanel} from '@decky/ui';
import {getUILanguage} from './i18n';
import {translateNode} from './localized_nodes';
import {type SettingsSelection,settingsSlotVisible} from './settings_structure';

interface Help {label:ReactNode;body:ReactNode}
interface Presentation {selection:SettingsSelection;help:Map<symbol,Help>;open:(selection:SettingsSelection)=>void}
const Context=createContext<Presentation|null>(null);
export const useSettingsPresentation=()=>useContext(Context);
export function SettingsPresentation({selection,onOpen,children}:{selection:SettingsSelection;onOpen:(selection:SettingsSelection)=>void;children:ReactNode}){
  const help=useRef(new Map<symbol,Help>());
  return <Context.Provider value={{selection,help:help.current,open:onOpen}}>{children}</Context.Provider>;
}
export function useSettingsHelp(label:ReactNode,body:ReactNode){
  const context=useSettingsPresentation();const id=useRef(Symbol());
  const help=context?.help;
  useEffect(()=>{if(!help||!body)return;const key=id.current;help.set(key,{label,body});return()=>{help.delete(key);};},[help,label,body]);
  return Boolean(context);
}
/** Explicit JSX slots keep original callbacks/options; invisible slots never mount children. */
export function SettingsPart({slot,children}:{slot:string|readonly string[];children:ReactNode}){
  const context=useSettingsPresentation();
  return !context||(Array.isArray(slot)?slot:[slot]).some(slot=>settingsSlotVisible(context.selection,slot))?<>{children}</>:null;
}
/** Static long copy only. Live statuses and errors must never use this component. */
export function SettingsHelpText({children,label='Details'}:{children:ReactNode;label?:string}){
  const compact=useSettingsHelp(label,children);
  return compact?null:<>{children}</>;
}
export function SettingsHelpButton(){
  const context=useSettingsPresentation();if(!context)return null;
  const french=getUILanguage()==='fr';
  return <DialogButton className="gca-help" onClick={()=>{
    const entries=Array.from(context.help.values());
    let modal:ReturnType<typeof showModal>|undefined;
    modal=showModal(<ConfirmModal strTitle={french?'Aide sur ces réglages':'About these settings'} bAlertDialog
      strOKButtonText={french?'Fermer':'Close'} onOK={()=>modal?.Close()} onCancel={()=>modal?.Close()}>
      <div className="gca-help-modal"><ScrollPanel><div style={{padding:20}}>{entries.length?entries.map((entry,index)=><section key={index} style={{marginBottom:22}}>
        <h3>{translateNode(entry.label,getUILanguage())}</h3><div>{translateNode(entry.body,getUILanguage())}</div>
      </section>):<p>{french?'Les choix sont enregistrés automatiquement. Les essais et les téléchargements demandent une action explicite.':'Choices are saved automatically. Previews and downloads require an explicit action.'}</p>}</div></ScrollPanel></div>
    </ConfirmModal>);
  }}>{french?'Aide sur ces réglages':'About these settings'}</DialogButton>;
}
