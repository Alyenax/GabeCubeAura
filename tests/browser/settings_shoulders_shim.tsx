// Browser fault injection only; no Steam controller engine is executed.
import {useEffect,useLayoutEffect,useRef,useState} from 'react';
export * from './settings_ui_shim';
const m=window.__gcaQaNative;
export const DialogBody=({children})=><div className="DialogBody">{children}</div>;
export function SidebarNavigation({title,pages,page,onPageRequested,fnSetNavigateToPage}){
 const s=m.sidebar,selected=pages.find(p=>p.route===page)||pages[0];
 useEffect(()=>{fnSetNavigateToPage?.(onPageRequested);},[fnSetNavigateToPage,onPageRequested]);
 return <div className={s.PagedSettingsDialog}><div className={s.PagedSettingsDialog_PageListColumn}><div className={s.PagedSettingsDialog_Title}>{title}</div><div className={s.PagedSettingsDialog_PageList}>{pages.map(p=><div className={s.PagedSettingsDialog_PageListItem} data-qa-category={p.identifier} role="button" tabIndex={0} key={p.route} onFocus={()=>onPageRequested(p.route)} onClick={()=>onPageRequested(p.route)}>{p.title}</div>)}</div></div><div className={'DialogContentTransition '+s.PagedSettingDialog_ContentColumn}><div className={'DialogContent '+s.PagedSettingsDialog_PageContent+' '+s.NoPadding}>{selected.content}</div></div></div>;
}
let serial=0;
export function Tabs({tabs,activeTab,onShowTab,autoFocusContents,wrapAround}){
 const t=m.tabs,id=useRef(++serial),previous=useRef(tabs.find(t=>t.id===activeTab)),timers=useRef([]),[outgoing,setOutgoing]=useState([]);
 const active=tabs.find(t=>t.id===activeTab);
 useLayoutEffect(()=>{
  if(previous.current.id!==active.id){
   const old=previous.current;setOutgoing(items=>[...items,old]);
   // Reproduce Steam's 10s fallback when completion is lost/interrupted.
   // Holding the outgoing start state is deliberate fault injection.
   timers.current.push(setTimeout(()=>setOutgoing(items=>items.filter(item=>item!==old)),10000));
  }
  previous.current=active;
 },[activeTab]);
 useEffect(()=>{
  window.__qa.live.add(id.current);
  if(autoFocusContents){const timer=setTimeout(()=>document.querySelector('[data-qa-tab-pane] button')?.focus(),0);timers.current.push(timer);}
  return()=>{window.__qa.live.delete(id.current);timers.current.forEach(clearTimeout);};
 },[]);
 useEffect(()=>{window.__qa.current={active:activeTab,onShowTab};window.__qa.callbacks.push(onShowTab);},[activeTab,onShowTab]);
 const shoulder=event=>{
  if(!['q','e'].includes(event.key)||event.defaultPrevented)return;
  event.preventDefault();event.stopPropagation();
  const index=tabs.indexOf(active)+(event.key==='e'?1:-1);
  if(index>=0&&index<tabs.length)onShowTab(tabs[index].id);
 };
 const panes=[...outgoing.map((tab,index)=>({tab,key:'exit-'+index,exit:true})),{tab:active,key:active.id,exit:false}];
 return <div className={t.GamepadTabbedPage} data-qa-tabs data-qa-native-scope={id.current} onKeyDown={shoulder}>
  <div className={t.TabHeaderRowWrapper}><div className={t.TabRow}><div className={t.TabRowTabs}><div className={t.TabsRowScroll}><div className={t.FixCenterAlignScroll}>{tabs.map(tab=><div role="tab" tabIndex={-1} aria-selected={tab===active} className={t.Tab+' '+(tab===active?t.Selected:'')} key={tab.id}>{tab.title}</div>)}</div></div></div></div></div>
  <div className={t.TabContents}>{panes.map(({tab,key,exit})=><div key={key} className={t.ContentTransition+' '+(exit?t.Exit:'')} data-qa-tab-pane={tab.id} data-qa-outgoing={exit||undefined}><div className={t.TabContentsScroll} role="tabpanel">{tab.content}</div></div>)}</div>
 </div>;
}
