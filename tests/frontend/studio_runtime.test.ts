import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import * as screensaver from '../../src/steam_screensaver';
import * as screensaverQueue from '../../src/screensaver_context_queue';

// Execute the production observer without starting Steam or a real backend.
// No player, Storage API, iframe or Studio module is needed anymore.
function harness(){
  const signals:any[]=[],listeners:any[]=[];
  let active=true,available=true,read:()=>Promise<unknown>=async()=>({Body:()=>({active:()=>active})});
  const service={GetActiveState:()=>read(),RegisterForNotifyActiveStateChanged:(callback:any)=>{
    listeners.push(callback);return {unregister:()=>{}};
  }};
  const api={setScreenSyncContext:async(...args:any[])=>{signals.push(args);}};
  const stub=new Proxy({}, {get:()=>class {}});
  const source=readFileSync(new URL('../../src/runtime.ts',import.meta.url),'utf8');
  const code=ts.transpileModule(source,{
    compilerOptions:{target:ts.ScriptTarget.ES2020,module:ts.ModuleKind.CommonJS}}).outputText;
  const exports:any={};
  const context=vm.createContext({exports,module:{exports},console,Promise,Date,
    window:{setTimeout,clearTimeout},SteamClient:{},
    require:(name:string)=>name==='@decky/ui'?{findModuleExport:()=>available?service:undefined,Router:{}}:
      name==='./api'?api:name==='./steam_screensaver'?screensaver:
      name==='./screensaver_context_queue'?screensaverQueue:stub});
  vm.runInContext(code+'\nexports.Subject=GabeCubeAuraRuntime;',context);
  const runtime=new exports.Subject();runtime.alive=true;
  return {runtime,source,signals,listeners,setActive:(value:boolean)=>{active=value;},
    setRead:(value:()=>Promise<unknown>)=>{read=value;},
    unavailable:()=>{available=false;runtime.screensaverService=undefined;}};
}

test('native observer follows any Steam screensaver without a Studio player or bridge',async()=>{
  const h=harness();await h.runtime.pollScreensaver();
  assert.deepEqual(h.signals[0],['steam-screensaver',true,'available','poll']);
  h.setActive(false);await h.runtime.pollScreensaver();
  assert.deepEqual(h.signals.at(-1),['steam-screensaver',false,'available','poll']);
  assert.doesNotMatch(h.source,/cinema_bridge|setCinemaContext|cinemaFrames|SteamClient\.Storage|studioFrameMessage/);
});

test('native observer reports unavailable and invalid responses without inventing activation',async()=>{
  const h=harness();h.unavailable();await h.runtime.pollScreensaver();
  assert.equal(h.signals[0][1],false);assert.equal(h.signals[0][2],'unavailable');
  const other=harness();other.setRead(async()=>({state:'not-a-supported-shape'}));
  await other.runtime.pollScreensaver();
  assert.equal(other.signals[0][1],false);assert.equal(other.signals[0][2],'error');
});

test('native notification immediately reports Steam exit while polling remains a fallback',async()=>{
  const h=harness();await h.runtime.pollScreensaver();
  assert.equal(h.listeners.length,1);
  h.listeners[0]({Body:()=>({active:()=>false})});await Promise.resolve();
  assert.deepEqual(h.signals.at(-1),['steam-screensaver',false,'available','notification']);
});

test('late native response after teardown cannot revive a screensaver activation',async()=>{
  const h=harness();let finish!:(value:unknown)=>void;
  h.setRead(()=>new Promise(resolve=>{finish=resolve;}));
  const pending=h.runtime.pollScreensaver();h.runtime.alive=false;
  finish({active:true});await pending;
  assert.equal(h.signals.length,0);
});

test('late active poll cannot overwrite a newer native Steam exit notification',async()=>{
  const h=harness();let finish!:(value:unknown)=>void;
  h.setRead(()=>new Promise(resolve=>{finish=resolve;}));
  const pending=h.runtime.pollScreensaver();
  h.listeners[0]({active:false});await Promise.resolve();
  finish({active:true});await pending;
  assert.equal(h.signals.length,1);
  assert.deepEqual(h.signals[0],['steam-screensaver',false,'available','notification']);
});

test('a notification from an invalidated Steam service is ignored',async()=>{
  const h=harness();await h.runtime.pollScreensaver();
  h.unavailable();const before=h.signals.length;
  h.listeners[0]({active:false});await Promise.resolve();
  assert.equal(h.signals.length,before);
});
