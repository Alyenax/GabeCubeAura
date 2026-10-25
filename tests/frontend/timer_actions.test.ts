import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

function mount(){
 const source=readFileSync(new URL('../../src/timer_actions.ts',import.meta.url),'utf8').replace(/^import .*;\s*$/gm,'');
 const events=new Map<string,Function>(),calls:any[]=[],actions:any[]=[],removed:string[]=[];
 let finish!:(value:any)=>void;
 const context=vm.createContext({exports:{},
  addEventListener:(name:string,fn:Function)=>{events.set(name,fn);return fn;},
  removeEventListener:(name:string)=>removed.push(name),
  callable:(name:string)=>async(...args:any[])=>{calls.push([name,...args]);return name==='timer_claim_action'?new Promise(resolve=>{finish=resolve;}):undefined;},
  Router:{MainRunningApp:{appid:42}},selectObservedGame:()=>({appid:42}),
  SteamClient:{System:{SuspendPC(){}},Apps:{TerminateApp(){}}},
  dispatchGabeAction:(action:any,options:any)=>actions.push({action,options}),
 });
 vm.runInContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,context);
 const service=context.exports.startTimerActions();
 return{events,calls,actions,removed,service,finish:(value:any)=>finish(value)};
}

test('ordinary timer power actions retain their own claimed Steam channel without vocal notifications',async()=>{
 const app=mount();assert.deepEqual([...app.events.keys()],['timer-action']);
 const token='a'.repeat(32),task=app.events.get('timer-action')!({token});
 app.finish({action:'sleep'});await task;
 assert.deepEqual(app.calls,[['timer_claim_action',token],['timer_acknowledge_action',token,true]]);
 assert.equal(app.actions.length,1);assert.equal(app.actions[0].options.currentAppId(),42);
 app.service.stop();assert.deepEqual(app.removed,['timer-action']);
});

test('closing the plugin while a timer claim is pending withdraws late dispatch',async()=>{
 const app=mount(),task=app.events.get('timer-action')!({token:'b'.repeat(32)});
 app.service.stop();app.finish({action:'sleep'});await task;
 assert.equal(app.actions.length,0);assert.equal(app.calls.length,1);
 await app.events.get('timer-action')!({token:'c'.repeat(32)});assert.equal(app.calls.length,1);
});

test('malformed timer tokens cannot claim or dispatch actions',async()=>{
 const app=mount();for(const token of ['',undefined,'not-a-token','a'.repeat(33)])await app.events.get('timer-action')!({token});
 assert.equal(app.calls.length,0);assert.equal(app.actions.length,0);app.service.stop();
});
