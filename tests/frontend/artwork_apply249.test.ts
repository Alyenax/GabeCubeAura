import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import vm from 'node:vm';

// Execute the actual shipped Apply callback, retaining refs across invocations.
const source=readFileSync(new URL('../../src/index.tsx',import.meta.url),'utf8');
const ast=ts.createSourceFile('index.tsx',source,99,true,4);
let declaration:ts.VariableDeclaration|undefined;
function find(n:ts.Node){if(ts.isVariableDeclaration(n)&&n.name.getText(ast)==='activatePrepared')declaration=n;ts.forEachChild(n,find);}find(ast);
const js=ts.transpileModule('const '+declaration!.getText(ast)+';this.apply=activatePrepared;',{
 compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
function harness(failStatus=false){
 const requests:{args:unknown[];resolve:(v:any)=>void;reject:(e:any)=>void}[]=[],messages:string[]=[],applied:string[]=[],busy:boolean[]=[],warnings:unknown[]=[],statuses:unknown[]=[];
 const request=(...args:unknown[])=>new Promise((resolve,reject)=>requests.push({args,resolve,reject}));
 const context=vm.createContext({useCallback:(fn:unknown)=>fn,STUDIO_UX:true,destination:'both',useForDashboardHome:false,
  applyingPrepared:{current:false},appliedSha:{current:''},deliveryKey:{current:''},prepareFocus:{current:'use-static'},
  status:{game:{appid:0}},setBusy:(v:boolean)=>busy.push(v),setStatus:(v:unknown)=>statuses.push(v),setAppliedDraftKey:(v:string)=>applied.push(v),
  commitFaceplateDashboardArtwork:request,activateFaceplateArtwork:request,
  getStatus:async()=>{if(failStatus)throw new Error('Python Exception');return {faceplate:{}};},
  getFaceplateDeliveryStatus:async()=>({routing:{desired_content_key:'new'}}),
  setDeliveryStatus(){},setDeliveryReadError(){},setDeliveryWatch(){},refreshArtworkState:async()=>{},refreshLibrary:async()=>{},
  setMessage:(v:string)=>messages.push(v),restoreArtworkFocus(){},console:{warn:(...v:unknown[])=>warnings.push(v)},
 });
 vm.runInContext(js,context);
 return {context,requests,messages,applied,busy,warnings,statuses,apply:(target='both')=>context.apply(620,'animated',{sha256:'new'},target)};
}
test('controller double activation sends one Apply and telemetry failure retains its successful result',async()=>{
 const ui=harness(true),first=ui.apply(),second=ui.apply();
 assert.equal(ui.requests.length,1);assert.equal(ui.context.applyingPrepared.current,true);
 assert.equal(ui.requests[0].args.at(-1),false,'Commit must not require full status telemetry');
 ui.requests[0].resolve({sha256:'new'});await Promise.all([first,second]);
 assert.deepEqual(ui.applied,['new:both']);assert.equal(ui.warnings.length,1);
 assert(!ui.messages.some(message=>message.includes('could not be activated')));
 assert.match(ui.messages.at(-1)!,/Display selected/);assert.equal(ui.context.applyingPrepared.current,false);
 assert.equal(ui.busy.at(-1),false);
});
test('a real application failure remains retryable without premature applied state',async()=>{
 const ui=harness(),first=ui.apply();ui.requests[0].reject(new Error('copy failed'));await first;
 assert.deepEqual(ui.applied,[]);assert.match(ui.messages.at(-1)!,/could not be activated/);
 const retry=ui.apply();assert.equal(ui.requests.length,2);ui.requests[1].resolve({sha256:'new'});await retry;
 assert.deepEqual(ui.applied,['new:both']);assert.equal(ui.context.applyingPrepared.current,false);
});
test('Home-only and game destinations retain their requested scope',async()=>{
 for(const target of ['home','game','game-dashboard']){
  const ui=harness(),pending=ui.apply(target);assert.equal(ui.requests.length,1);
  assert.equal(ui.requests[0].args[3],target==='home'?true:'new');
  if(target.startsWith('game'))assert.equal(ui.requests[0].args[4],target==='game'?'artwork':'artwork-dashboard');
  ui.requests[0].resolve({sha256:'new'});await pending;assert.deepEqual(ui.applied,[`new:${target}`]);
 }
});
