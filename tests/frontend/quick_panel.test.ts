import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {quickPanelState, quickOwnerLabel, quickFaceplateState} from '../../src/quick_panel';
import type {Status} from '../../src/types';
import {gameDisplayOptions} from '../../src/game_display_options';

function fixture(available=false, recent=false, display='artwork', appid=620) {
  return {faceplate:{available,recently_detected:recent},game:{appid,title:'Portal 2'},current_display:display} as Status;
}
test('never detected and expired faceplates have no quick controls',()=>{
  assert.deepEqual(quickPanelState(fixture()),{faceplateControls:false,gamePreview:'artwork'});
  const old=fixture(); delete old.faceplate.recently_detected;
  assert.equal(quickPanelState(old).faceplateControls,false);
  assert.equal(quickPanelState(fixture(false,false,'performance')).gamePreview,'performance');
});
test('recent disconnect hides Faceplate controls but keeps the game preview',()=>{
  assert.deepEqual(quickPanelState(fixture(false,true)),{faceplateControls:false,gamePreview:'artwork'});
});
test('connected, busy or powered-off hardware always keeps current game previews',()=>{
  for(const display of ['artwork','performance']) {
    const value=fixture(true,false,display);
    value.faceplate.busy=true; value.faceplate.powered=false;
    assert.deepEqual(quickPanelState(value),{faceplateControls:true,gamePreview:display});
  }
});
test('home has no game artwork but every in-game display retains it',()=>{
  assert.equal(quickPanelState(fixture(false,false,'artwork',0)).gamePreview,null);
  for(const display of ['audio_sync','weather','countdown','controller','customization'])
    assert.equal(quickPanelState(fixture(false,false,display)).gamePreview,'artwork');
});
test('compact panel uses read-only bounded artwork and native controls',()=>{
  const source=readFileSync(new URL('../../src/components/CompactQuickPanel.tsx',import.meta.url),'utf8');
  assert.match(source,/quickPanelState\(status\).faceplateControls/);
  assert.match(source,/getQuickArtwork\(status.game.appid,status.artwork_source\)/);
  assert.match(source,/request.busy\|\|request.found\|\|request.attempts>=3/);
  assert.match(source,/artRequest.current!==request/);
  assert.match(source,/gca-compact-led/);
  assert.doesNotMatch(source,/sampleArtwork|submitArtwork|Canvas|<video|PerformanceReadout/);
});

test('owner badge follows actual ownership, not enable toggle or provider',()=>{
  assert.equal(quickOwnerLabel({available:true,owner:'GabeCubeAura'}),'GabeCubeAura in control');
  assert.equal(quickOwnerLabel({available:true,owner:'Valve'}),'Steam in control');
  assert.equal(quickOwnerLabel({available:false,owner:'GabeCubeAura'}),'Light bar not detected');
});

test('quick faceplate claims only confirmed scenes and omits routes and raw error details',()=>{
  const value={faceplate_lab_enabled:true,faceplate:{available:true,powered:true,busy:false,
    routing:{effective_scene:'dashboard',desired_scene:'artwork',effective_content_key:'old',desired_content_key:'new',preparation:{state:'ready',error:''}},
    automation:{busy:false,queued:false,last_error:'',last_result:null}}} as unknown as Status;
  assert.equal(quickFaceplateState(value).confirmed,false);
  value.faceplate.routing.effective_content_key='new';
  assert.deepEqual(quickFaceplateState(value),{label:'dashboard',tone:'good',confirmed:true});
  value.faceplate.automation.last_error='Secret /home/deck/USB stack detail';
  assert.deepEqual(quickFaceplateState(value),{label:'Preparation failed',tone:'error',confirmed:false,hint:'See Faceplate settings'});
});

test('compact control order matches the approved preview',()=>{
 const source=readFileSync(new URL('../../src/components/CompactQuickPanel.tsx',import.meta.url),'utf8');
 const render=source.slice(source.indexOf('return <div id="gca-compact-root"'));
 let previous=-1;for(const name of['gca-compact-visual','gca-compact-master','gca-compact-light','gca-compact-timer','gca-compact-faceplate']){const n=render.indexOf(name);assert(n>previous,name);previous=n;}
 assert.doesNotMatch(render,/PerformanceReadout|QuickZone|QuickStatusCard/);
});

test('compact actions keep native focus targets and let Steam paint their states',()=>{
 const source=readFileSync(new URL('../../src/components/CompactQuickPanel.tsx',import.meta.url),'utf8');
 const css=readFileSync(new URL('../../src/components/compact_quick_style.ts',import.meta.url),'utf8');
 assert.match(source,/<DialogButton/);assert.match(source,/<QuickInlineChoice label=/);assert.match(source,/<SliderField/);assert.match(source,/<ToggleField/);
 assert.doesNotMatch(css,/ToggleRail|ToggleSwitch|SliderHandle|outline:|box-shadow:/);
 assert.doesNotMatch(source,/noFocusRing/,'Every compact action retains its native focus cue');
 assert.doesNotMatch(css,/#gca-compact-root\{[^}]*padding:/);assert.doesNotMatch(source,/document\.querySelector|\.focus\(|tabIndex|onKeyDown/);
});

test('branding gear opens general settings through a native labelled action',()=>{
  const source=readFileSync(new URL('../../src/index.tsx',import.meta.url),'utf8');
  const title=source.slice(source.indexOf('titleView:'),source.indexOf('content: <Content />'));
  assert.match(title,/justifyContent: 'space-between'/);
  assert.match(title,/<QuickSettingsAction \/>/);
  const action=source.slice(source.indexOf('function QuickSettingsAction'),source.indexOf('function QuickAccessContent'));
  assert.match(action,/<DialogButton className="gca-quick-gear" aria-label="Settings"/);
  assert.match(action,/<TbSettings/);
  assert.match(action,/Navigation.Navigate\("\/gabecubeaura\/settings"\)/);
  assert.doesNotMatch(action,/getStatus|setInterval|setTimeout|window.open/);
});

test('game menu has exactly two explicit Off choices and Steam control is only in Advanced',()=>{
  const source=readFileSync(new URL('../../src/index.tsx',import.meta.url),'utf8');
  const options=readFileSync(new URL('../../src/game_display_options.ts',import.meta.url),'utf8');
  assert.match(options,/data: "bar_off", label: "Light bar off"/);
  assert.match(options,/data: "displays_off", label: "Light bar \+ Faceplate off"/);
  assert.doesNotMatch(options,/data: "steam"|data: "blackout"|GabeCubeAura Off/);
  const homeOptions=source.slice(source.indexOf('const HOME_DISPLAY_OPTIONS'),source.indexOf('const FACEPLATE_DASHBOARD_SOURCE_OPTIONS'));
  assert.doesNotMatch(homeOptions,/data: "steam"|GabeCubeAura Off/);
  const advanced=source.slice(source.indexOf('showPage("advanced") ? <SettingsPart slot={[\'advanced.general\''),source.indexOf('slot="advanced.data"'));
  assert.match(advanced,/label="Steam control"/);
  assert.match(advanced,/<ToggleField label="Steam control"/);
  assert.match(advanced,/setSteamControl\(enabled\)/);
  assert.doesNotMatch(advanced,/setGameDisplay\(status.game.appid, 'steam'\)|setSetting\('home_display', 'steam'\)/);
  assert.match(source,/renderButtonValue=\{\(value\) => legacyGameDisplayLabel/);
});

test('in-game quick display retains the saved extension on disconnect and hides it for new selection',()=>{
  assert(gameDisplayOptions(true).some(option=>option.data==='faceplate_extension'));
  assert(!gameDisplayOptions(false).some(option=>option.data==='faceplate_extension'));
  assert(gameDisplayOptions(false, 'faceplate_extension').some(option=>option.data==='faceplate_extension'));
  for(const mode of ['screen_sync','audio_sync','artwork','customization','bar_off','displays_off'])
    assert(gameDisplayOptions(false).some(option=>option.data===mode),mode);
});

test('requested extinction never claims the panel is dark before power confirmation',()=>{
  const value=fixture(true,false,'displays_off');
  value.faceplate.powered=true; value.signalbar_enabled=true;
  assert.deepEqual(quickFaceplateState(value),{label:'Turning displays off…',tone:'waiting',confirmed:false});
});

test('compact panel replaces colour zones without changing global ownership semantics',()=>{
 const source=readFileSync(new URL('../../src/components/CompactQuickPanel.tsx',import.meta.url),'utf8');
 assert.doesNotMatch(source,/QuickZone|tone ===/);
 assert.equal(quickOwnerLabel({available:true,owner:'GabeCubeAura',signalbar_enabled:false}),'Displays off');
});

test('USB failure is actionable without exposing raw errors in the quick panel',()=>{
  const value={faceplate_lab_enabled:true,faceplate:{available:true,powered:true,busy:false,
    routing:{preparation:{state:'error',error:'no reply to type=0x01 cmd=0x0b'}},
    automation:{busy:false,queued:false,last_error:''}}} as unknown as Status;
  assert.deepEqual(quickFaceplateState(value),{label:'Transfer not confirmed',tone:'error',confirmed:false,hint:'No USB confirmation'});
});

test('a stopped runtime cannot reuse a stale GabeCubeAura owner badge',()=>{
  const status={available:true,owner:'GabeCubeAura',signalbar_enabled:true,debug:{engine_running:false}} as Status;
  assert.equal(quickOwnerLabel(status),'Display engine stopped');
  status.debug.engine_running=true;
  assert.equal(quickOwnerLabel(status),'GabeCubeAura in control');
});

test('sent without USB confirmation never claims that the selected scene is showing',()=>{
  const value={faceplate_lab_enabled:true,faceplate:{available:true,powered:true,busy:false,
    routing:{desired_scene:'dashboard',preparation:{state:'unconfirmed',error:'no reply'}},
    automation:{busy:false,queued:false,last_error:''}}} as unknown as Status;
  assert.deepEqual(quickFaceplateState(value),{label:'Sent · confirmation unavailable',tone:'waiting',confirmed:false});
});
