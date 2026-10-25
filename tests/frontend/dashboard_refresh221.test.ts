import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import fs from 'node:fs';
import ts from 'typescript';
import * as statsModule from '../../src/steam_dashboard_stats';
import {PlayerCityTransport} from '../../src/player_city_transport';
import {normalizeAppId} from '../../src/steam_app_id';

const source=ts.transpileModule(fs.readFileSync(new URL('../../src/runtime.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
function fixture(){
 let now=100000,done=12,total=2251;let deferred:((value:boolean)=>void)|undefined;
 const calls:any[]=[],callbacks:{appid:number;run:()=>void;closed:boolean}[]=[],timers=new Map<number,{run:()=>void;at:number}>();let next=1;
 const details={GetAppDetails:()=>({achievements:{nAchieved:done,nTotal:48}}),RegisterForAppData:(appid:number,run:()=>void)=>{const item={appid,run,closed:false};callbacks.push(item);run();return{unregister(){item.closed=true;}};}};
 class Stub {selectApp(){} stop(){} reset(){} }
 const stubs=new Proxy({} as any,{get:()=>Stub});
 const exports:any={};const context=vm.createContext({exports,module:{exports},console,Promise,Date:class extends Date {static now(){return now;}},
   window:{setTimeout:(run:()=>void,delay:number)=>{const id=next++;timers.set(id,{run,at:now+delay});return id;},clearTimeout:(id:number)=>timers.delete(id),clearInterval(){}},
   appStore:{GetAppOverviewByAppID:()=>({minutes_playtime_forever:total})},
   require:(name:string)=>name==='@decky/ui'?{Router:{},findModuleExport:()=>details}:
     name==='./api'?new Proxy({reportDashboardStats:async(...args:any[])=>{calls.push(JSON.parse(JSON.stringify(args)));if(deferred!==undefined)return new Promise<boolean>(resolve=>{deferred=resolve;});return true;},triggerEvent:async(...args:any[])=>{calls.push(['event',...args]);return true;}} as any,{get:(obj,key)=>obj[key]||(()=>Promise.resolve(true))}):
     name==='./steam_dashboard_stats'?statsModule:name==='./player_city_transport'?{PlayerCityTransport}:name==='./steam_app_id'?{normalizeAppId}:stubs});
 vm.runInContext(source+'\nexports.Subject=GabeCubeAuraRuntime;',context);
 const subject=new exports.Subject();subject.alive=true;subject.desired={appid:620,title:'Portal',launchSequence:0};subject.flushGameState=async()=>{};
 const settle=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
 return {subject,calls,callbacks,timers,settle,done:(value:number)=>{done=value;},total:(value:number)=>{total=value;},
  hold:()=>{deferred=()=>{};},release:()=>{const resolve=deferred;deferred=undefined;resolve?.(true);},
  advance:async(milliseconds:number)=>{now+=milliseconds;const due=[...timers].filter(([,t])=>t.at<=now);for(const [id,timer] of due){timers.delete(id);timer.run();}await settle();}};
}

test('Real runtime keeps native app details registered and reports each achievement without waiting for throttle',async()=>{
 const f=fixture();await f.subject.syncDashboardStats(true);await f.settle();
 assert.equal(f.callbacks.length,1);assert.equal(f.callbacks[0].appid,620);
 f.done(13);f.callbacks[0].run();await f.settle();assert.equal(f.calls.at(-1)[1].achieved,13);
 f.done(14);f.callbacks[0].run();await f.settle();assert.equal(f.calls.at(-1)[1].achieved,14);
 const before=f.calls.length;await f.subject.syncDashboardStats();assert.equal(f.calls.length,before);
 await f.advance(20000);await f.subject.syncDashboardStats();assert.equal(f.calls.length,before+1,'Heartbeat keeps samples fresh beyond the backend 45-second expiry');
 f.subject.clearDashboardSubscription();assert(f.callbacks[0].closed);const count=f.calls.length;f.callbacks[0].run();await f.settle();assert.equal(f.calls.length,count);
});

test('An app-data change during an in-flight report is delivered immediately after it',async()=>{
 const f=fixture();await f.subject.syncDashboardStats(true);await f.settle();f.hold();
 const first=f.subject.syncDashboardStats(true);f.done(13);f.callbacks[0].run();await f.settle();
 const count=f.calls.length;f.release();await first;await f.settle();assert.equal(f.calls.length,count+1);assert.equal(f.calls.at(-1)[1].achieved,13);
});

test('Actual achievement event forces bounded delayed reads when the notification arrives before updated counts',async()=>{
 const f=fixture();await f.subject.syncDashboardStats(true);await f.settle();
 f.subject.emitLightEvent('achievement');await f.settle();assert.equal(f.timers.size,3);
 f.done(13);await f.advance(250);assert.equal(f.calls.at(-1)[1].achieved,13);
 f.subject.emitLightEvent('achievement');await f.settle();assert.equal(f.timers.size,3,'Bursts replace rather than multiply retry timers');
 f.done(14);await f.advance(3000);assert.equal(f.calls.at(-1)[1].achieved,14);assert.equal(f.timers.size,0);
 f.subject.emitLightEvent('screenshot');assert.equal(f.timers.size,0);
});

test('Game change, same-AppID return and stop fence old callbacks and cancel achievement retries',async()=>{
 const f=fixture();await f.subject.syncDashboardStats(true);await f.settle();f.subject.emitLightEvent('achievement');await f.settle();
 f.subject.requestGame(570,'Dota','test',true);assert(f.callbacks[0].closed);assert.equal(f.timers.size,0);
 await f.subject.syncDashboardStats(true);await f.settle();assert.equal(f.callbacks[1].appid,570);
 f.subject.requestGame(620,'Portal','test',true);await f.subject.syncDashboardStats(true);await f.settle();const before=f.calls.length;
 f.done(99);f.callbacks[0].run();await f.settle();assert.equal(f.calls.length,before,'Old callback cannot revive after A→B→A');
 f.subject.emitLightEvent('achievement');await f.settle();
 f.subject.parental={stop(){}};f.subject.communityNotificationObserver={reset(){}};f.subject.downloadLedOverride={stop(){}};f.subject.screensaverContext={submit:async()=>true};
 f.subject.stop();assert.equal(f.timers.size,0);assert(f.callbacks.every(c=>c.closed));const after=f.calls.length;
 for(const c of f.callbacks)c.run();await f.advance(10000);assert.equal(f.calls.length,after);
});
