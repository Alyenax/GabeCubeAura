import assert from 'node:assert/strict';
import test from 'node:test';
import type {Status} from '../../src/types';
import {finishSetupWithFaceplate,setupDisplayConfirmed,setupActivationMessage} from '../../src/setupActivation';

function state(confirmed=false):Status{return {
  game:{appid:0},signalbar_enabled:true,faceplate_lab_enabled:true,current_display:'weather',
  faceplate_setup_completed:true,faceplate_dashboard_home_source:'weather',
  faceplate:{available:true,powered:confirmed,delivery:{state:confirmed?'confirmed':'idle'},
    power_recovery:{suspended:false,route_state:'idle'},routing:{routes:{home:'weather',game:'artwork'},
      desired_scene:'weather',effective_scene:confirmed?'weather':'artwork',desired_content_key:'new',
      effective_content_key:confirmed?'new':'old',preparation:{state:confirmed?'ready':'pending'}}},
} as Status;}
function fixture(states:Status[]){let now=0,applied=0,reads=0,waiting=0,alive=true;const published:Status[]=[];
 return {deps:{apply:async()=>{applied++;return states.shift()!;},read:async()=>{reads++;return states.shift()!;},
 publish:(s:Status)=>published.push(s),alive:()=>alive,waiting:()=>waiting++,now:()=>now,pause:async(ms:number)=>{now+=ms;},timeoutMs:1500},
 published,counts:()=>({applied,reads,waiting}),kill:()=>{alive=false;}};
}
test('queued Off and an old visible image cannot finish setup before the selected receipt',async()=>{
 const f=fixture([state(),state(),state(true)]);
 const result=await finishSetupWithFaceplate({faceplate_requested:true},f.deps);
 assert.equal(result?.faceplate.powered,true);assert.deepEqual(f.counts(),{applied:1,reads:2,waiting:2});
 assert.equal(f.published[0].faceplate.powered,false);
});
test('old confirmed scene or mismatched content does not count as the requested display',()=>{
 const s=state(true);assert.equal(setupDisplayConfirmed(s),true);
 s.faceplate.routing.effective_scene='artwork';assert.equal(setupDisplayConfirmed(s),false);
 s.faceplate.routing.effective_scene='weather';s.faceplate.routing.effective_content_key='old';assert.equal(setupDisplayConfirmed(s),false);
 s.faceplate.routing.effective_content_key='new';s.faceplate.powered=false;assert.equal(setupDisplayConfirmed(s),false);
});
test('no Faceplate consent closes normally without waiting or activating again',async()=>{
 for(const choice of [false,null,undefined]){
  const f=fixture([state()]);await finishSetupWithFaceplate({faceplate_requested:choice},f.deps);
  assert.deepEqual(f.counts(),{applied:1,reads:0,waiting:0});
 }
});
test('a missing receipt stays retryable with an explicit bounded error in both languages',async()=>{
 const f=fixture([state(),state(),state()]);
 await assert.rejects(finishSetupWithFaceplate({faceplate_requested:true},f.deps),error=>{
  assert.match(setupActivationMessage(error,true),/guide reste ouvert/);
  assert.match(setupActivationMessage(error,false),/Setup stays open/);return true;
 });assert.equal(f.counts().applied,1);
});
test('disconnect, global Off and final missing confirmation never become success',async()=>{
 for(const change of [(s:Status)=>{s.faceplate.available=false;},(s:Status)=>{s.signalbar_enabled=false;},
   (s:Status)=>{s.faceplate.power_recovery.route_state='unconfirmed';}]){
  const s=state();change(s);const f=fixture([s]);
  await assert.rejects(finishSetupWithFaceplate({faceplate_requested:true},f.deps));assert.equal(f.counts().reads,0);
 }
});
test('leaving the guide stops confirmation reads without another backend application',async()=>{
 const f=fixture([state()]);f.deps.pause=async()=>f.kill();
 assert.equal(await finishSetupWithFaceplate({faceplate_requested:true},f.deps),undefined);
 assert.deepEqual(f.counts(),{applied:1,reads:0,waiting:1});
});
test('automatic receipt retry remains one backend setup request',async()=>{
 const missing=state();missing.faceplate.delivery!.state='unconfirmed';missing.faceplate.power_recovery.route_state='retry-waiting';
 const f=fixture([missing,state(true)]);await finishSetupWithFaceplate({faceplate_requested:true},f.deps);
 assert.equal(f.counts().applied,1);assert.equal(f.counts().reads,1);
});
