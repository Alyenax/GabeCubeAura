import {PanelSectionRow, SliderField} from '../localized_ui';

/** Preparation-only control: no settings writes, rendering or hardware calls. */
export function ArtworkLogoScale({value,disabled,onChange}:{value:number;disabled:boolean;onChange:(value:number)=>void}){
  return <PanelSectionRow><SliderField label="Logo size"
    description="100% keeps the normal size. Reduces only the added logo; prepare a new preview to see the result."
    value={value} min={50} max={100} step={5} showValue valueSuffix="%"
    disabled={disabled} onChange={onChange} /></PanelSectionRow>;
}
