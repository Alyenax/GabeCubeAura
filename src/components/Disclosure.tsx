import { useState, type ReactNode } from "react";
import { ButtonItem, PanelSection, PanelSectionRow, ToggleField } from "../localized_ui";
import {useSettingsPresentation} from '../settings_presentation';

/** Native Decky control: no HTML details element or extra navigation item. */
export function Disclosure({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const compact=useSettingsPresentation();
  if(compact)return <><PanelSectionRow><ButtonItem label={title} onClick={()=>setOpen(!open)}>{open?'Hide':'Open'}</ButtonItem></PanelSectionRow>{open?children:null}</>;
  return <PanelSection title={title}>
    <PanelSectionRow><ToggleField label="Show details" checked={open} onChange={setOpen} /></PanelSectionRow>
    {open ? children : null}
  </PanelSection>;
}
