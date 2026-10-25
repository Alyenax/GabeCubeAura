import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {createElement} from 'react';
import ts from 'typescript';
import {publishQuickSetupStatus,quickSetupCompleted,subscribeQuickSetup} from '../../src/quick_setup_access';

test('title settings action shares confirmed setup state, unlocks and relocks without polling',()=>{
 assert.equal(quickSetupCompleted(),false,'Unknown setup is locked');
 const source=readFileSync(new URL('../../src/index.tsx',import.meta.url),'utf8');
 const action=source.slice(source.indexOf('function QuickSettingsAction'),source.indexOf('function QuickAccessContent'));
 let changes=0;const unsubscribe=subscribeQuickSetup(()=>changes++);
 const navigations:string[]=[];
 const context=vm.createContext({React:{createElement},exports:{},DialogButton:'button',TbSettings:'icon',
  useSyncExternalStore:(_subscribe:any,get:any)=>get(),subscribeQuickSetup,quickSetupCompleted,
  Navigation:{CloseSideMenus:()=>navigations.push('close'),Navigate:(route:string)=>navigations.push(route)}});
 vm.runInContext(ts.transpileModule(action+';exports.render=QuickSettingsAction;',{
  compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React}}).outputText,context);
 let button=context.exports.render();assert.equal(button.props.disabled,true);
 button.props.onClick();assert.deepEqual(navigations,[]);
 publishQuickSetupStatus({onboarding_completed:false});assert.equal(changes,0);
 publishQuickSetupStatus({onboarding_completed:true});assert.equal(changes,1);
 button=context.exports.render();assert.equal(button.props.disabled,false);
 button.props.onClick();assert.deepEqual(navigations,['close','/gabecubeaura/settings']);
 publishQuickSetupStatus({onboarding_completed:false});assert.equal(changes,2);
 button.props.onClick();assert.equal(navigations.length,2,'Retained callback cannot bypass a reset');
 assert.equal(context.exports.render().props.disabled,true);
 unsubscribe();publishQuickSetupStatus({onboarding_completed:true});assert.equal(changes,2);
 publishQuickSetupStatus({onboarding_completed:false});
});

test('hidden Content adopts setup confirmation/reset immediately and invalidates older reads',()=>{
 const source=readFileSync(new URL('../../src/index.tsx',import.meta.url),'utf8');
 const ast=ts.createSourceFile('index.tsx',source,99,true,4);
 const content=ast.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text==='Content') as ts.FunctionDeclaration;
 const effect=content.body!.statements.find(n=>ts.isExpressionStatement(n)&&n.getText().includes('useEffect(()=>subscribeQuickSetup('))!;
 let listener!:()=>void,invalidations=0,cleanup:(()=>void)|undefined;const states:any[]=[];
 const context=vm.createContext({useEffect:(fn:()=>()=>void)=>{cleanup=fn();},
  subscribeQuickSetup:(fn:()=>void)=>{listener=fn;return()=>{listener=()=>{};};},
  retainedStatus:null,statusReads:{current:{invalidate:()=>invalidations++}},setStatusState:(s:any)=>states.push(s)});
 vm.runInContext(ts.transpileModule(effect.getText(ast),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,context);
 listener();assert.equal(invalidations,0);
 for(const completed of [true,false]){context.retainedStatus={onboarding_completed:completed};listener();}
 assert.equal(invalidations,2);assert.deepEqual(states.map(s=>s.onboarding_completed),[true,false]);
 cleanup?.();listener();assert.equal(states.length,2);
});

test('a Faceplate-only confirmation refreshes the retained quick panel immediately',()=>{
 publishQuickSetupStatus({onboarding_completed:true,faceplate_setup_completed:false});
 let changes=0;const unsubscribe=subscribeQuickSetup(()=>changes++);
 publishQuickSetupStatus({onboarding_completed:true,faceplate_setup_completed:true});
 assert.equal(changes,1);assert.equal(quickSetupCompleted(),true);
 publishQuickSetupStatus({onboarding_completed:true,faceplate_setup_completed:true});
 assert.equal(changes,1);unsubscribe();
 publishQuickSetupStatus({onboarding_completed:false});
});
