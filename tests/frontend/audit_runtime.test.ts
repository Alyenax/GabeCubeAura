import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import {GameSessionLatch} from '../../src/game_session';
import {ParentalPlaytimeSubscription} from '../../src/parental_playtime';
import {ScreensaverContextQueue} from '../../src/screensaver_context_queue';
import {normalizeAppId} from '../../src/steam_app_id';
import {PlayerCityTransport} from '../../src/player_city_transport';

function mount(){
  const calls:any[]=[],callbacks:any[]=[];let registered=0;let finish!:(status:any)=>void;let requests=0;
  const status={artwork_source:'hero',launch_artwork_source:'hero'};
  const api=new Proxy({} as any,{get:(_target,name:string)=>async(...args:any[])=>{
    calls.push([name,...args]);
    if(name==='gameChanged'&&++requests===1)return new Promise(done=>{finish=done;});
    return name==='gameChanged'?status:{};
  }});
  const stub=new Proxy({} as any,{get:()=>class {}});
  const exports:any={};const context=vm.createContext({exports,module:{exports},console:{log(){},warn(...args:any[]){calls.push(['warn',...args]);}},Date,Promise,
    window:{setInterval:()=>1,clearInterval(){},setTimeout:()=>1,clearTimeout(){}},
    SteamClient:{Parental:{RegisterForParentalPlaytimeWarnings:(callback:any)=>{registered++;callbacks.push(callback);return {unregister(){registered--;}};}}},
    require:(name:string)=>name==='@decky/ui'?{Router:{},findModuleExport:()=>undefined}:name==='./api'?api:
      name==='./game_session'?{GameSessionLatch,selectObservedGame:()=>({appid:42,title:'Game'})}:
      name==='./parental_playtime'?{ParentalPlaytimeSubscription}:name==='./steam_app_id'?{normalizeAppId}:
      name==='./screensaver_context_queue'?{ScreensaverContextQueue}:name==='./player_city_transport'?{PlayerCityTransport}:stub});
  vm.runInContext(ts.transpileModule(readFileSync(new URL('../../src/runtime.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText+"\nexports.GabeCubeAuraRuntime=GabeCubeAuraRuntime;",context);
  const runtime=new exports.GabeCubeAuraRuntime();
  runtime.communityNotificationObserver={reset(){}};
  runtime.downloadLedOverride={recoverAfterRestart:async()=> 'inactive',stop(){}};
  runtime.registerSteamEvents=()=>{};runtime.renewSteamActivity=()=>{};runtime.pollScreensaver=async()=>{};
  return {runtime,calls,callbacks,registered:()=>registered,finish:()=>finish(status)};
}
const flush=async()=>{for(let i=0;i<16;i++)await Promise.resolve();};
for(const restart of [false,true])test(`GA-06: delayed gameChanged cannot outlive stop${restart?'/start':''}`,async()=>{
  const app=mount();app.runtime.start();await flush();app.runtime.stop();
  if(restart){app.runtime.start();await flush();}
  const before=app.calls.length,registered=app.registered();
  app.finish();await flush();
  assert.equal(app.calls.length,before);assert.equal(app.registered(),registered);
  assert.equal(app.registered(),restart?1:0);
  assert.equal(app.calls.filter(row=>row[0]==='getArtwork').length,restart?2:0);
  app.runtime.stop();for(const callback of app.callbacks)callback(15);await flush();
  assert.equal(app.registered(),0);assert.equal(app.calls.filter(row=>row[0]==='reportParentalMinutes').length,0);
});
