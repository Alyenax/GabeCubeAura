import {useRef,useState,useEffect,useCallback,useSyncExternalStore,type ReactNode} from 'react';
import {SidebarNavigation,Tabs,DialogBody,Focusable,GamepadButton,Navigation,NavEntryPositionPreferences,type GamepadEvent} from '@decky/ui';
import {getUILanguage,subscribeUILanguage,translate} from '../i18n';
import {settingsSelection,settingsStep,settingsCategoryRoute,settingsCategoryFromRoute,visibleSettingsCategories,visibleSettingsSelection,type SettingsSelection,type SettingsCategory} from '../settings_structure';
import {SettingsPresentation,SettingsHelpButton} from '../settings_presentation';
import {SETTINGS_CSS} from '../settings_theme';
import {SETTINGS_TAB_INDICATOR,focusSettingsTab,type SettingsNavHandle} from '../settings_navigation';

interface Props {initial?:SettingsSelection;initialSource?:string;faceplateConnected:boolean;renderContent:(selection:SettingsSelection,onOpen:(selection:SettingsSelection)=>void)=>ReactNode}

/** Steam owns sidebar entry, registered scrolling and the B return chain.
 * Each committed subtab mounts one native Tabs instance: no outgoing native
 * scope or delayed restore can overlap a later shoulder selection. */
export function SimpleSettings({initial,initialSource,faceplateConnected,renderContent}:Props){
  const [requestedSelection,setRequestedSelection]=useState(()=>settingsSelection(initial?.category??'display',initial?.tab));
  const selection=visibleSettingsSelection(requestedSelection,faceplateConnected);
  // The old Tabs instance must not keep an exiting native page/focus history
  // alive when shoulders reverse direction during its 400ms enter animation.
  const current=useRef(selection);current.current=selection;
  const revision=useRef(0),enterContent=useRef(false);
  const remembered=useRef<Partial<Record<SettingsCategory,string>>>({});
  const nativeRoute=useRef<string|undefined>(undefined);
  const area=useRef<'sidebar'|'content'>('sidebar');
  const [entry,setEntry]=useState(0);
  const switched=(next:SettingsSelection)=>{
    if(next.category===current.current.category&&next.tab===current.current.tab)return;
    enterContent.current=area.current==='content';
    if(enterContent.current)setEntry(value=>value+1);
    select(next);
  };
  const trackFocus=(event:{target:EventTarget|null})=>{
    const target=event.target as Element|null;
    if(!target?.closest)return;
    if(target.closest('.gca-category-page'))area.current='content';
    else if(target.closest('.gca-sidebar-host')){area.current='sidebar';enterContent.current=false;}
  };
  // Native SidebarNavigation supplies this callback (part of its discovery
  // signature in @decky/ui). It replaces the route instead of stacking pages.
  const navigatePage=useRef<((route:string)=>void)|undefined>(undefined);
  const bindNavigatePage=useCallback((navigate:(route:string)=>void)=>{navigatePage.current=navigate;},[]);
  const french=useSyncExternalStore(subscribeUILanguage,getUILanguage,getUILanguage)==='fr';
  const select=(next:SettingsSelection)=>{
    const valid=visibleSettingsSelection(settingsSelection(next.category,next.tab),faceplateConnected);
    if(valid.category!==current.current.category||valid.tab!==current.current.tab){
      revision.current++;current.current=valid;
    }
    remembered.current[valid.category]=valid.tab;
    setRequestedSelection(previous=>previous.category===valid.category&&previous.tab===valid.tab?previous:valid);
  };
  useEffect(()=>{
    // SidebarNavigation replaces its route itself. Do not reset the remembered
    // subtab when that native navigation updates the optional route parameter.
    if(initialSource===nativeRoute.current){nativeRoute.current=undefined;return;}
    if(initial)select(initial);
  },[initialSource]);
  useEffect(()=>{
    // Unplugging while focused in this category must not strand Steam's native focus scope.
    if(faceplateConnected||requestedSelection.category!=='faceplate')return;
    const fallback=settingsSelection('display','daily'),route=settingsCategoryRoute('display');
    nativeRoute.current=route.split('/').pop();
    remembered.current.display=fallback.tab;
    enterContent.current=false;revision.current++;current.current=fallback;
    setRequestedSelection(fallback);
    if(navigatePage.current)navigatePage.current(route);
  },[faceplateConnected,requestedSelection.category]);
  const requestPage=(route:string)=>{
    const category=settingsCategoryFromRoute(route);if(!category)return;
    const next=visibleSettingsSelection(settingsSelection(category,remembered.current[category]),faceplateConnected);
    nativeRoute.current=settingsCategoryRoute(next.category).split('/').pop();
    if(next.category!==category&&navigatePage.current)navigatePage.current(settingsCategoryRoute(next.category));
    enterContent.current=false;
    select(next);
  };
  const open=(next:SettingsSelection)=>{
    const safe=visibleSettingsSelection(next,faceplateConnected);
    if(safe.category!==selection.category){
      const route=settingsCategoryRoute(safe.category);
      nativeRoute.current=route.split('/').pop();
      if(navigatePage.current)navigatePage.current(route);
      else Navigation.Navigate(route);
    }
    enterContent.current=area.current==='content';
    select(safe);
  };
  const step=(direction:number)=>switched(settingsStep(current.current,direction));
  const renderedRevision=revision.current;
  const isCurrent=(category:SettingsCategory,tab:string)=>revision.current===renderedRevision
    &&current.current.category===category&&current.current.tab===tab;
  const onButton=(event:GamepadEvent)=>{
    // Tabs handles shoulders in its own header/content. This fallback only
    // serves the sidebar and never moves focus out of it.
    if(event.defaultPrevented)return;
    if(event.detail.button===GamepadButton.BUMPER_LEFT||event.detail.button===GamepadButton.BUMPER_RIGHT){
      event.preventDefault();event.stopPropagation();step(event.detail.button===GamepadButton.BUMPER_LEFT?-1:1);
    }
  };
  return <SettingsPresentation selection={selection} onOpen={open}>
      <Focusable id="gca-settings-root" className="gca-settings" data-gca-active-category={selection.category} {...{focusable:false}} onButtonDown={onButton}
        onGamepadFocus={trackFocus} onFocusCapture={trackFocus}>
        <style>{SETTINGS_CSS}</style>
        <div className="gca-sidebar-host">
          <SidebarNavigation title="GabeCubeAura" disableRouteReporting
            {...{fnSetNavigateToPage:bindNavigatePage}}
            page={settingsCategoryRoute(selection.category)} onPageRequested={requestPage}
            pages={visibleSettingsCategories(faceplateConnected).map(item=>({
              title:translate(item.title,french?'fr':'en'),route:settingsCategoryRoute(item.id),identifier:item.id,
              hideTitle:true,padding:'none',
              content:<div className="gca-category-page" data-gca-category={item.id}>
                <div className="gca-tabs-host"><Tabs key={`${item.id}:${selection.tab}:${renderedRevision}`} autoFocusContents={enterContent.current} wrapAround={false} cancelSkipTabHeader
                  activeTab={selection.category===item.id?selection.tab:remembered.current[item.id]??item.tabs[0][0]}
                  onShowTab={(tab:string)=>{if(revision.current===renderedRevision&&current.current.category===item.id)switched(settingsSelection(item.id,tab));}}
                  tabs={item.tabs.map(tab=>({id:tab[0],title:french?tab[1]:tab[2],
                    footer:SETTINGS_TAB_INDICATOR,
                    content:<SettingsTabBody selection={settingsSelection(item.id,tab[0])} renderContent={renderContent} onOpen={open}
                      entry={entry} canEnter={()=>isCurrent(item.id,tab[0])&&area.current==='content'}/>}))}/></div>
              </div>,
            }))}/>
        </div>
      </Focusable>
  </SettingsPresentation>;
}

function SettingsTabBody({selection,renderContent,onOpen,entry,canEnter}:{selection:SettingsSelection;renderContent:Props['renderContent'];onOpen:(selection:SettingsSelection)=>void;entry:number;canEnter:()=>boolean}){
  const nav=useRef<SettingsNavHandle|undefined>(undefined);
  useEffect(()=>{
    if(!entry)return;
    return focusSettingsTab(()=>nav.current,canEnter,
      callback=>window.requestAnimationFrame(callback),id=>window.cancelAnimationFrame(id),GamepadButton.DIR_RIGHT);
  },[selection.category,selection.tab,entry]);
  // Native Tabs supplies the registered vertical ScrollPanel and focus history.
  // Mount only the active page through Steam's renderer, not 25 hidden readers.
  return <Focusable className="gca-content" data-gca-tab={selection.tab}
    {...{focusable:false,resetNavOnEntry:true,navRef:nav}} navEntryPreferPosition={NavEntryPositionPreferences.FIRST}>
    <DialogBody>{renderContent(selection,onOpen)}<SettingsHelpButton/></DialogBody>
  </Focusable>;
}
