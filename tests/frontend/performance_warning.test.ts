import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import {FACEPLATE_HOME_OPTIONS,FACEPLATE_GAME_OPTIONS} from '../../src/faceplate_choices';

const read=(name:string)=>readFileSync(new URL('../../'+name,import.meta.url),'utf8');
const source=read('src/index.tsx');

test('retired matrix Performance has no selectable route, consent or update cadence',()=>{
  assert(![...FACEPLATE_HOME_OPTIONS,...FACEPLATE_GAME_OPTIONS].some(o=>o.data==='performance'));
  assert.doesNotMatch(source,/confirmPerformanceRisk|requiresPerformanceConsent|faceplate_performance_|faceplate_performance_warning|performance_warning_view/);
  const api=read('src/api.ts');
  const route=api.slice(api.indexOf('export const setFaceplateRouting'),api.indexOf('export const setFaceplateVisualTheme'));
  assert.doesNotMatch(route,/performance|performanceRiskAccepted/);
  const kinds=read('src/types.ts').match(/export type FaceplateSceneThemeKind =[^;]+;/)![0];
  assert.doesNotMatch(kinds,/performance/);
});

test('native 17 LED Performance controls and thermal safety remain available',()=>{
  const home=source.slice(source.indexOf('const HOME_DISPLAY_OPTIONS'),source.indexOf('const FACEPLATE_DASHBOARD_SOURCE_OPTIONS'));
  const game=read('src/game_display_options.ts');
  assert.match(home,/data: "performance"/);assert.match(game,/data: "performance"/);
  assert.match(source,/showPage\("performance"\)/);
  assert.match(source,/Thermal protection/);
});

test('actual matrix route callback only persists the route and expected revision',async()=>{
  const callback=source.slice(source.indexOf('const changeFaceplateRoute ='),source.indexOf('const changeManualPosition ='));
  const calls:unknown[][]=[],busy:boolean[]=[],statuses:unknown[]=[];
  const status={faceplate:{routing:{preference_revision:7}}};
  const context=vm.createContext({status,setFaceplateActionBusy:(value:boolean)=>busy.push(value),
    setFaceplateRoutingMessage:()=>{},setStatus:(value:unknown)=>statuses.push(value),
    setFaceplateRouting:async(...args:unknown[])=>{calls.push(args);return status;}});
  vm.runInContext(ts.transpileModule(callback,{compilerOptions:{target:ts.ScriptTarget.ES2020}}).outputText+
    '\nthis.change=changeFaceplateRoute;',context);
  await context.change('dashboard','artwork-dashboard');
  assert.deepEqual(calls,[['dashboard','artwork-dashboard',7]]);
  assert.deepEqual(busy,[true,false]);assert.equal(statuses.length,1);
});

test('Home owns the single clock control and artwork has no per-game clock toggle',()=>{
  const dashboard=read('src/components/FaceplateDashboardSettings.tsx');
  assert.doesNotMatch(source,/dashboardShowClock|setDashboardShowClock|Artwork Dashboard clock|Weather Dashboard clock/);
  assert.match(dashboard,/Home Dashboard Clock/);
  assert.match(dashboard,/faceplate_dashboard_clock_choice === 'legacy-unreviewed'/);
  assert.match(dashboard,/write\('faceplate_dashboard_show_clock', true\)/);
  assert.match(dashboard,/write\('faceplate_dashboard_show_clock', false\)/);
  assert.match(dashboard,/Updating the clock requires new images/);
});
