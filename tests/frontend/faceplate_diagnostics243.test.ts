import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import {createElement} from 'react';
const source=readFileSync(new URL('../../src/components/FaceplateDiagnostics.tsx',import.meta.url),'utf8');
const context=vm.createContext({React:{createElement},Disclosure:'disclosure'});
vm.runInContext(ts.transpileModule(source.replace(/^import .*;\n/gm,'').replace(/export function/g,'function'),{compilerOptions:{jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2022}}).outputText+';this.render=FaceplateDiagnostics;',context);
const walk=(x:any):any[]=>Array.isArray(x)?x.flatMap(walk):x&&typeof x==='object'?[x,...walk(x.props?.children)]:[];
const text=(x:any):string=>Array.isArray(x)?x.map(text).join(' '):x&&typeof x==='object'?text(x.props?.children):String(x??'');
const fixture=(language:string)=>({ui_language:language,faceplate_lab_enabled:true,faceplate_configuration_error:'one shared error',faceplate:{available:true,busy:false,powered:null,port:'/dev/ttyACM0',owners:['Steam'],detail:'',error:'one shared error',writes_session:3,writes_total:7,last_asset:'scene.gif',last_upload_ms:650,last_start_ack_ms:8,last_transfer:{total_ms:650,active_profile:'baseline',preflight_ms:1,begin_ms:2,chunks_ms:640,finalize_ms:7,chunks:12,transfer_retries:1,end_timeout_seconds:4},delivery:{state:'unconfirmed'},routing:{routes:{home:'dashboard',game:'artwork'},desired_scene:'dashboard',prepared_scene:'dashboard',effective_scene:'artwork',preparation:{state:'unconfirmed',error:'one shared error'}},automation:{last_scene:'weather:job3',busy:false,queued:true,dropped:2,superseded_active:1,ack_ema_ms:9,last_error:'one shared error',last_result:{frames:80,refresh_policy:'economy',fallback:'missing hero'}},flash_protection:{enabled:true,session:{confirmed:3},total:{confirmed:7,reused:8,deferred:2,uncertain:1},history_state:'persisted',recent:[]},upload_observability:{today_utc:{writes:3,identical:8,failed:1},journal:[{outcome:'unconfirmed',reason:'test send',crc32:'ab12',size_bytes:54321,ack_ms:8,duration_ms:650}]}}});
test('one diagnostic keeps three clear sections and distinct troubleshooting facts in both languages',()=>{
 for(const language of ['en','fr']){
  const tree=context.render({status:fixture(language)}),nodes=walk(tree),body=text(tree);
  assert.equal(tree.type,'disclosure');assert.equal(nodes.filter(n=>n.type==='disclosure').length,1);
  assert.deepEqual(nodes.filter(n=>n.type==='h3').map(n=>n.props.children),language==='fr'?['Connexion','Affichage','Transferts']:['Connection','Display','Transfers']);
  assert.equal(body.split('one shared error').length-1,1);
  for(const fact of ['/dev/ttyACM0','Steam','scene.gif','missing hero','650','54321','ab12','80','weather:job3'])assert(body.includes(fact),fact);
  assert.match(body,language==='fr'?/Confirmation manquante/:/Confirmation missing/);
  assert.doesNotMatch(body,/Displayed:|Visible playback: unknown|Technical details|undefined/);
 }
});
test('the existing summary is not repeated inside the diagnostic',()=>{
 const body=text(context.render({status:fixture('en'),summaryShown:true}));
 assert.doesNotMatch(body,/Confirmed GIF transfers|Image-change counter/);
 assert.match(text(context.render({status:fixture('en')})),/Confirmed GIF transfers/);
});

test('recovery distinguishes missing confirmation and exhausted attempts in both languages',()=>{
 for(const language of ['en','fr'])for(const state of ['restoring','retry-waiting','unconfirmed','exhausted']){
  const status=fixture(language) as any;status.faceplate.power_recovery={route_state:state,route_attempts:3};
  const body=text(context.render({status}));
  assert.match(body,language==='fr'?/Récupération de l’affichage/:/Display recovery/);
  if(state==='retry-waiting')assert.match(body,language==='fr'?/seul nouvel essai automatique/:/One automatic retry/);
  if(state==='unconfirmed')assert.match(body,language==='fr'?/Reprise automatique arrêtée/:/Automatic retry stopped/);
  if(state==='exhausted')assert.match(body,language==='fr'?/trois tentatives/:/three attempts/);
  assert.doesNotMatch(body,/undefined/);
 }
});

test('explicit Off hides an older automatic recovery message',()=>{
 const status=fixture('en') as any;status.faceplate.powered=false;
 status.faceplate.power_recovery={suspended:true,route_state:'restoring'};
 const body=text(context.render({status}));assert.match(body,/Power\s*:\s*Off/);
 assert.doesNotMatch(body,/Display recovery|Restoring the current image/);
});
