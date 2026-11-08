import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import {createElement,Fragment} from 'react';

const source=readFileSync(new URL('../../src/components/FaceplateDiagnostics.tsx',import.meta.url),'utf8').replace(/^import .*;\n/gm,'');
const context=vm.createContext({exports:{},React:{createElement,Fragment},Disclosure:'section'});
vm.runInContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.React}}).outputText,context);
function words(node:any):string {
  if(node==null||typeof node==='boolean')return '';
  if(Array.isArray(node))return node.map(words).join(' ');
  return typeof node==='object'?words(node.props?.children):String(node);
}
function render(transfer:any,language='en',restoration:any={}){
  const status:any={ui_language:language,faceplate_lab_enabled:true,faceplate_configuration_error:'',
    faceplate:{available:true,powered:false,routing:{routes:{home:'weather',game:'dashboard'},preparation:{state:'error',error:''}},
      automation:{last_error:'',busy:false},last_transfer:transfer,power_recovery:{route_state:'failed'},restoration}};
  return words(context.exports.FaceplateDiagnostics({status}));
}

test('a fast zero-status BEGIN refusal remains visible as 0x00',()=>{
  const text=render({total_ms:0,begin_attempted:true,begin_status:0,failure_stage:'begin',failure_kind:'rejected',chunks:0});
  assert.match(text,/0x00/);assert.match(text,/Failed stage/);assert.doesNotMatch(text,/No reply/);
});
test('an attempted BEGIN without a reply differs from a command never sent',()=>{
  assert.match(render({begin_attempted:true,begin_status:null,failure_stage:'begin'}),/No reply/);
  const notSent=render({begin_attempted:false,failure_stage:'preflight'});
  assert.match(notSent,/Not sent/);assert.doesNotMatch(notSent,/No reply/);
});
test('French diagnostics follow the selected GCA language',()=>{
  assert.match(render({begin_attempted:true,begin_status:null,failure_stage:'begin'},'fr'),/Aucune réponse/);
  assert.match(render({failure_stage:'preflight'},'fr'),/Non envoyé/);
});
test('power-only recovery never reports the requested picture as confirmed or asks for the same action again',()=>{
  const text=render({begin_attempted:true,begin_status:0,failure_stage:'begin'},'en',{stored_picture_resumed:true});
  assert.match(text,/requested image remains unconfirmed/);
  assert.doesNotMatch(text,/Use Resume stored picture/);
});
