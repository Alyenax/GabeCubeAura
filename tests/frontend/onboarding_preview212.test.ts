import assert from 'node:assert/strict';
import test from 'node:test';
import {createSetupPreview} from '../../src/onboardingPreview';
import type {Status} from '../../src/types';
const deferred=<T,>()=>{let resolve!:(v:T)=>void;const promise=new Promise<T>(r=>resolve=r);return {promise,resolve};};
const state=(owner:string,preset='moderate',active=true)=>({display_preset_preview:{owner,preset,active,on_bar:true,remaining_s:10,phase:'',colors:[[10,20,30]]}} as Status);
const flush=()=>new Promise(r=>setImmediate(r));
function fixture(){
 const frames:any[]=[],calls:any[]=[],timers=new Set<()=>void>();let owner='',reading=deferred<Status>(),pendingRead=false,now=0;
 const session=createSetupPreview({start:async(preset,id)=>{owner=id;calls.push(['start',preset,id]);return state(id,preset);},
  stop:async id=>{calls.push(['stop',id]);},read:async()=>{calls.push(['read']);return pendingRead?reading.promise:state(owner);},
  frame:frame=>frames.push(frame),failed:()=>calls.push(['failed']),now:()=>now,
  interval:((fn:()=>void,ms:number)=>{assert.equal(ms,250);timers.add(fn);return fn;}) as any,clear:((fn:()=>void)=>timers.delete(fn)) as any});
 return {session,frames,calls,timers,tick:()=>{for(const fn of timers)fn();},delayRead:()=>{pendingRead=true;return reading;},advance:()=>{now=13000;}};
}
test('each of four actual RPC selections publishes dynamic preview frames and stops its own timer',async()=>{
 for(const preset of ['moderate','atmosphere','signals','immersive'] as const){
  const f=fixture();await f.session.start(preset);assert.equal(f.frames[0].preset,preset);assert.equal(f.timers.size,1);
  f.tick();await flush();assert.equal(f.frames.length,2);await f.session.stop();assert.equal(f.timers.size,0);
  assert.deepEqual(f.calls.at(-1),['stop',f.session.owner]);
 }
});
test('unmount ignores delayed read, serializes old stop before a new setup, and skips cancelled starts',async()=>{
 const f=fixture();await f.session.start('signals');const pending=f.delayRead();f.tick();f.tick();
 assert.equal(f.calls.filter(c=>c[0]==='read').length,1,'one status RPC in flight');
 const count=f.frames.length,stopped=f.session.stop(),next=fixture();await next.session.start('immersive');await stopped;
 pending.resolve(state(f.session.owner,'signals'));await flush();assert.equal(f.frames.length,count);
 const cancelled=fixture(),start=cancelled.session.start('moderate'),stop=cancelled.session.stop();await start;await stop;
 assert.equal(cancelled.calls.length,0);
 await next.session.stop();
});
test('late start cannot paint after exit and its cleanup precedes the next physical preview',async()=>{
 const order:string[]=[],pending=deferred<Status>(),frames:any[]=[];
 const old=createSetupPreview({start:async()=>{order.push('old-start');return pending.promise;},stop:async()=>{order.push('old-stop');},read:async()=>state(''),frame:s=>frames.push(s),failed:()=>assert.fail()});
 const starting=old.start('signals');await flush();const stopping=old.stop();
 const next=createSetupPreview({start:async(_,id)=>{order.push('next-start');return state(id,'immersive',false);},stop:async()=>{},read:async()=>state(''),frame:()=>{},failed:()=>assert.fail()});
 const newStart=next.start('immersive');pending.resolve(state(old.owner,'signals'));await starting;await stopping;await newStart;
 assert.deepEqual(order,['old-start','old-stop','next-start']);assert.equal(frames.length,0);await next.stop();
});
test('expired or superseded preview cannot leave a polling loop or show another preview',async()=>{
 const f=fixture();await f.session.start('moderate');f.advance();f.tick();assert.equal(f.timers.size,0);assert.equal(f.frames.at(-1).active,false);await f.session.stop();
 const g=fixture();await g.session.start('signals');const pending=g.delayRead();g.tick();pending.resolve(state('unrelated','immersive'));await flush();
 assert.equal(g.timers.size,0);assert.equal(g.frames.at(-1).active,false);await g.session.stop();
});
