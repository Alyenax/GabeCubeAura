import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {createElement} from 'react';
import ts from 'typescript';
import {publishQuickSetupStatus,quickSetupCompleted,subscribeQuickSetup} from '../../src/quick_setup_access';

test('title settings action remains available before setup and after reset',()=>{
 const source=readFileSync(new URL('../../src/index.tsx',import.meta.url),'utf8');
 const ast=ts.createSourceFile('index.tsx',source,99,true,4);
 const component=ast.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text==='QuickSettingsAction')!;
 const navigations:string[]=[];
 const context=vm.createContext({exports:{},React:{createElement},DialogButton:'button',TbSettings:'icon',
  Navigation:{CloseSideMenus:()=>navigations.push('close'),Navigate:(path:string)=>navigations.push(path)}});
 vm.runInContext(ts.transpileModule(component.getText(ast)+';exports.render=QuickSettingsAction',{compilerOptions:{jsx:ts.JsxEmit.React,module:ts.ModuleKind.CommonJS}}).outputText,context);
 for(const completed of [false,true,false]){
  publishQuickSetupStatus({onboarding_completed:completed});
  const button=context.exports.render();assert.notEqual(button.props.disabled,true);button.props.onClick();
 }
 assert.deepEqual(navigations,['close','/gabecubeaura/settings','close','/gabecubeaura/settings','close','/gabecubeaura/settings']);
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
