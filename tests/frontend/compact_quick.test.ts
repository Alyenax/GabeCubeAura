import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import {createElement,Fragment} from 'react';
import {homeFaceChoice} from '../../src/faceplate_choices';
const source=readFileSync(new URL('../../src/components/CompactQuickPanel.tsx',import.meta.url),'utf8');
const ast=ts.createSourceFile('compact.tsx',source,99,true,4);
const functions=['personalTimer','quickFaceChoice','TimerEditor'].map(name=>ast.statements.find(node=>ts.isFunctionDeclaration(node)&&node.name?.text===name)!.getText(ast).replace(/^export /,''));
function nodes(tree:any):any[]{return Array.isArray(tree)?tree.flatMap(nodes):tree&&typeof tree==='object'?[tree,...nodes(tree.props?.children)]:[];}
const flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
function harness(action='none',success=true){
 let cursor=0;
 const started:any[]=[],closed:any[]=[];
 const context=vm.createContext({homeFaceChoice,React:{createElement,Fragment},useState:(initial:any)=>[cursor++===0?initial:action,()=>{}],useRef:(current:any)=>({current}),
 DialogButton:'button',SliderField:'slider',TextField:'text',QuickInlineChoice:'dropdown',Localized:'localized',Focusable:'focusable',COMPACT_QUICK_CSS:'',reportQuickUI(){}});
 vm.runInContext(ts.transpileModule(functions.join('\n')+'\nthis.api={personalTimer,quickFaceChoice,TimerEditor};',{compilerOptions:{jsx:ts.JsxEmit.React,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,context);
 return{api:context.api,started,closed,editor:(disabled=false)=>context.api.TimerEditor({minutes:30,disabled,onStart:async(...args:any[])=>{started.push(args);return success;},onClose:()=>closed.push(true)})};
}
test('personal timer snapshot is independent of the active Families display',()=>{
 const app=harness();
 assert.equal(app.api.personalTimer({personal_timer:{active:true,remaining_seconds:300},countdown:{active:true,source:'parental',remaining_seconds:60}}).remaining_seconds,300);
 assert.equal(app.api.personalTimer({countdown:{active:true,source:'parental',remaining_seconds:60}}).active,false);
});
test('faceplate selector preserves native clock, artwork-dashboard and power state',()=>{
 const app=harness(),s:any={game:{appid:0},faceplate_dashboard_home_source:'artwork',faceplate:{powered:true,routing:{routes:{home:'dashboard',game:'artwork-dashboard'}}}};
 assert.equal(app.api.quickFaceChoice(s),'artwork-dashboard');s.game.appid=42;assert.equal(app.api.quickFaceChoice(s),'artwork-dashboard');
 s.game.appid=0;s.faceplate.routing.routes.home='native-clock';assert.equal(app.api.quickFaceChoice(s),'native-clock');
 s.faceplate.powered=false;assert.equal(app.api.quickFaceChoice(s),'off');
});
test('sleep/shutdown start only after explicit inline confirmation and once',async()=>{
 for(const action of['none','sleep','shutdown']){
  const app=harness(action),editor=app.editor();assert.deepEqual(app.started,[]);
  const start=nodes(editor).find(n=>n.type==='button'&&n.props.children===(action==='none'?'Start':'Confirm and start'));
  start.props.onClick();start.props.onClick();await flush();
  assert.deepEqual(app.started,[[30,action]]);assert.equal(app.closed.length,1);
 }
});
test('cancelled timer editor cannot start from a late confirm',async()=>{
 const app=harness('shutdown'),buttons=nodes(app.editor()).filter(n=>n.type==='button');
 buttons.find(n=>n.props.children==='Cancel').props.onClick();buttons.find(n=>n.props.children==='Confirm and start').props.onClick();await flush();
 assert.deepEqual(app.started,[]);assert.equal(app.closed.length,1);
});
test('failed timer start keeps the editor open and permits a retry; busy editor cannot start',async()=>{
 const app=harness('none',false),start=nodes(app.editor()).find(n=>n.type==='button'&&n.props.children==='Start');
 start.props.onClick();await flush();assert.equal(app.closed.length,0);
 start.props.onClick();await flush();assert.equal(app.started.length,2);
 const busy=harness();nodes(busy.editor(true)).find(n=>n.type==='button'&&n.props.children==='Start').props.onClick();await flush();
 assert.equal(busy.started.length,0);
});
test('all four quick choices retain the shared native selector',()=>{
 assert.equal((source.match(/<QuickInlineChoice label=/g)||[]).length,4);
 assert.doesNotMatch(source,/\bshowModal\b|<ConfirmModal|<Dropdown(?:Item)?\s/);
});
