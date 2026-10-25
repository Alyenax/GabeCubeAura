// DOM/CSS fixture only. The native Steam navigation engine is NOT emulated.
// The QA server extracts CSS-module maps as data from Valve's public client;
// no downloaded Steam JavaScript is executed and none is shipped in the plugin.
import React,{forwardRef,useEffect,useId,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {createPortal} from 'react-dom';

const native=window.__gcaQaNative??{};
const mapped=keys=>Object.fromEntries(keys.map(key=>[key,'steam_fixture_'+key.toLowerCase()+'_x17']));
const cx=(...classes)=>classes.filter(Boolean).join(' ');
export const gamepadDialogClasses=native.field??mapped(['Field','FieldLeftColumn','FieldRightColumn','FieldLabel','FieldLabelRow','FieldChildrenInner','FieldChildrenWithIcon','FieldDescription','ChildrenWidthFixed','ChildrenWidthGrow','WithChildrenInline','WithChildrenBelow','VerticalAlignCenter','StandardPadding','WithBottomSeparatorStandard','HighlightOnFocus','Button','ControlsListChild','BackgroundAnimation','focusAnimation','Toggle','ToggleRail','ToggleSwitch','On','DropDownControlButtonContents','DropDownRow']);
export const gamepadSliderClasses=native.slider??mapped(['SliderControlPanelGroup','SliderControlAndNotches','SliderControl','SliderTrack','SliderTrackDark','SliderHandleContainer','SliderHandle','LabelText','DescriptionValue','DescriptionValueText','BackgroundAnimation']);
export const gamepadTabbedPageClasses=native.tabs??mapped(['GamepadTabbedPage','TabHeaderRowWrapper','Pinned','TabRow','TabRowTabs','TabsRowScroll','FixCenterAlignScroll','Tab','TabTitle','Selected','Glyphs','Show','TabRowSpacer','TabContents','TabContentsScroll','ContentTransition']);
const sidebarClasses=native.sidebar??mapped(['PagedSettingsDialog','PagedSettingsDialog_PageListColumn','PagedSettingsDialog_PageList','PagedSettingsDialog_PageListItem','PagedSettingsDialog_Title','Active','ScaledChildren','PageListItem_Title','PagedSettingDialog_ContentColumn','PagedSettingsDialog_PageContent','NoPadding','ContentTransition']);
const transitionClasses=native.transition??mapped(['TransitionGroup','ContentWrapper']);
export const quickAccessControlsClasses=mapped(['PanelSection','PanelSectionRow','PanelSectionTitle','BackgroundAnimation']);
export const findClassModule=predicate=>[gamepadDialogClasses,gamepadSliderClasses,gamepadTabbedPageClasses,sidebarClasses,quickAccessControlsClasses].find(predicate);
export const Navigation={NavigateBack(){window.__gcaQaExited=true;},CloseSideMenus(){window.__gcaQaSideMenusClosed=true;},Navigate(path){window.__gcaQaNavigation=path;},NavigateToExternalWeb(){}};
export const Router=Navigation,staticClasses={},NavEntryPositionPreferences={PREFERRED_CHILD:4,FIRST:0};
export const GamepadButton={OK:1,CANCEL:2,BUMPER_LEFT:5,BUMPER_RIGHT:6,DIR_UP:9,DIR_DOWN:10,DIR_LEFT:11,DIR_RIGHT:12};
export const getGamepadNavigationTrees=()=>[],getFocusNavController=()=>null,findModuleExport=()=>null;
export const useParams=()=>window.__gcaQaParams??{};

const excluded=new Set(['untranslatedProps','untranslatedOptions','preferredFocus','navEntryPreferPosition','resetNavOnEntry','onFocusWithin','actionDescriptionMap','noFocusRing','onOKActionDescription','onCancelActionDescription','focusable','childFocusDisabled','navRef','autoFocus','scrollIntoViewWhenChildFocused','scrollIntoViewType']);
const clean=props=>Object.fromEntries(Object.entries(props).filter(([key])=>!excluded.has(key)&&!key.startsWith('onGamepad')&&!['onButtonDown','onCancelButton','onActivate'].includes(key)));
const keyButton=key=>key==='q'?5:key==='e'?6:key==='Escape'?2:0;
const gamepadEvent=(event,button)=>({detail:{button},defaultPrevented:false,preventDefault(){event.preventDefault();this.defaultPrevented=true;},stopPropagation(){event.stopPropagation();}});
export const Focusable=forwardRef(({children,className,onButtonDown,onCancelButton,onActivate,navRef,...props},ref)=>{
 const element=useRef(null);
 useEffect(()=>{
  if(!navRef)return;
  // Deliberate browser double of the native ref contract, NOT Steam navigation.
  const handle={TakeFocus(direction){const first=[...element.current.querySelectorAll('button:not([aria-disabled=true]),input:not(:disabled),[role=slider]:not([aria-disabled=true]),[role=checkbox]:not([aria-disabled=true])')].find(el=>el.getBoundingClientRect().height>0);
   if(!first)return false;first.focus();window.__gcaQaFocusRequests??=[];window.__gcaQaFocusRequests.push({tab:element.current.dataset.gcaTab,direction});return true;}};
  if(typeof navRef==='function')navRef(handle);else navRef.current=handle;
  return()=>{if(typeof navRef==='function')navRef(undefined);else navRef.current=undefined;};
 },[navRef]);
 return <div {...clean(props)} className={cx('Focusable',className)} ref={node=>{element.current=node;if(typeof ref==='function')ref(node);else if(ref)ref.current=node;}}
 onFocus={event=>{props.onFocus?.(event);props.onGamepadFocus?.(event);}} onKeyDown={event=>{
  props.onKeyDown?.(event);if(event.defaultPrevented)return;
  const button=keyButton(event.key);
  if(button){const detail=gamepadEvent(event,button);button===2?onCancelButton?.(detail):onButtonDown?.(detail);}
  else if(event.key==='Enter'&&event.target===event.currentTarget)onActivate?.(gamepadEvent(event,1));
}}>{children}</div>;});
export const DialogButton=forwardRef(({children,className,disabled,onClick,onKeyDown,role,...props},ref)=><button type="button" {...clean(props)} role={role} tabIndex={disabled?-1:0}
  aria-disabled={disabled||undefined} className={cx(gamepadDialogClasses.Button,'DialogButton _DialogLayout Secondary',disabled&&'Disabled',className)} ref={ref}
  onClick={disabled?undefined:onClick} onKeyDown={event=>{onKeyDown?.(event);if(disabled&&['Enter',' '].includes(event.key))event.preventDefault();}}>{children}</button>);

export const PanelSection=forwardRef(({title,children},ref)=><section className={quickAccessControlsClasses.PanelSection} ref={ref}>{title?<h3 className={quickAccessControlsClasses.PanelSectionTitle}>{title}</h3>:null}{children}</section>);
export const PanelSectionRow=forwardRef(({children},ref)=><div className={quickAccessControlsClasses.PanelSectionRow} ref={ref}>{children}</div>);
export const Field=({label,description,children,layout='inline',childrenContainerWidth='min',bottomSeparator='standard',className,disabled})=>{
  const f=gamepadDialogClasses,below=layout==='below';
  const child=<div className={f.FieldChildrenWithIcon}><div className={f.FieldChildrenInner}>{children}</div></div>;
  return <div className={cx('Focusable',f.Field,className,children&&(below?f.WithChildrenBelow:f.WithChildrenInline),childrenContainerWidth==='fixed'&&f.ChildrenWidthFixed,childrenContainerWidth==='max'&&f.ChildrenWidthGrow,f.StandardPadding,bottomSeparator==='standard'&&f.WithBottomSeparatorStandard,f.VerticalAlignCenter,f.HighlightOnFocus,disabled&&f.Disabled)}>
    <div className={f.FieldLeftColumn}>{label?<div className={f.FieldLabelRow}><div className={f.FieldLabel}>{label}</div></div>:null}{below?child:null}{description?<div className={f.FieldDescription}>{description}</div>:null}</div>
    {!below?<div className={f.FieldRightColumn}>{child}</div>:null}
  </div>;
};
export const ToggleField=({label,description,checked,onChange,disabled,layout,childrenContainerWidth,bottomSeparator})=><Field {...{label,description,disabled,layout,childrenContainerWidth,bottomSeparator}}><div role="checkbox" aria-label={label} tabIndex={disabled?-1:0} aria-checked={!!checked} aria-disabled={disabled} className={cx('Focusable',gamepadDialogClasses.Toggle,checked&&gamepadDialogClasses.On,disabled&&gamepadDialogClasses.Disabled)}
  onClick={disabled?undefined:()=>onChange(!checked)} onKeyDown={event=>{if(!disabled&&['Enter',' '].includes(event.key)){event.preventDefault();onChange(!checked);}}}><div className={gamepadDialogClasses.ToggleRail}/><div className={gamepadDialogClasses.ToggleSwitch}/></div></Field>;
export const SliderField=({label,description,value,min=0,max=100,step=1,onChange,disabled,valueSuffix='',showValue,layout='below',childrenContainerWidth='fixed',bottomSeparator})=>{
  const s=gamepadSliderClasses,percent=Math.min(1,Math.max(0,max>min?(value-min)/(max-min):0));
  const fieldLabel=showValue?<><div className={s.LabelText}>{label}</div><div className={s.DescriptionValue}><span className={s.DescriptionValueText}>{value}{valueSuffix}</span></div></>:label;
  return <Field label={fieldLabel} {...{description,layout,childrenContainerWidth,disabled,bottomSeparator}}><div className={cx('Focusable',s.SliderControlPanelGroup,'SliderControlPanelGroup')}><div className={cx('Focusable',s.SliderControlAndNotches,disabled&&s.Disabled)} role="slider" aria-label={label} tabIndex={disabled?-1:0} aria-valuemin={min} aria-valuemax={max} aria-valuenow={value} aria-disabled={disabled}
    style={{'--normalized-slider-value':percent,'--normalized-slider-origin':0,'--slider-extra-notch-padding':'0px'}} onKeyDown={event=>{if(!disabled&&['ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();onChange(Math.min(max,Math.max(min,value+(event.key==='ArrowRight'?step:-step))));}}}>
    <div className={cx(s.SliderControl,'SliderControl')}><div className={cx(s.SliderTrack,'SliderTrack')}/><div className={cx(s.SliderHandleContainer,'SliderHandleContainer')}><div className={cx(s.SliderHandle,'SliderHandle')}/></div></div>
  </div></div></Field>;
};
// Valve's raw Dropdown is not a DialogButton. Its uncontrolled display changes
// immediately, then follows changed selectedOption props after server refresh.
export const Dropdown=forwardRef(({label,menuLabel,rgOptions=[],selectedOption,onChange,disabled,controlled,strDefaultLabel='',renderButtonValue,onMenuWillOpen,onMenuOpened,className,itemContext=false,...props},ref)=>{
  const [opened,setOpened]=useState(false),[position,setPosition]=useState({left:0,top:0}),[value,setValue]=useState(selectedOption),button=useRef(null),previous=useRef(selectedOption),listId=useId();
  useEffect(()=>{if(previous.current!==selectedOption){previous.current=selectedOption;setValue(selectedOption);}},[selectedOption]);
  const current=rgOptions.find(option=>option.data===(controlled?selectedOption:value));
  const close=()=>{setOpened(false);button.current?.focus();};
  const choose=(option,event)=>{if(disabled)return;setValue(option.data);close();onChange?.(option,undefined,event);};
  // Native Field supplies a context-specific DialogButton renderer (ue),
  // whereas raw QAM Dropdown uses Se / DialogDropDown. They are not aliases.
  const Button=itemContext?DialogButton:'button';
  const arrow=<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="M3 6L8 11L13 6" fill="none" stroke="currentColor"/></svg>;
  const selectedLabel=current?.label??strDefaultLabel;
  const display=<div className="DialogDropDown_CurrentDisplay">{renderButtonValue?renderButtonValue(selectedLabel):selectedLabel}</div>;
  return <><Button type="button" {...clean(props)} ref={node=>{button.current=node;if(typeof ref==='function')ref(node);else if(ref)ref.current=node;}} role="combobox" aria-label={label??menuLabel} aria-expanded={opened} aria-controls={opened?listId:undefined} disabled={disabled}
    className={cx(itemContext?native.dropdown?.DropDownControlButton:'DialogDropDown _DialogInputContainer',opened&&'Active',disabled&&'Disabled',className)} onClick={event=>{if(opened){close();return;}const rect=event.currentTarget.getBoundingClientRect();const show=()=>{setPosition({left:rect.left,top:Math.min(rect.bottom,innerHeight-180)});setOpened(true);onMenuOpened?.();};if(onMenuWillOpen?.(show)!==false)show();}}
    onKeyDown={event=>{if(event.key==='Escape'&&opened){event.preventDefault();close();}else if(['ArrowUp','ArrowDown'].includes(event.key)&&!disabled){event.preventDefault();const index=rgOptions.indexOf(current),next=index+(event.key==='ArrowDown'?1:-1);if(next>=0&&next<rgOptions.length)choose(rgOptions[next],event);}}}>
    {itemContext?<div className={gamepadDialogClasses.DropDownControlButtonContents}>{display}{arrow}</div>:<>{display}{!disabled?<div className="DialogDropDown_Arrow">{arrow}</div>:null}</>}
  </Button>{opened?createPortal(<div id={listId} role="listbox" className="qa-dropdown-options" style={{position:'fixed',...position,zIndex:2000,background:'#202c3a',padding:8,display:'flex',flexDirection:'column',gap:4}}>{rgOptions.map((option,index)=><button type="button" role="option" aria-selected={option===current} key={index} onClick={event=>choose(option,event)}>{option.label}</button>)}</div>,document.body):null}</>;
});
export const DropdownItem=({label,description,layout='inline',childrenContainerWidth='min',bottomSeparator,...props})=><Field {...{label,description,layout,childrenContainerWidth,bottomSeparator}}><Dropdown label={label} itemContext {...props}/></Field>;
export const TextField=forwardRef(({label,description,value,onChange,disabled,...props},ref)=><div className="DialogInputLabelGroup _DialogLayout"><label>{label?<div className="DialogLabel _DialogLayout">{label}</div>:null}<div className="DialogInput_Wrapper"><input {...clean(props)} className="DialogInput DialogTextInputBase" aria-label={label} value={value??''} onChange={onChange} disabled={disabled} ref={ref}/></div>{description?<div className="DialogLabelExplainer">{description}</div>:null}</label></div>);
export const ButtonItem=({label,description,children,onClick,disabled,layout='inline',childrenContainerWidth='min'})=><Field {...{label,description,layout,childrenContainerWidth,disabled}}><DialogButton onClick={onClick} disabled={disabled}>{children}</DialogButton></Field>;
export const ScrollPanel=({children})=><div className="qa-native-scroll-panel">{children}</div>;
export const SteamSpinner=props=><svg {...props} role="progressbar" viewBox="0 0 20 20"><circle cx="10" cy="10" r="8" fill="none" stroke="currentColor"/></svg>;

export function SidebarNavigation({title,pages,page,onPageRequested,fnSetNavigateToPage,showTitle=true}){
  const s=sidebarClasses,id=useId(),available=pages.filter(item=>typeof item==='object'&&item.visible!==false),active=available.find(item=>item.route===page||item.identifier===page)??available[0];
  useEffect(()=>{fnSetNavigateToPage?.(onPageRequested);},[fnSetNavigateToPage,onPageRequested]);
  return <div data-qa-sidebar className={cx('Focusable',s.PagedSettingsDialog)}>
    <div className={cx('Focusable','PageListColumn',s.PagedSettingsDialog_PageListColumn)}>{showTitle?<div className={s.PagedSettingsDialog_Title}>{title}</div>:null}
      <div className={cx('Focusable',s.PagedSettingsDialog_PageList)} role="tablist" aria-orientation="vertical">{available.map(item=><div key={item.route??item.identifier} role="tab" tabIndex="0" aria-selected={item===active} aria-controls={id+item.route+'_Content'} className={cx('Focusable',s.PagedSettingsDialog_PageListItem,item===active&&s.Active)}
        onFocus={()=>onPageRequested?.(item.route??item.identifier)} onClick={()=>onPageRequested?.(item.route??item.identifier)} onKeyDown={event=>{if(event.key==='Enter')onPageRequested?.(item.route??item.identifier);}}>
        <div className={s.ScaledChildren}><div className={s.PageListItem_Title}>{item.title}</div></div>
      </div>)}</div>
    </div>
    <div className={cx('Focusable','DialogContentTransition',s.PagedSettingDialog_ContentColumn)}><div className={transitionClasses.TransitionGroup}><div key={active?.route??active?.identifier} className={cx(transitionClasses.ContentWrapper,s.ContentTransition)}><div className="Focusable">
      <div className={cx('DialogContent _DialogLayout',s.PagedSettingsDialog_PageContent,active?.padding==='none'&&s.NoPadding)} role="tabpanel" id={id+active?.route+'_Content'}><div className="DialogContent_InnerWidth">{!active?.hideTitle?<div className="DialogHeader">{active?.title}</div>:null}{active?.content}</div></div>
    </div></div></div></div>
  </div>;
}
export function Tabs({tabs,activeTab,onShowTab,wrapAround=true}){
  const t=gamepadTabbedPageClasses,id=useId(),active=tabs.find(tab=>tab.id===activeTab)??tabs[0];
  const shoulder=event=>{const direction=event.key==='q'?-1:event.key==='e'?1:0;if(direction){event.preventDefault();event.stopPropagation();const next=tabs.indexOf(active)+direction;if(wrapAround)onShowTab(tabs[(next+tabs.length)%tabs.length].id);else if(next>=0&&next<tabs.length)onShowTab(tabs[next].id);}};
  return <div data-qa-tabs className={cx('Focusable',t.GamepadTabbedPage)} onKeyDown={shoulder}>
    <div className={cx(t.TabHeaderRowWrapper,t.Pinned)}><div className={t.TabRow}>
      <div className={cx(t.Glyphs,t.Show)}>L1</div><div className={t.TabRowTabs} role="tablist" aria-orientation="horizontal"><div className={t.TabsRowScroll}><div className={cx('Focusable',t.FixCenterAlignScroll)}>
        <div className={t.TabRowSpacer}/>{tabs.map(tab=><div key={tab.id} id={id+tab.id} role="tab" tabIndex={tab.footer?.focusable===false?-1:0} aria-selected={tab===active} aria-controls={id+tab.id+'_Content'} className={cx('Focusable',t.Tab,tab===active&&t.Selected)}
         onFocus={tab.footer?.onFocus??(()=>onShowTab(tab.id))} onClick={tab.footer?.onActivate??(()=>onShowTab(tab.id))}><span className={t.TabTitle}>{tab.title}</span></div>)}<div className={t.TabRowSpacer}/>
      </div></div></div><div className={cx(t.Glyphs,t.Show)}>R1</div>
    </div></div>
    <div className={cx('Focusable',t.TabContents)}><div className={transitionClasses.TransitionGroup}><div className={cx(transitionClasses.ContentWrapper,t.ContentTransition)} key={active?.id}><div className="Focusable"><div className={cx(t.TabContentsScroll,'_TabContentsScroll')} role="tabpanel" id={id+active?.id+'_Content'} aria-labelledby={id+active?.id}>{active?.content}</div></div></div></div></div>
  </div>;
}
export const ConfirmModal=({strTitle,strDescription,children,strOKButtonText='OK',strCancelButtonText='Cancel',onOK,onCancel,bAlertDialog,bOKDisabled})=><div className="qa-modal" role="dialog"><h2>{strTitle}</h2>{strDescription?<p>{strDescription}</p>:null}{children}<button disabled={bOKDisabled} onClick={onOK}>{strOKButtonText}</button>{!bAlertDialog?<button onClick={onCancel}>{strCancelButtonText}</button>:null}</div>;
export function showModal(node){const el=document.createElement('div');document.getElementById('modals').append(el);const root=createRoot(el);root.render(node);return{Close(){root.unmount();el.remove();}};}

// Full-page public primitives added since the original QAM fixture.
export const DialogBody=({children,className=''})=><div className={'DialogBody '+className}>{children}</div>;
export const DialogHeader=({children})=><div className="DialogHeader">{children}</div>;
export const DialogControlsSection=forwardRef(({children,className='',...props},ref)=><div className={'DialogControlsSection '+className} ref={ref} {...props}>{children}</div>);
export const DialogControlsSectionHeader=({children})=><div className="DialogControlsSectionHeader">{children}</div>;
export const useQuickAccessVisible=()=>true;
