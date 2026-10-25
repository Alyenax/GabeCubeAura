import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import {createElement, Fragment} from 'react';
import {dashboardContext, updateDashboardContext, dashboardRowOptions, dashboardRowUsesControllers} from '../../src/dashboard_settings';
import {translate} from '../../src/i18n';
import type {Status} from '../../src/types';

const legacy = {faceplate_dashboard_show_weather:true,faceplate_dashboard_show_bottom_row:true,
  faceplate_dashboard_bottom_mode:'today',faceplate_dashboard_game_session:true,
  faceplate_dashboard_battery_style:'percent',faceplate_dashboard_show_p2:false,
  faceplate_dashboard_show_clock:false,faceplate_dashboard_home_source:'weather',
  faceplate_dashboard_home_appid:0,faceplate:{routing:{routes:{home:'dashboard'}}}} as unknown as Status;

test('legacy Home and game selections stay distinct until explicitly edited',()=>{
  assert.equal(dashboardContext(legacy,'home').bottom_mode,'today');
  assert.equal(dashboardContext(legacy,'game').bottom_mode,'controllers');
  assert.equal(dashboardContext(legacy,'home').show_session,false);
  const contexts=updateDashboardContext(legacy,'game',{bottom_mode:'next_hour',show_weather:false});
  const edited={...legacy,faceplate_dashboard_contexts:contexts};
  assert.equal(dashboardContext(edited,'home').bottom_mode,'today');
  assert.equal(dashboardContext(edited,'home').show_weather,true);
  assert.equal(dashboardContext(edited,'game').bottom_mode,'next_hour');
  assert.equal(dashboardContext(edited,'game').show_weather,false);
  assert.equal(legacy.faceplate_dashboard_contexts,undefined);
});

const source=readFileSync(new URL('../../src/components/FaceplateDashboardSettings.tsx',import.meta.url),'utf8');
const flush=async()=>{for(let n=0;n<10;n++)await Promise.resolve();};
function harness(){
  let status=structuredClone(legacy);
  const calls:{key:string;value:any}[]=[];
  const context=vm.createContext({React:{createElement,Fragment},
    useState:(value:any)=>[value,()=>{}],useEffect:()=>{},
    useSettingsPresentation:()=>({open:()=>{}}),Navigation:{},
    dashboardContext,updateDashboardContext,dashboardRowOptions,dashboardRowUsesControllers,
    setSetting:async(key:string,value:any)=>{calls.push({key,value});status={...status,[key]:value};return status;},
    PanelSection:'section',PanelSectionRow:'row',Localized:'localized',SettingsDetails:'details',
    ToggleField:'toggle',DropdownItem:'dropdown',ButtonItem:'button'});
  const body=source.replace(/^import .*$/gm,'').replace(/export function /g,'function ');
  vm.runInContext(ts.transpileModule(body,{compilerOptions:{jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2020}}).outputText+
    '\nthis.render=FaceplateDashboardSettings;',context);
  function nodes(node:any):any[]{
    if(!node)return[];
    if(Array.isArray(node))return node.flatMap(nodes);
    if(typeof node.type==='function')return nodes(node.type(node.props));
    return [node,...nodes(node.props?.children)];
  }
  return {calls,render(){return nodes(context.render({status,setStatus:(next:Status)=>{status=next;}}));},
    controls(scope:'home'|'game'){
      const group=this.render().find(n=>n.props?.['data-dashboard-context']===scope);
      return nodes(group);
    }};
}

test('actual Dashboard controls write only their context and do not need a running game',async()=>{
  const ui=harness();
  const rows=ui.render().filter(n=>n.type==='section').map(n=>n.props.title);
  assert.deepEqual(rows,['Dashboard at Home','Dashboard in game']);
  ui.controls('game').find(n=>n.props?.label==='Bottom row content').props.onChange({data:'next_hour'});
  await flush();
  assert.equal(ui.calls[0].key,'faceplate_dashboard_contexts');
  assert.equal(ui.calls[0].value.game.bottom_mode,'next_hour');
  assert.equal(ui.calls[0].value.home,undefined);
  ui.controls('home').find(n=>n.props?.label==='Show Dashboard bottom row').props.onChange(false);
  await flush();
  const value=ui.calls[1].value;
  assert.equal(value.home.show_bottom_row,false);
  assert.equal(value.game.show_bottom_row,true);
  assert.equal(value.game.bottom_mode,'next_hour');
  assert(!ui.controls('home').some(n=>n.props?.label==='Bottom row content'));
  assert(ui.controls('game').some(n=>n.props?.label==='Bottom row content'));
});

test('controllers have no optional session or player-count controls in either context',()=>{
  const ui=harness();
  assert(!ui.controls('game').some(n=>n.props?.label==='Show session time with one controller'));
  assert(!ui.render().some(n=>n.props?.label==='Show P2 when connected'));
  assert(!ui.render().some(n=>n.type==='details'));
  assert(!ui.controls('home').some(n=>n.props?.label==='Show session time with one controller'));
  for(const label of ['Dashboard in game','Bottom row content','Show session time with one controller'])
    assert.notEqual(translate(label,'fr'),label);
});


test('one additive selector keeps every prior row and gives new modes meaningful names',async()=>{
  const ui=harness();
  const selector=ui.controls('game').find(n=>n.props?.label==='Bottom row content');
  assert.deepEqual(Array.from(selector.props.rgOptions,(x:any)=>x.data),['next_hour','today','controllers','d','c','b','a','e']);
  assert(!ui.render().some(n=>n.props?.label==='In-game bottom row'));
  const home=ui.controls('home').find(n=>n.props?.label==='Bottom row content');
  assert.deepEqual(Array.from(home.props.rgOptions,(x:any)=>x.data),['next_hour','today','controllers']);
  for(const item of selector.props.rgOptions){
    assert(!/^[ABCDE] [·—-]|Existing behavio/i.test(item.label));
    assert.notEqual(translate(item.label,'fr'),item.label);
  }
  selector.props.onChange({data:'a'});await flush();
  assert.equal(ui.calls[0].value.game.game_row,'a');
  assert.equal(ui.calls[0].value.game.battery_style,'percent');
  assert.equal(ui.calls[0].value.home,undefined);
  assert.equal(ui.controls('game').filter(n=>n.props?.label==='Bottom row content').length,1);
  ui.controls('game').find(n=>n.props?.label==='Bottom row content').props.onChange({data:'today'});await flush();
  assert.equal(ui.calls[1].value.game.game_row,'existing');
  assert.equal(ui.calls[1].value.game.bottom_mode,'today');
  ui.controls('game').find(n=>n.props?.label==='Bottom row content').props.onChange({data:'e'});await flush();
  assert.equal(ui.calls[2].value.game.game_row,'e');
  assert.equal(ui.calls[2].value.game.bottom_mode,'today');
  assert(ui.controls('game').some(n=>n.props?.label==='Battery display'));
  assert(!ui.controls('game').some(n=>n.props?.label==='Show session time with one controller'));
});


test('weather notch position is independent and greyed only by the clock in its context',async()=>{
  const ui=harness();const label='Weather notch position';
  ui.controls('home').find(n=>n.props?.label===label).props.onChange({data:'center'});await flush();
  assert.equal(ui.calls[0].value.home.weather_position,'center');
  assert.equal(ui.calls[0].value.game,undefined);
  const clock=()=>ui.controls('home').find(n=>n.props?.label==='Home Dashboard Clock');
  clock().props.onChange(true);await flush();
  const locked=ui.controls('home').find(n=>n.props?.label===label);
  assert.equal(locked.props.disabled,true);assert.equal(locked.props.selectedOption,'right');
  assert.equal(ui.controls('game').find(n=>n.props?.label===label).props.disabled,false);
  clock().props.onChange(false);await flush();
  const restored=ui.controls('home').find(n=>n.props?.label===label);
  assert.equal(restored.props.disabled,false);assert.equal(restored.props.selectedOption,'center');
  assert.notEqual(translate(label,'fr'),label);
});

test('battery style is a direct independent control for every row containing controllers',async()=>{
  const ui=harness();
  const choose=(context:'home'|'game',data:string)=>ui.controls(context).find(n=>n.props?.label==='Bottom row content').props.onChange({data});
  choose('home','controllers');await flush();
  ui.controls('home').find(n=>n.props?.label==='Battery display').props.onChange({data:'bar'});await flush();
  for(const mode of ['controllers','c','a','e']){
    choose('game',mode);await flush();
    const style=ui.controls('game').find(n=>n.props?.label==='Battery display');
    assert(style);assert(!ui.controls('game').some(n=>n.type==='details'));
    style.props.onChange({data:'percent'});await flush();
    assert.equal(ui.calls.at(-1)!.value.game.battery_style,'percent');
    assert.equal(ui.calls.at(-1)!.value.home.battery_style,'bar');
    ui.controls('game').find(n=>n.props?.label==='Battery display').props.onChange({data:'bar'});await flush();
    assert.equal(ui.calls.at(-1)!.value.game.battery_style,'bar');
  }
  for(const mode of ['next_hour','today','d','b']){
    choose('game',mode);await flush();
    assert(!ui.controls('game').some(n=>n.props?.label==='Battery display'));
  }
  const options=ui.controls('game').find(n=>n.props?.label==='Bottom row content').props.rgOptions;
  for(const option of options.slice(0,2)){
    assert.match(option.label,/Weather/);assert.match(translate(option.label,'fr'),/Météo/);
  }
});
