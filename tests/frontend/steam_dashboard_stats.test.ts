import assert from 'node:assert/strict';
import test from 'node:test';
import {steamDashboardStats, isSteamAppDetailsStore} from '../../src/steam_dashboard_stats';
import {PlayerCityTransport} from '../../src/player_city_transport';

test('read-only SteamUI fields provide totals and full achievement counters without requests',()=>{
  const overview={minutes_playtime_forever:2251};
  const details={achievements:{nAchieved:21,nTotal:25}};
  assert.deepEqual(steamDashboardStats(overview,details),{total_minutes:2251,achieved:21,achievements_total:25});
  assert.deepEqual(steamDashboardStats({minutes_playtime_forever:0},{achievements:{nAchieved:0,nTotal:0}}),
    {total_minutes:0,achieved:0,achievements_total:0});
  assert(isSteamAppDetailsStore({GetAppDetails(){},RegisterForAppData(){}}));
});
test('unknown, partial or invalid client facts never become invented zero counts',()=>{
  assert.deepEqual(steamDashboardStats(null,null),{});
  assert.deepEqual(steamDashboardStats({minutes_playtime_forever:'10'},{achievements:{nAchieved:26,nTotal:25}}),{});
  assert.deepEqual(steamDashboardStats({minutes_playtime_forever:12},{achievements:{nAchieved:12}}),{total_minutes:12});
});

test('actual background runtime publishes loaded Steam values and stops with its lifecycle',async()=>{
  const vm=await import('node:vm');const ts=await import('typescript');const fs=await import('node:fs');
  const moduleStats=await import('../../src/steam_dashboard_stats');
  const calls:any[]=[];const exports:any={};
  const stub=new Proxy({} as any,{get:()=>class {}});
  const context=vm.createContext({exports,module:{exports},console,Date,Promise,
    appStore:{GetAppOverviewByAppID:()=>({minutes_playtime_forever:2251})},
    require:(name:string)=>name==='@decky/ui'?{Router:{},findModuleExport:()=>({GetAppDetails:()=>({achievements:{nAchieved:21,nTotal:25}})})}:
      name==='./api'?{reportDashboardStats:async(...args:any[])=>{calls.push(JSON.parse(JSON.stringify(args)));return true;}}:
      name==='./steam_dashboard_stats'?moduleStats:name==='./player_city_transport'?{PlayerCityTransport}:stub});
  const code=ts.transpileModule(fs.readFileSync(new URL('../../src/runtime.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
  vm.runInContext(code+'\nexports.Subject=GabeCubeAuraRuntime;',context);
  const subject=new exports.Subject();subject.alive=true;subject.desired={appid:620};
  await subject.syncDashboardStats(true);
  assert.deepEqual(calls,[[620,{total_minutes:2251,achieved:21,achievements_total:25}]]);
  await subject.syncDashboardStats();assert.equal(calls.length,1);
  subject.alive=false;await subject.syncDashboardStats(true);assert.equal(calls.length,1);
});
