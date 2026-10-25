import {DropdownItem} from '../localized_ui';
type Option={data:string;label:string};
type Props={label:string;selectedOption:string;rgOptions:Option[];disabled?:boolean;
  onChange:(option:Option)=>void;onMenuWillOpen?:()=>void;onMenuOpened?:()=>void};

/** Compatibility name retained for callers; rendered selector is Steam's DropdownItem. */
export function QuickInlineChoice({label,selectedOption,rgOptions,disabled=false,onChange,onMenuWillOpen,onMenuOpened}:Props){
  return <DropdownItem label={label} menuLabel={label} selectedOption={selectedOption} rgOptions={rgOptions}
    disabled={disabled} onChange={onChange} onMenuOpened={onMenuOpened}
    onMenuWillOpen={show=>{onMenuWillOpen?.();show();}}/>;
}
