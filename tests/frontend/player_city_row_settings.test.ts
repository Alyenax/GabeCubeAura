import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import {createElement, Fragment} from 'react';
import {translate} from '../../src/i18n';
import {dashboardRowOptions, dashboardRowUsesControllers} from '../../src/dashboard_settings';

const source = readFileSync(new URL('../../src/components/PlayerCityRowSettings.tsx', import.meta.url), 'utf8');
test('native City selector writes its independent setting and preserves each choice', async () => {
  let status: any = {faceplate_dashboard_contexts:{game:{game_row:'b',battery_style:'percent'}}};
  const dashboardBefore = structuredClone(status.faceplate_dashboard_contexts);
  const calls: any[] = [];
  const context = vm.createContext({React:{createElement, Fragment},
    useState:(value:any) => [value, () => {}], dashboardRowOptions, dashboardRowUsesControllers,
    setSetting:async (key:string, value:any) => {
      calls.push({key,value}); return {...status,[key]:value};
    }, DropdownItem:'dropdown',PanelSectionRow:'row',Localized:'localized'});
  const body = source.replace(/^import .*$/gm, '').replace(/export function /g, 'function ');
  vm.runInContext(ts.transpileModule(body, {compilerOptions:{jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2020}}).outputText +
    '\nthis.render=PlayerCityRowSettings;', context);
  const nodes = (node:any):any[] => !node ? [] : Array.isArray(node) ? node.flatMap(nodes) :
    [node,...nodes(node.props?.children)];
  const selector = (disabled = false) => nodes(context.render({status,disabled,setStatus:(next:any)=>{status=next;}}))
    .find(n=>n.type==='dropdown');
  const controls = () => nodes(context.render({status,setStatus:(next:any)=>{status=next;}}));
  const control = (label:string) => controls().find(n=>n.props?.label===label);
  assert.equal(selector().props.selectedOption,'count');
  assert.equal(selector(true).props.disabled,true);
  assert.deepEqual(Array.from(selector().props.rgOptions,(o:any)=>o.data),['count','controllers','session','achievements','total','dashboard']);
  assert.equal(translate(selector().props.label,'fr'),'Ligne inférieure de Players City');
  const expected = ['Nombre de joueurs uniquement','Joueurs + manette','Joueurs + temps de session','Joueurs + trophées','Joueurs + temps total','Sans nombre de joueurs'];
  assert.deepEqual(Array.from(selector().props.rgOptions,(o:any)=>translate(o.label,'fr')),expected);
  assert.notEqual(translate(selector().props.description,'fr'),selector().props.description);
  assert(!control('Battery display'));
  for(const choice of ['session','achievements','total','controllers']) {
    await selector().props.onChange({data:choice});
    assert.equal(calls.at(-1).key,'faceplate_player_city_row');
    assert.equal(selector().props.selectedOption,choice);
  }
  assert.equal(control('Battery display').props.selectedOption,'percent');
  await control('Battery display').props.onChange({data:'bar'});
  assert.equal(calls.at(-1).key,'faceplate_player_city_battery_style');
  assert.equal(control('Battery display').props.selectedOption,'bar');
  const controlsInOrder = controls().filter(n=>n.type==='dropdown').map(n=>n.props.label);
  assert.deepEqual(controlsInOrder,['Players City bottom row','Battery display']);
  assert(!control('Bottom row content'));
  await selector().props.onChange({data:'dashboard'});
  assert.deepEqual(Array.from(control('Bottom row content').props.rgOptions,(o:any)=>({...o})),dashboardRowOptions(true));
  assert.equal(control('Bottom row content').props.selectedOption,'controllers');
  assert.equal(control('Battery display').props.selectedOption,'bar');
  for(const choice of ['next_hour','today','controllers','a','b','c','d','e']) {
    await control('Bottom row content').props.onChange({data:choice});
    assert.equal(calls.at(-1).key,'faceplate_player_city_dashboard_row');
    assert.equal(control('Bottom row content').props.selectedOption,choice);
    assert.equal(Boolean(control('Battery display')),['controllers','a','c','e'].includes(choice));
  }
  await control('Battery display').props.onChange({data:'bar'});
  assert.equal(calls.at(-1).key,'faceplate_player_city_battery_style');
  await selector().props.onChange({data:'session'});
  assert(!control('Bottom row content')); assert(!control('Battery display'));
  await selector().props.onChange({data:'dashboard'});
  assert.equal(control('Bottom row content').props.selectedOption,'e');
  assert.equal(control('Battery display').props.selectedOption,'bar');
  await selector().props.onChange({data:'count'});
  assert(!control('Bottom row content')); assert(!control('Battery display'));
  await selector().props.onChange({data:'controllers'});
  assert.equal(control('Battery display').props.selectedOption,'bar');
  assert.deepEqual(status.faceplate_dashboard_contexts,dashboardBefore);
});
