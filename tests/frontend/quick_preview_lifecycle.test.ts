import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import { createElement,Fragment } from 'react';
import {faceplateTransferNotice} from '../../src/faceplate_transfer';
import {presetSummary,quickAmbienceOptions} from '../../src/lighting_presets';
import {faceplateBrightnessNotice} from '../../src/faceplate_power';
import {trailingSetting} from '../../src/trailingSetting';
import {gameDisplayOptions} from '../../src/game_display_options';
import {quickFaceOptions,homeFaceChoice,isDashboardChoice,showArtworkPreparationHint} from '../../src/faceplate_choices';

const source = readFileSync(new URL('../../src/components/CompactQuickPanel.tsx', import.meta.url), 'utf8');
const componentSource = source.slice(source.indexOf('export function CompactQuickPanel')).replace('export function','function');
const javascript = ts.transpileModule(componentSource, { compilerOptions: {
  target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.React,
} }).outputText;

// Execute the shipped component with deterministic hook/RPC doubles. No Steam,
// Decky, DOM, timers, worker or serial access is needed for lifecycle checks.
function harness(faceplateControls=false, rejectRoute=false) {
  let cursor = 0;
  const values: any[] = [], dependencies: any[] = [], cleanup: (() => void)[] = [];
  const effects: (() => void)[] = [];
  const requests: { appid: number; resolve: (value: any) => void }[] = [];
  const voiceRequests:{resolve:(value:any)=>void}[]=[],scheduled:(()=>void)[]=[],voiceChanges:boolean[]=[];
  const writes:boolean[]=[],settingRequests:{args:any[];resolve:(value:any)=>void;reject:(reason:any)=>void}[]=[],saved:any[]=[];
  const navigations:string[]=[];const routeRequests:any[]=[];const powerRequests:boolean[]=[];
  const displayRequests:{appid:number;display:string}[]=[];
  const trailingJobs=new Map<number,()=>void>();let nextJob=0;
  let savedVoice:any;
  const context = vm.createContext({ React: { createElement,Fragment }, console,
    useState(initial: any) { const i = cursor++; if (!(i in values)) values[i] = initial;
      return [values[i], (next: any) => { values[i] = next; }]; },
    useRef(initial: any) { const i = cursor++; if (!(i in values)) values[i] = { current: initial }; return values[i]; },
    useEffect(effect: () => (() => void), deps: any[]) { const i = cursor++;
      if (!dependencies[i] || deps.some((item, j) => item !== dependencies[i][j])) {
        cleanup[i]?.(); dependencies[i] = deps; effects.push(() => { cleanup[i] = effect(); });
      }
    },
    faceplateTransferNotice,playerCitySummary:()=>'',COMPACT_QUICK_CSS:'',faceplateBrightnessNotice,presetSummary,quickAmbienceOptions,gameDisplayOptions,quickFaceOptions,homeFaceChoice,isDashboardChoice,showArtworkPreparationHint,quickFaceChoice:()=> 'dashboard',clock:()=>'',personalTimer:()=>({active:false,remaining_seconds:0}),
    setTimeout:(fn:()=>void)=>scheduled.push(fn),clearTimeout(){},getGabeStatus:()=>new Promise(resolve=>voiceRequests.push({resolve})),
    setGabeListening:async(value:boolean)=>{voiceChanges.push(value);savedVoice={voice_ready:true,busy:false,phase:'idle',config:{enabled:value,wake_enabled:value}};return savedVoice;},
    setLightBarBrightness:(...args:any[])=>new Promise((resolve,reject)=>settingRequests.push({args,resolve,reject})),
    setSetting:(...args:any[])=>new Promise((resolve,reject)=>settingRequests.push({args,resolve,reject})),
    setFaceplateRouting:async(home:string,game:string,revision:number)=>{routeRequests.push({home,game,revision});if(rejectRoute)throw new Error('route failed');return {faceplate:{routing:{routes:{home,game},preference_revision:revision+1},powered:true}};},
    setFaceplatePower:async(powered:boolean)=>{powerRequests.push(powered);return {faceplate:{powered}};},
    setGameDisplay:async(appid:number,display:string)=>{displayRequests.push({appid,display});return {game:{appid},current_display:display};},
    trailingSetting:(save:any,delay:number)=>trailingSetting(save,delay,fn=>{const id=++nextJob;trailingJobs.set(id,fn);return id as any;},id=>{trailingJobs.delete(id as any);}),
    reportQuickUI(){},TimerEditor:'timer-editor',CompactLedPreview:'led-preview',
    quickPanelState: () => ({faceplateControls}),
    getQuickArtwork: (appid: number) => new Promise(resolve => requests.push({ appid, resolve })),
    Navigation:{CloseSideMenus(){},Navigate(){}},ButtonItem:'dva-launcher',PanelSection:'section-native',PanelSectionRow:'row-native',Field:'field-native',DialogButton:'button',SliderField:'slider',ToggleField:'toggle',QuickInlineChoice:'select',Focusable:'div',Localized:'Localized',
  });
  vm.runInContext(javascript + '\nthis.component = CompactQuickPanel;', context);
  return {routeRequests,powerRequests,navigations,requests,voiceRequests,scheduled,voiceChanges,writes,settingRequests,displayRequests,saved,async flushSliders(){const jobs=[...trailingJobs.values()];trailingJobs.clear();for(const job of jobs)job();await flush();},render(appid: number, extra = {}, active=true) {
    cursor = 0;
    const tree = context.component({ active, status: {onboarding_completed:true,game:{appid,title:'Game '+appid},artwork_source:'hero',countdown:{active:false},light_bar_day_brightness:128,faceplate_brightness:100,signalbar_enabled:true,active:true,faceplate_lab_enabled:true,faceplate:{available:true,powered:true,automation:{busy:false,queued:false},routing:{routes:{home:'dashboard',game:'artwork'},preparation:{state:'idle'}}},thermal_protection:{active:false},timer_end_action:{phase:'idle'},...extra},setStatus:(value:any)=>saved.push(value),onMutationChange:(active:boolean)=>writes.push(active),colors:[],onOpenGame(){navigations.push('game');},onOpenSettings(){navigations.push('settings');},onOpenArtwork(){navigations.push('faceplate-artwork');} });
    for (const effect of effects.splice(0)) effect();
    return tree;
  }, unmount() { for (const fn of cleanup) fn?.(); } };
}
const flush = async () => { for (let n = 0; n < 5; n++) await Promise.resolve(); };

test('quick game display switches only the running game and hides unavailable extension',async()=>{
  const ui=harness(true);
  const choice=controls(ui.render(620,{current_display:'audio_sync'})).find(n=>n.props?.label==='In-game light bar');
  assert.equal(choice.props.selectedOption,'audio_sync');
  assert(choice.props.rgOptions.some((o:any)=>o.data==='faceplate_extension'));
  choice.props.onChange({data:'faceplate_extension'});await flush();await flush();
  assert.deepEqual(ui.displayRequests,[{appid:620,display:'faceplate_extension'}]);
  assert.equal(ui.saved[0].current_display,'faceplate_extension');
  assert.equal(ui.settingRequests.length,0,'No global default or ambience change');
  const disconnected=controls(ui.render(620,{faceplate:{available:false,routing:{routes:{game:'artwork'}}}})).find(n=>n.props?.label==='In-game light bar');
  assert(!disconnected.props.rgOptions.some((o:any)=>o.data==='faceplate_extension'));
  assert(!controls(ui.render(0)).some(n=>n.props?.label==='In-game light bar'));
  ui.unmount();
});
function image(tree: any): any {
  if (!tree) return null;
  if (Array.isArray(tree)) return tree.map(image).find(Boolean);
  if (tree.type === 'img') return {appid:Number(tree.props.alt.split(' ')[1]),data_uri:tree.props.src};
  return image(tree.props?.children);
}
test('quick artwork never duplicates an in-flight request or decodes on successful polling', async () => {
  const ui = harness(); ui.render(620);
  for (let n = 0; n < 8; n++) ui.render(620, { owner: 'Valve', faceplate: { available: true } });
  assert.equal(ui.requests.length, 1);
  ui.requests[0].resolve({ found: true, appid: 620, data_uri: 'data:image/jpeg;base64,thumbnail' }); await flush();
  for (let n = 0; n < 8; n++) assert.equal(image(ui.render(620)).appid, 620);
  assert.equal(ui.requests.length, 1); ui.unmount();
});
test('old-game and unmounted thumbnail results never become visible', async () => {
  const ui = harness(); ui.render(620); assert.ok(!image(ui.render(570)));
  assert.equal(ui.requests.length, 2);
  ui.requests[0].resolve({ found: true, appid: 620, data_uri: 'OLD' }); await flush();
  assert.ok(!image(ui.render(570)));
  ui.unmount(); ui.requests[1].resolve({ found: true, appid: 570, data_uri: 'LATE' }); await flush();
  assert.equal(ui.requests.length, 2);
});
test('late Steam cache retries only three times, and a new game resets that budget', async () => {
  const ui = harness(); ui.render(620);
  for (let n = 0; n < 3; n++) {
    ui.requests[n].resolve({ found: false, appid: 620 }); await flush(); ui.render(620);
  }
  for (let n = 0; n < 10; n++) ui.render(620);
  assert.equal(ui.requests.length, 3);
  ui.render(570); assert.equal(ui.requests.length, 4); ui.unmount();
});
test('quick refresh has no separate hardware probe or refresh loop',()=>{
  assert.doesNotMatch(source,/getFaceplateDeliveryStatus|setInterval|refreshQuickStatus/);
  assert.match(source,/getQuickArtwork/);
});
function controls(tree:any):any[]{return Array.isArray(tree)?tree.flatMap(controls):tree&&typeof tree==='object'?[tree,...controls(tree.props?.children)]:[];}
test('GCA quick panel has no vocal launcher, polling or microphone mutation',()=>{
  const ui=harness();const tree=ui.render(620);
  assert.equal(ui.voiceRequests.length,0);assert.equal(ui.voiceChanges.length,0);
  assert.equal(controls(tree).some(node=>node.type==='dva-launcher'),false);
  assert.doesNotMatch(source,/getGabeStatus|setGabeListening|Hands-free activation/);
  ui.unmount();
});

test('actual quick selection holds the read barrier through success/failure and rejects duplicate actions',async()=>{
  const ui=harness();
  const ambience=controls(ui.render(620)).find(node=>node.props?.label==='Ambience');
  ambience.props.onChange({data:'atmosphere'});await flush();
  ambience.props.onChange({data:'signals'});await flush();
  assert.deepEqual(ui.writes,[true]);
  assert.equal(ui.settingRequests.length,1,'One in-flight choice, no duplicate write');
  ui.settingRequests[0].resolve({display_preset:'atmosphere'});await flush();
  assert.deepEqual(ui.writes,[true,false]);
  assert.equal(ui.saved[0].display_preset,'atmosphere');
  ambience.props.onChange({data:'signals'});await flush();
  ui.settingRequests[1].reject(new Error('Failed save'));await flush();
  assert.deepEqual(ui.writes,[true,false,true,false]);
  const next=controls(ui.render(620));
  assert(next.some(node=>node.props?.role==='alert'),'Failed save remains visible');
  assert.equal(ui.saved.length,1,'Failed write cannot invent a saved selection');
  ui.unmount();
});

test('reproduces the old popup unmount: a callback from the destroyed panel cannot save',async()=>{
  const ui=harness();const choice=controls(ui.render(620)).find(node=>node.props?.label==='Ambience');
  ui.unmount();choice.props.onChange({data:'immersive'});await flush();
  assert.equal(ui.settingRequests.length,0);
  assert.doesNotMatch(source,/<DropdownItem|<Dropdown\s|showModal|showContextMenu/,
    'The compact panel delegates popup rendering to the retained native selector');
});

test('JSAUX brightness coalesces changes, ignores stale saves and flushes on panel close',async()=>{
 const ui=harness(true);
 const slider=controls(ui.render(620)).find(node=>node.props?.label==='JSAUX brightness');
 slider.props.onChange(75);slider.props.onChange(55);await ui.flushSliders();
 assert.deepEqual(ui.settingRequests.map(r=>r.args),[['faceplate_brightness',55]]);
 slider.props.onChange(35);
 ui.settingRequests[0].resolve({faceplate_brightness:55});await flush();
 assert.equal(ui.saved.length,0,'Old saved value cannot repaint a newer slider choice');
 assert.equal(controls(ui.render(620)).find(n=>n.props?.label==='JSAUX brightness').props.value,35);
 ui.unmount();await flush();
 assert.deepEqual(ui.settingRequests.map(r=>r.args),[['faceplate_brightness',55],['faceplate_brightness',35]]);
 ui.settingRequests[1].resolve({faceplate_brightness:35});await flush();
 assert.equal(ui.saved.length,0,'No stale UI update after panel exit');
 slider.props.onChange(20);await ui.flushSliders();assert.equal(ui.settingRequests.length,2,'Unmounted callback does nothing');
 assert.deepEqual(ui.writes,[true,false,true,false]);
});

test('JSAUX brightness failure is visible and retryable; missing/off/busy hardware never writes',async()=>{
 const ui=harness(true);
 let slider=controls(ui.render(620)).find(n=>n.props?.label==='JSAUX brightness');
 slider.props.onChange(50);await ui.flushSliders();ui.settingRequests[0].reject(Error('offline'));await flush();
 let tree=ui.render(620);assert(controls(tree).some(n=>n.props?.role==='alert'));
 slider=controls(tree).find(n=>n.props?.label==='JSAUX brightness');
 assert.equal(slider.props.value,100,'Failed save restores last confirmed brightness');
 slider.props.onChange(40);await ui.flushSliders();ui.settingRequests[1].resolve({faceplate_brightness:40});await flush();
 assert.equal(ui.saved[0].faceplate_brightness,40);
 for(const state of[{available:false},{busy:true},{powered:false}]){
  const control=controls(ui.render(620,{faceplate:{available:true,powered:true,...state,routing:{routes:{home:'dashboard',game:'artwork'}}}})).find(n=>n.props?.label==='JSAUX brightness');
  assert.equal(control.props.disabled,true);control.props.onChange(25);await ui.flushSliders();
 }
 assert.equal(ui.settingRequests.length,2);
 const absent=harness();assert(!controls(absent.render(620)).some(n=>n.props?.label==='JSAUX brightness'));
 ui.unmount();absent.unmount();
});

test('failed JSAUX brightness does not poison later ambience actions',async()=>{
 const ui=harness(true);
 controls(ui.render(620)).find(n=>n.props?.label==='JSAUX brightness').props.onChange(50);
 await ui.flushSliders();ui.settingRequests[0].reject(Error('offline'));await flush();
 controls(ui.render(620)).find(n=>n.props?.label==='Ambience').props.onChange({data:'festive'});
 for(let n=0;n<20;n++)await Promise.resolve();
 assert.deepEqual(ui.settingRequests[1].args,['display_preset','festive']);
 ui.settingRequests[1].resolve({display_preset:'festive'});await flush();
 assert.equal(ui.saved[0].display_preset,'festive');ui.unmount();
});


test('retained hidden QAM pauses artwork reads and never owns voice polling',async()=>{
 const ui=harness();ui.render(620,{},false);
 assert.equal(ui.requests.length,0);assert.equal(ui.voiceRequests.length,0);assert.equal(ui.scheduled.length,0);
 ui.render(620,{},true);assert.equal(ui.requests.length,1);assert.equal(ui.voiceRequests.length,0);
 ui.render(620,{},false);
 ui.requests[0].resolve({found:true,appid:620,data_uri:'OLD'});await flush();
 for(let n=0;n<4;n++)ui.render(620,{},false);
 assert.equal(ui.requests.length,1);assert.equal(ui.voiceRequests.length,0);
 ui.render(570,{},true);assert.equal(ui.requests.length,2,'Visibility permits one request for the current game');
 ui.unmount();
});


test('unfinished setup disables every compact control and rejects native callbacks',async()=>{
 const ui=harness(true);
 const tree=ui.render(620,{onboarding_completed:false});
 const actions=controls(tree).filter(n=>['button','toggle','slider','select'].includes(n.type));
 assert(actions.length>=8);
 for(const action of actions){
  assert.equal(action.props.disabled,true,action.props.label||action.props['aria-label']||action.props.children);
  action.props.onClick?.();
  action.props.onChange?.(action.type==='select'?{data:'atmosphere'}:50);
 }
 await ui.flushSliders();
 assert.deepEqual(ui.settingRequests,[]);assert.deepEqual(ui.displayRequests,[]);
 assert.deepEqual(ui.navigations,[]);assert.deepEqual(ui.writes,[]);
 assert(!controls(ui.render(620,{onboarding_completed:false})).some(n=>n.type==='timer-editor'));
 ui.unmount();
});

test('confirmation unlocks controls; resetting blocks retained callbacks and pending slider saves',async()=>{
 const ui=harness(true);
 ui.render(620,{onboarding_completed:false});
 const enabled=controls(ui.render(620,{onboarding_completed:true}));
 const actions=enabled.filter(n=>['button','toggle','slider','select'].includes(n.type));
 assert(actions.every(n=>n.props.disabled===false));
 const face=enabled.find(n=>n.props.label==='JSAUX brightness');
 const light=enabled.find(n=>n.props.label==='Brightness');
 face.props.onChange(55);light.props.onChange(50);
 ui.render(620,{onboarding_completed:false});
 for(const action of actions){action.props.onClick?.();action.props.onChange?.(action.type==='select'?{data:'atmosphere'}:50);}
 await ui.flushSliders();
 assert.equal(ui.settingRequests.length,0);assert.deepEqual(ui.navigations,[]);
 const reopened=controls(ui.render(620,{onboarding_completed:true}));
 assert.equal(reopened.find(n=>n.props.label==='JSAUX brightness').props.value,100);
 reopened.find(n=>n.props['aria-label']==='Game display…').props.onClick();
 assert.deepEqual(ui.navigations,['game']);
 reopened.find(n=>n.props.label==='Ambience').props.onChange({data:'signals'});
 for(let n=0;n<20;n++)await Promise.resolve();
 assert.deepEqual(ui.settingRequests[0].args,['display_preset','signals']);
 ui.settingRequests[0].resolve({display_preset:'signals'});await flush();ui.unmount();
});

test('locking while an action awaits a slider prevents its later RPC and stale status update',async()=>{
 const ui=harness(true),enabled=controls(ui.render(620));
 enabled.find(n=>n.props.label==='JSAUX brightness').props.onChange(55);await ui.flushSliders();
 enabled.find(n=>n.props.label==='Ambience').props.onChange({data:'signals'});await flush();
 ui.render(620,{onboarding_completed:false});
 ui.settingRequests[0].resolve({faceplate_brightness:55,onboarding_completed:true});
 for(let n=0;n<30;n++)await Promise.resolve();
 assert.equal(ui.settingRequests.length,1);assert.equal(ui.saved.length,0);
 ui.unmount();
});

test('Player City is game-only in the quick selector and saves the shared route revision',async()=>{
 const ui=harness(true);
 // The shipped component executes against the same persistence RPC as Settings.
 // Verify its exact saved Home/game values and revision.
 const node=controls(ui.render(620,{faceplate:{available:true,powered:true,routing:{routes:{home:'weather',game:'artwork'},preference_revision:7}}})).find(n=>n.props.label==='JSAUX screen');
 assert(node.props.rgOptions.some((o:any)=>o.data==='player-city'&&o.label==='Steam Players City'));
 node.props.onChange({data:'player-city'});for(let i=0;i<30;i++)await Promise.resolve();
 assert.deepEqual(ui.routeRequests,[{home:'weather',game:'player-city',revision:7}]);
 assert.equal(ui.saved[0].faceplate.routing.routes.game,'player-city');
 assert(!controls(ui.render(0)).find(n=>n.props.label==='JSAUX screen').props.rgOptions.some((o:any)=>o.data==='player-city'));
 ui.unmount();
});

test('Artwork Dashboard is selectable from another game route and preserves Home',async()=>{
 const ui=harness(true);
 const node=controls(ui.render(620,{faceplate:{available:true,powered:true,routing:{routes:{home:'native-clock',game:'weather'},preference_revision:8}}})).find(n=>n.props.label==='JSAUX screen');
 assert(node.props.rgOptions.some((o:any)=>o.data==='artwork-dashboard'));
 assert.equal(node.props.rgOptions.at(-1).data,'off');
 node.props.onChange({data:'artwork-dashboard'});await flush();await flush();
 assert.deepEqual(ui.routeRequests,[{home:'native-clock',game:'artwork-dashboard',revision:8}]);
 assert.equal(ui.settingRequests.length,0);ui.unmount();
});

test('Home Artwork Dashboard selects the saved background without changing the game route',async()=>{
 const ui=harness(true),routes={home:'weather',game:'player-city'};
 const node=controls(ui.render(0,{faceplate_dashboard_home_source:'weather',faceplate:{available:true,powered:true,routing:{routes,preference_revision:9}}})).find(n=>n.props.label==='JSAUX screen');
 node.props.onChange({data:'artwork-dashboard'});await flush();
 assert.equal(ui.settingRequests.length,0,'Background selection belongs to the route');await flush();
 assert.deepEqual(ui.routeRequests,[{home:'artwork-dashboard',game:'player-city',revision:9}]);ui.unmount();
});

test('Off remains a power-only shortcut at Home and in game',async()=>{
 for(const appid of [0,620]){
  const ui=harness(true),node=controls(ui.render(appid)).find(n=>n.props.label==='JSAUX screen');
  assert.equal(node.props.rgOptions.at(-1).data,'off');node.props.onChange({data:'off'});await flush();await flush();
  assert.deepEqual(ui.powerRequests,[false]);assert.equal(ui.routeRequests.length,0);assert.equal(ui.settingRequests.length,0);ui.unmount();
 }
});


test('Decky shows transfer progress and a settled result without extra reads or writes',()=>{
  const ui=harness(true);
  const panel:any={available:true,powered:true,phase:'uploading',delivery:{state:'sending'},
    automation:{busy:true,queued:false,last_error:''},
    routing:{routes:{home:'dashboard',game:'artwork'},desired_content_key:'new',effective_content_key:'old',preparation:{state:'preparing'}}};
  const extra={faceplate_lab_enabled:true,faceplate:panel};
  const notice=(tree:any)=>controls(tree).find(n=>n.props?.['data-faceplate-transfer']);
  const content=(tree:any):string=>typeof tree==='string'?tree:Array.isArray(tree)?tree.map(content).join(' '):content(tree?.props?.children??'');
  let tree=ui.render(0,extra);
  assert.match(content(notice(tree)),/Transferring to Faceplate… Please wait\./);
  assert.equal(notice(tree).props['aria-live'],'polite');
  assert.equal(notice(tree).props['data-faceplate-transfer'],'active');
  // Hidden panels/reopening consume the same supplied snapshot, without starting polling.
  ui.render(0,extra,false);tree=ui.render(0,extra,true);
  assert.equal(notice(tree).props['data-faceplate-transfer'],'active');
  panel.automation.busy=false;panel.phase='sent-unconfirmed';panel.delivery.state='unconfirmed';panel.routing.preparation.state='unconfirmed';
  tree=ui.render(0,extra);
  assert.equal(notice(tree).props['data-faceplate-transfer'],'settled');
  assert.match(content(notice(tree)),/Faceplate confirmation not received/);
  assert.doesNotMatch(content(notice(tree)),/Please wait/);
  panel.phase='artwork';panel.delivery.state='confirmed';panel.routing.preparation.state='ready';panel.routing.effective_content_key='new';
  assert.match(content(notice(ui.render(0,extra))),/Transfer confirmed by Faceplate/);
  panel.available=false;assert.equal(notice(ui.render(0,extra)),undefined);
  assert.equal(ui.requests.length,0);assert.equal(ui.settingRequests.length,0);
  assert.equal(ui.routeRequests.length,0);assert.equal(ui.powerRequests.length,0);
  assert.equal(ui.scheduled.length,0);ui.unmount();
});


test('a rejected new JSAUX choice cannot display the previous transfer confirmation',async()=>{
 const ui=harness(true,true);
 const faceplate:any={available:true,powered:true,phase:'dashboard',delivery:{state:'confirmed'},
   automation:{busy:false,queued:false,last_error:''},routing:{routes:{home:'dashboard',game:'artwork'},
   preference_revision:12,desired_content_key:'old',effective_content_key:'old',preparation:{state:'ready'}}};
 const extra={faceplate_lab_enabled:true,faceplate};
 const notice=(tree:any)=>controls(tree).find(n=>n.props?.['data-faceplate-transfer']);
 let tree=ui.render(0,extra);assert.ok(notice(tree),'Previous receipt is initially valid');
 controls(tree).find(n=>n.props?.label==='JSAUX screen').props.onChange({data:'artwork-dashboard'});
 await flush();await flush();tree=ui.render(0,extra);
 assert.equal(ui.routeRequests.length,1);assert.equal(ui.saved.length,0);
 assert(controls(tree).some(n=>n.props?.role==='alert'),'Failed choice remains explicit');
 assert.match(JSON.stringify(tree),/The JSAUX choice could not be applied/,'A post-save activation error must not claim the choice was not saved');
 assert.equal(notice(tree),undefined,'Old successful receipt cannot confirm the failed choice');
 faceplate.automation.busy=true;faceplate.phase='uploading';faceplate.delivery.state='sending';
 faceplate.routing.preparation.state='preparing';
 assert.equal(notice(ui.render(0,extra)).props['data-faceplate-transfer'],'active',
   'Authoritative ongoing transfer progress remains visible after a local choice error');
 ui.unmount();
});
