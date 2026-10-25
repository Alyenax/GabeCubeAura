import {PanelSection,PanelSectionRow} from '../localized_ui';
import {QuickAction} from './QuickAction';
import {showUpdateButton} from '../update_button';
import type {UpdateStatus} from '../types';

/** Persistent entry point; opening it never downloads or installs anything. */
export function UpdateAvailableButton({update,onOpen,disabled=false}:{update:UpdateStatus|null;onOpen:()=>void;disabled?:boolean}) {
  if(!showUpdateButton(update))return null;
  return <PanelSection><PanelSectionRow><QuickAction disabled={disabled} onClick={()=>{if(!disabled)onOpen();}}>
    <span>{update.phase==='ready'?'Update ready':'Update available'}</span>{' · '}
    <span translate="no">{update.available_version}</span>
  </QuickAction></PanelSectionRow></PanelSection>;
}
