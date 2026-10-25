import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import {createElement,Fragment} from 'react';

const source=readFileSync(new URL('../../src/index.tsx',import.meta.url),'utf8');
const walk=(node:any):any[]=>Array.isArray(node)?node.flatMap(walk):node&&typeof node==='object'?[node,...walk(node.props?.children)]:[];
function mount(action='none',reject=false){
 const ast=ts.createSourceFile('panel.tsx',source,99,true,4);
 const panel=ast.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text==='CountdownPanel')!;
 const calls:any[]=[],modals:any[]=[],errors:any[]=[],updates:any[]=[];
 const status={countdown:{active:false},free_timer_minutes:30,free_timer_end_action:action,timer_end_action:{phase:'idle'},countdown_full_bar_minutes:0};
 const context=vm.createContext({exports:{},React:{createElement,Fragment},useRef:(current:any)=>({current}),useState:()=>['',(value:any)=>errors.push(value)],
  PanelSection:'section',PanelSectionRow:'row',ButtonItem:'action',DropdownItem:'choice',ToggleField:'toggle',SliderField:'slider',Localized:'localized',ConfirmModal:'confirm',
  COUNTDOWN_COLOUR_OPTIONS:[],COUNTDOWN_SCALE_OPTIONS:[],PalettePreview:'palette',
  showModal:(node:any)=>{modals.push(node);return{Close(){}};},
  startFreeTimer:async(...args:any[])=>{calls.push(args);if(reject)throw new Error('test');return status;},
  stopFreeTimer:async()=>status,previewCountdown:async()=>status,
 });
 vm.runInContext(ts.transpileModule('exports.mount='+panel.getText(ast),{compilerOptions:{jsx:ts.JsxEmit.React,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,context);
 const tree=context.exports.mount({status,setStatus:(value:any)=>updates.push(value)});
 return{tree,calls,modals,errors,updates,start:walk(tree).find(n=>n.props?.label==='Personal limit').props.onClick};
}
const settle=async()=>{await Promise.resolve();await Promise.resolve();};
test('ordinary timer starts without a power modal and explicitly passes none',async()=>{
 const app=mount();app.start();await settle();assert.deepEqual(app.calls,[[30,'none']]);assert.equal(app.modals.length,0);assert.equal(app.updates.length,1);
});
test('sleep and shutdown require confirmation and repeated OK cannot start twice',async()=>{
 for(const action of['sleep','shutdown']){
  const app=mount(action);app.start();app.start();assert.equal(app.modals.length,1);assert.deepEqual(app.calls,[]);
  const modal=app.modals[0];assert.match(modal.props.strTitle,action==='sleep'?/sleep/:/shutdown/);
  modal.props.onOK();modal.props.onOK();await settle();assert.deepEqual(app.calls,[[30,action]]);
 }
});
test('cancel does not replace the running timer and allows a later explicit attempt',async()=>{
 const app=mount('shutdown');app.start();app.modals[0].props.onCancel();app.modals[0].props.onOK();await settle();
 assert.deepEqual(app.calls,[]);app.start();assert.equal(app.modals.length,2);
});
test('start errors remain visible and do not automatically retry',async()=>{
 const app=mount('sleep',true);app.start();app.modals[0].props.onOK();await settle();
 assert.equal(app.calls.length,1);assert(app.errors.some(value=>/could not be started/.test(value)));assert.equal(app.updates.length,0);
});
test('end-action choice remains a native setting outside the immutable quick panel',()=>{
 const app=mount();const choice=walk(app.tree).find(n=>n.props?.label==='When the next personal timer ends');
 assert.equal(choice.type,'choice');assert.equal(choice.props.selectedOption,'none');
 assert.deepEqual(Array.from(choice.props.rgOptions,(o:any)=>o.data),['none','sleep','shutdown']);
});
