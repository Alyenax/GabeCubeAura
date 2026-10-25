import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import {createElement,Fragment} from 'react';
import {translate} from '../../src/i18n';
import {SETTINGS_TAB_INDICATOR} from '../../src/settings_navigation';
import {SETTINGS_CATEGORIES,SETTINGS_ALIASES,SETTINGS_ROUTE_PATTERN,settingsCategoryRoute,settingsCategoryFromRoute,settingsSources,settingsSelection,settingsStep,visibleSettingsCategories,visibleSettingsSelection,SETTINGS_SLOTS,settingsSlotVisible} from '../../src/settings_structure';
const index=readFileSync(new URL('../../src/index.tsx',import.meta.url),'utf8');
const shell=readFileSync(new URL('../../src/components/SimpleSettings.tsx',import.meta.url),'utf8');
const walk=(node:any):any[]=>Array.isArray(node)?node.flatMap(walk):node&&typeof node==='object'?[node,...walk(node.props?.children)]:[];
const nativeTabs=(page:any)=>walk(page.content).find(n=>n.type==='tabs');
test('six lighting/settings categories and 19 native tabs use the documented native containers',()=>{
  assert.deepEqual(SETTINGS_CATEGORIES.map(item=>item.title),['Display Light','Signals light','Weather','Faceplate Jsaux','Updates','Advanced']);
  assert.equal(SETTINGS_CATEGORIES.flatMap(item=>item.tabs).length,19);
  for(const item of SETTINGS_CATEGORIES)for(const tab of item.tabs){
    const choice=settingsSelection(item.id,tab[0]);assert(settingsSources(choice).length);
  }
  assert.match(shell,/<SidebarNavigation/);assert.match(shell,/<Tabs key=/);assert.match(shell,/autoFocusContents=\{enterContent.current\}/);
  const executable=shell.replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/[^\n]*/g,'');
  assert.doesNotMatch(executable,/takeArtworkNativeFocus|getGamepadNavigationTrees|\.focus\(|onCancelButton|onGamepadDirection|setInterval|fetch\(|getStatus\(/);
  assert.doesNotMatch(shell,/flow-children|gca-scroll|gca-subnav|gca-bumper/);
});
test('all 16 lighting/settings deep links share one optional-parameter route without remounting the sidebar',()=>{
  assert.equal(Object.keys(SETTINGS_ALIASES).length,16);assert.equal(SETTINGS_ROUTE_PATTERN,'/gabecubeaura/settings/:source?');
  for(const[page,selection]of Object.entries(SETTINGS_ALIASES))assert(settingsSources(selection,page,page,page).includes(page as any),page);
  for(const category of SETTINGS_CATEGORIES)assert.equal(settingsCategoryFromRoute(settingsCategoryRoute(category.id)),category.id);
  assert.equal(settingsCategoryFromRoute('/routes/steam/not-gca'),undefined);
  assert.match(index,/useParams<\{source\?:string\}>/);
  assert.match(index,/routerHook.addRoute\(SETTINGS_ROUTE_PATTERN, GabeCubeAuraSettings/);
  assert.doesNotMatch(index,/<SimpleSettings key=|LegacySettingsPage|SettingsGroup|LAB58_LIGHT_BAR_PAGES/);
});
test('explicit slots retain all valid destinations and reachable nested gates',()=>{
  for(const[slot,path]of Object.entries(SETTINGS_SLOTS)){const[category,tab]=path.split('/');const selection=settingsSelection(category,tab);assert.equal(`${selection.category}/${selection.tab}`,path,slot);assert(settingsSlotVisible(selection,slot));}
  const ast=ts.createSourceFile('index.tsx',index,99,true,4);
  function inspect(node:ts.Node,allowed:Set<string>|null){
    if(ts.isJsxElement(node)&&node.openingElement.tagName.getText(ast)==='SettingsPart'){
      const prop=node.openingElement.attributes.properties.find(p=>ts.isJsxAttribute(p)&&p.name.text==='slot') as ts.JsxAttribute;
      const value=prop.initializer!;let slots:string[]=[];
      if(ts.isStringLiteral(value))slots=[value.text];else if(ts.isJsxExpression(value)&&value.expression&&ts.isArrayLiteralExpression(value.expression))slots=value.expression.elements.map(item=>(item as ts.StringLiteral).text);
      assert(slots.length);for(const slot of slots)assert(slot in SETTINGS_SLOTS,slot);
      const paths=new Set(slots.map(slot=>SETTINGS_SLOTS[slot]));allowed=allowed?new Set([...allowed].filter(path=>paths.has(path))):paths;assert(allowed.size);
    }ts.forEachChild(node,child=>inspect(child,allowed));
  }inspect(ast,null);
});
function harness(initiallyConnected=true){
  const hooks:any[]=[];let cursor=0,connected=initiallyConnected;
  const effects:Array<()=>void>=[];
  const context=vm.createContext({exports:{},React:{createElement,Fragment},Focusable:'focusable',SidebarNavigation:'sidebar',Tabs:'tabs',
    DialogBody:'native-dialog-body',SettingsPresentation:'presentation',SettingsHelpButton:'help',SETTINGS_CSS:'',SETTINGS_CATEGORIES,settingsSelection,settingsStep,settingsCategoryRoute,settingsCategoryFromRoute,visibleSettingsCategories,visibleSettingsSelection,SETTINGS_TAB_INDICATOR,
    getUILanguage:()=> 'fr',translate,subscribeUILanguage:()=>()=>{},useSyncExternalStore:(_s:any,get:any)=>get(),
    useState:(initial:any)=>{const i=cursor++;if(!(i in hooks))hooks[i]=typeof initial==='function'?initial():initial;return[hooks[i],(next:any)=>{hooks[i]=typeof next==='function'?next(hooks[i]):next;}];},
    useRef:(initial:any)=>{const i=cursor++;return hooks[i]??={current:initial};},useEffect:(fn:()=>void)=>{cursor++;effects.push(fn);},useCallback:(fn:any)=>fn,
    Navigation:{Navigate:()=>{}},
    GamepadButton:{BUMPER_LEFT:5,BUMPER_RIGHT:6},
  });
  const ast=ts.createSourceFile('shell.tsx',shell,99,true,4),body=ast.statements.filter(n=>!ts.isImportDeclaration(n)).map(n=>n.getText(ast)).join('\n');
  vm.runInContext(ts.transpileModule(body,{compilerOptions:{jsx:ts.JsxEmit.React,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,context);
  const render=()=>{cursor=0;effects.length=0;const tree=context.exports.SimpleSettings({faceplateConnected:connected,renderContent:()=>createElement('content')});return{tree,sidebar:walk(tree).find(n=>n.type==='sidebar'),root:walk(tree).find(n=>n.props?.className==='gca-settings')};};
  return{render,setConnected:(value:boolean)=>{connected=value;},flushEffects:()=>{for(const effect of effects.splice(0))effect();}};
}
test('native sidebar receives contiguous pages, native tabs and no custom B/direction trap',()=>{
  const app=harness(),{tree,sidebar,root}=app.render();
  assert.equal(sidebar.props.pages.length,6);assert.equal(sidebar.props.disableRouteReporting,true);assert.equal(root.props.focusable,false);
  assert.equal(root.props.onCancelButton,undefined);assert.equal(root.props.onGamepadDirection,undefined);
  assert.equal(root.props.onKeyDown,undefined,'only shoulders select subtabs, not keyboard page shortcuts');
  assert.equal(walk(tree).some(n=>n.type==='voice-session'),false);
  for(const page of sidebar.props.pages){
    assert.equal(typeof page,'object');assert.equal(page.hideTitle,true);assert.equal(page.padding,'none');
    const tabs=walk(page.content).find(n=>n.type==='tabs');assert(tabs);assert.equal(tabs.props.autoFocusContents,false);
    assert.equal(tabs.props.wrapAround,false,'native row must not loop D-pad movement at the first/last header');
    assert.equal(tabs.props.cancelSkipTabHeader,true,'B must never target disabled tab headers');
    for(const tab of tabs.props.tabs){assert.equal(tab.footer.focusable,false);assert.equal(tab.footer.preferredFocus,false);}
    assert(tabs.props.tabs.every((tab:any)=>tab.content.props.selection.tab===tab.id));
  }
  sidebar.props.onPageRequested('/gabecubeaura/settings/gabe');
  assert.equal(app.render().sidebar.props.page,settingsCategoryRoute('display'));
  assert.equal(SETTINGS_ALIASES.gabe,undefined);
});
test('native-handled shoulders are never processed twice and sidebar fallback preserves its focus',()=>{
  const app=harness();let value=app.render();
  const event=(prevented=false)=>({detail:{button:6},defaultPrevented:prevented,preventDefault(){this.defaultPrevented=true;},stopPropagation(){}});
  value.root.props.onButtonDown(event(true));value=app.render();assert.equal(nativeTabs(value.sidebar.props.pages[0]).props.activeTab,'daily');
  value.root.props.onButtonDown(event());value=app.render();assert.equal(nativeTabs(value.sidebar.props.pages[0]).props.activeTab,'effects');
  assert.equal(value.sidebar.props.page,settingsCategoryRoute('display'));
});
test('explicit tab switches request first content only while content owns focus',()=>{
 const app=harness();let value=app.render();
 const tab=()=>nativeTabs(value.sidebar.props.pages[0]);
 assert.equal(tab().props.tabs[0].content.props.entry,0);
 value.root.props.onGamepadFocus({target:{closest:(selector:string)=>selector==='.gca-category-page'?{}:null}});
 tab().props.onShowTab('effects');value=app.render();assert.equal(tab().props.tabs[1].content.props.entry,1);
 value.root.props.onGamepadFocus({target:{closest:(selector:string)=>selector==='.gca-sidebar-host'?{}:null}});
 tab().props.onShowTab('sync');value=app.render();assert.equal(tab().props.tabs[2].content.props.entry,1);
 assert.equal(tab().props.tabs[2].content.props.canEnter(),false);
});
test('every subtab stops at both ends, including repeated shoulders and sidebar fallback',()=>{
  for(const item of SETTINGS_CATEGORIES){
    for(let index=0;index<item.tabs.length;index++){
      const choice=settingsSelection(item.id,item.tabs[index][0]);
      assert.equal(settingsStep(choice,-1).tab,item.tabs[Math.max(0,index-1)][0]);
      assert.equal(settingsStep(choice,1).tab,item.tabs[Math.min(item.tabs.length-1,index+1)][0]);
    }
    let choice=settingsSelection(item.id);
    for(let press=0;press<20;press++)choice=settingsStep(choice,-1);
    assert.equal(choice.tab,item.tabs[0][0]);
    for(let press=0;press<20;press++)choice=settingsStep(choice,1);
    assert.equal(choice.tab,item.tabs[item.tabs.length-1][0]);
  }
  const app=harness();let value=app.render();
  const event=(button:number)=>({detail:{button},defaultPrevented:false,preventDefault(){this.defaultPrevented=true;},stopPropagation(){}});
  for(let press=0;press<12;press++){value.root.props.onButtonDown(event(6));value=app.render();}
  assert.equal(nativeTabs(value.sidebar.props.pages[0]).props.activeTab,'profiles');
  for(let press=0;press<12;press++){value.root.props.onButtonDown(event(5));value=app.render();}
  assert.equal(nativeTabs(value.sidebar.props.pages[0]).props.activeTab,'daily');
  const left=event(11);value.root.props.onButtonDown(left);
  assert.equal(left.defaultPrevented,false,'D-pad left must remain available to native parent navigation');
});
test('explicit category links replace the native route before selecting the requested subtab',()=>{
  const app=harness();let value=app.render();const routes:string[]=[];
  value.sidebar.props.fnSetNavigateToPage((route:string)=>{routes.push(route);value.sidebar.props.onPageRequested(route);});
  value.tree.props.onOpen({category:'weather',tab:'animations'});
  value=app.render();assert.equal(value.sidebar.props.page,settingsCategoryRoute('weather'));
  assert.equal(nativeTabs(value.sidebar.props.pages[2]).props.activeTab,'animations');
  assert.deepEqual(routes,[settingsCategoryRoute('weather')]);
  value.tree.props.onOpen({category:'weather',tab:'forecast'});
  assert.equal(routes.length,1,'changing a subtab must not create a history entry');
});
test('native transition lifecycle and settings geometry are left to Steam',()=>{
 const theme=readFileSync(new URL('../../src/settings_theme.ts',import.meta.url),'utf8');
 assert.doesNotMatch(theme,/transition:|transition-duration|transform:|sidebarColumn|tabHeader|tabContent/);
});
test('Steam owns the settings heading, sidebar width and category titles',()=>{
 const {tree,sidebar}=harness().render();
 assert.equal(walk(tree).filter(n=>n.type==='header').length,0);
 assert.equal(sidebar.props.title,'GabeCubeAura');
 assert.notEqual(sidebar.props.showTitle,false);
 for(const page of sidebar.props.pages)assert.equal(page.hideTitle,true);
});

test('native Settings remove disconnected JSAUX immediately, then restore on connection',()=>{
  const app=harness(true);let view=app.render();
  assert.equal(view.sidebar.props.pages.length,6);
  const routes:string[]=[];
  view.sidebar.props.fnSetNavigateToPage((route:string)=>routes.push(route));
  view.sidebar.props.onPageRequested(settingsCategoryRoute('faceplate'));
  assert.equal(app.render().sidebar.props.page,settingsCategoryRoute('faceplate'));
  app.setConnected(false);view=app.render();
  assert.equal(view.sidebar.props.page,settingsCategoryRoute('display'));
  assert.equal(view.sidebar.props.pages.length,5);
  assert(view.sidebar.props.pages.every((page:any)=>page.identifier!=='faceplate'));
  app.flushEffects();view=app.render();
  assert.deepEqual(routes,[settingsCategoryRoute('display')]);
  app.setConnected(true);view=app.render();
  assert.equal(view.sidebar.props.pages.length,6);
  assert.equal(view.sidebar.props.page,settingsCategoryRoute('display'),'never auto-open JSAUX upon reconnect');
  view.tree.props.onOpen({category:'faceplate',tab:'artwork'});
  assert.equal(app.render().sidebar.props.page,settingsCategoryRoute('faceplate'));
});
test('hardware-specific links cannot open a disconnected Settings page',()=>{
  const app=harness(false);let view=app.render();const routes:string[]=[];
  view.sidebar.props.fnSetNavigateToPage((route:string)=>routes.push(route));
  view.tree.props.onOpen({category:'faceplate',tab:'maintenance'});
  view=app.render();
  assert.equal(view.sidebar.props.page,settingsCategoryRoute('display'));
  assert.equal(routes.length,0);
  view.sidebar.props.onPageRequested(settingsCategoryRoute('faceplate'));
  assert.equal(app.render().sidebar.props.page,settingsCategoryRoute('display'));
});


test('Lab198 retires each native Tabs scope and rejects callbacks from every retired instance',()=>{
 const app=harness();let value=app.render();const tabs=()=>nativeTabs(value.sidebar.props.pages[0]);
 const first=tabs(),oldBody=first.props.tabs[0].content;
 first.props.onShowTab('effects');value=app.render();const second=tabs();
 assert.notEqual(second.key,first.key,'A fresh native scope cannot retain outgoing transition/history');
 assert.equal(oldBody.props.canEnter(),false,'Old page cannot take focus after a switch');
 first.props.onShowTab('profiles');value=app.render();assert.equal(tabs().props.activeTab,'effects','Late callback cannot rebound');
 tabs().props.onShowTab('daily');value=app.render();assert.equal(tabs().props.activeTab,'daily');
 assert.notEqual(tabs().key,first.key,'Returning to the same tab still gets a fresh native lifetime');
 first.props.onShowTab('sync');second.props.onShowTab('profiles');value=app.render();
 assert.equal(tabs().props.activeTab,'daily','Neither old lifetime may select a later page');
});
test('Lab198 rapid sidebar shoulders advance from the latest committed selection without batching rebounds',()=>{
 const app=harness();let value=app.render();
 const press=(button:number)=>value.root.props.onButtonDown({detail:{button},defaultPrevented:false,preventDefault(){this.defaultPrevented=true;},stopPropagation(){}});
 press(6);press(6);press(6);value=app.render();
 assert.equal(nativeTabs(value.sidebar.props.pages[0]).props.activeTab,'profiles');
 for(let i=0;i<100;i++){press(i%2?6:5);value=app.render();assert.equal(nativeTabs(value.sidebar.props.pages[0]).props.activeTab,i%2?'profiles':'sync');}
 assert.equal(nativeTabs(value.sidebar.props.pages[0]).props.autoFocusContents,false);
});
test('Lab198 native sidebar focus cancels content entry without relying on fake PageListColumn classes',()=>{
 const app=harness();let value=app.render();
 value.root.props.onGamepadFocus({target:{closest:(selector:string)=>selector==='.gca-category-page'?{}:null}});
 nativeTabs(value.sidebar.props.pages[0]).props.onShowTab('effects');value=app.render();
 const body=nativeTabs(value.sidebar.props.pages[0]).props.tabs[1].content;
 assert.equal(body.props.canEnter(),true);assert.equal(nativeTabs(value.sidebar.props.pages[0]).props.autoFocusContents,true);
 value.root.props.onGamepadFocus({target:{closest:(selector:string)=>selector==='.gca-sidebar-host'?{}:null}});
 assert.equal(body.props.canEnter(),false);
 nativeTabs(value.sidebar.props.pages[0]).props.onShowTab('sync');value=app.render();
 assert.equal(nativeTabs(value.sidebar.props.pages[0]).props.autoFocusContents,false);
});


test('ordinary lighting, timer, ambience and update destinations survive removal of vocal routes',()=>{
  for(const [source,category,tab] of [['routing','display','daily'],['profiles','display','profiles'],['countdown','signals','timers'],['weather','weather','forecast'],['updates','updates','install']]){
    assert.deepEqual(SETTINGS_ALIASES[source],{category,tab});
  }
  for(const legacy of ['gabe','voice','assistant','decky-vocal-assistant']){
    assert.equal(settingsCategoryFromRoute('/gabecubeaura/settings/'+legacy),undefined);
    assert.equal(SETTINGS_ALIASES[legacy],undefined);
  }
  assert.doesNotMatch(index,/GabeAssistantPanel|startGabeActions|GabeSettingsSession|page === "gabe"/);
  assert.doesNotMatch(shell,/GabeSettingsSession|Voice Assistant|category==='voice'/);
  assert.match(index,/startTimerActions\(\)/);assert.match(index,/timerActions.stop\(\)/);
});

test('retired Compatibility destinations resolve to General and expose no old controls',()=>{
 assert.deepEqual(settingsSelection('advanced','compatibility'),{category:'advanced',tab:'general'});
 assert.equal('advanced.compatibility' in SETTINGS_SLOTS,false);
 const source=readFileSync(new URL('../../src/index.tsx',import.meta.url),'utf8');
 assert.doesNotMatch(source,/CompatibilityPanel|COMPANION_PRIORITY_OPTIONS|Show TW3-SteamRGB and StripMine controls|Coordinate LED ownership/);
});
