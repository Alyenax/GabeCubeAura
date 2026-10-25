/** Applied through native Tab.footer, which Steam spreads last on its header.
 * Removing header focus targets keeps native Sidebar/Tabs/ScrollPanel intact.
 * The header stays an accessible indicator; only shoulders select another tab.
 */
export const SETTINGS_TAB_INDICATOR={focusable:false,preferredFocus:false,
  onFocus:()=>{},onActivate:()=>{}};

export type SettingsNavHandle={TakeFocus:(direction?:number)=>boolean};
/** Native Tabs restores saved focus after 10ms. Enter the first control once
 * after that restore, only for an explicit tab switch made from its content.
 * Bounded retry handles async content registration; sidebar focus cancels it.
 */
export function focusSettingsTab(getHandle:()=>SettingsNavHandle|undefined,canEnter:()=>boolean,
  schedule:(callback:()=>void)=>number,cancel:(id:number)=>void,right:number){
  let frame:number|undefined,attempts=0,stopped=false;
  const tick=()=>{
    frame=undefined;if(stopped||!canEnter())return;
    attempts++;
    if(attempts>=3&&getHandle()?.TakeFocus(right))return;
    if(attempts<18)frame=schedule(tick);
  };
  frame=schedule(tick);
  return()=>{stopped=true;if(frame!==undefined)cancel(frame);};
}

export const EFFECTS_HELP='Configure Customization+ effects or the colours from your games’ Steam artwork.';
export function initialSettingsEffect(source:string|undefined,appid:number){
  return source==='artwork'||appid>0?'artwork':'customization';
}
