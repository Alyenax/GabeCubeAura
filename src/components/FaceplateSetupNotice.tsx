import type {Status} from '../types';
import {PanelSection,PanelSectionRow,Localized} from '../localized_ui';
import {QuickAction} from './QuickAction';
export function needsFaceplateSetup(status:Status){
  return status.onboarding_completed===true && status.faceplate.available===true
    && status.faceplate_setup_completed===false;
}
export function FaceplateSetupNotice({status,onOpen}:{status:Status;onOpen:()=>void}){
  if(!needsFaceplateSetup(status))return null;
  return <PanelSection title="Faceplate setup"><PanelSectionRow><Localized>
    <div role="status" style={{color:'#ffd27a',fontSize:'.85em',lineHeight:1.4}}>
      Your Faceplate is detected but has not been configured in GCA. Choose its Home and in-game displays.
    </div>
  </Localized></PanelSectionRow><PanelSectionRow><QuickAction onClick={onOpen}>Set up my Faceplate</QuickAction></PanelSectionRow></PanelSection>;
}
