import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {createElement} from 'react';
import ts from 'typescript';
import {showUpdateButton} from '../../src/update_button';
import type {UpdateStatus} from '../../src/types';

const source=readFileSync(new URL('../../src/components/UpdateAvailableButton.tsx',import.meta.url),'utf8').replace(/^import .*;\n/gm,'');
const context=vm.createContext({exports:{},React:{createElement},PanelSection:'section',PanelSectionRow:'row',QuickAction:'button',showUpdateButton});
vm.runInContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React}}).outputText,context);
const walk=(node:any):any[]=>!node||typeof node!=='object'?[]:Array.isArray(node)?node.flatMap(walk):[node,...walk(node.props?.children)];
const state={phase:'available',installed_version:'1.4.1-lab.176',available_version:'1.4.1-lab.177',channel:'private',notified_version:'1.4.1-lab.177',notifications:false,confirmation_token:''} as UpdateStatus;

test('detected update stays actionable after toast acknowledgement or notifications disabled, then disappears when current',()=>{
  let opened=0;
  const render=(update:UpdateStatus|null)=>(context.exports as any).UpdateAvailableButton({update,onOpen:()=>opened++});
  assert.equal(render(null),null);
  let tree=render(state);const button=walk(tree).find(node=>node.type==='button');assert(button);
  button.props.onClick();assert.equal(opened,1);
  for(const phase of ['available','ready','error'] as const){
    tree=render({...state,phase,confirmation_token:phase==='error'?'verified-token':''});
    assert(walk(tree).some(node=>node.type==='button'));
    assert(walk(tree).some(node=>node.props?.translate==='no'&&node.props.children===state.available_version));
  }
  for(const patch of [{phase:'up_to_date'},{phase:'installing'},{phase:'downloading'},{available_version:''},{installed_version:state.available_version},{recovery_prepared:true}])assert.equal(render({...state,...patch} as UpdateStatus),null);
  assert.equal(opened,1,'rendering never starts an action');
});

test('production quick panel mounts the update action and opens the existing Updates route',()=>{
  const entry=readFileSync(new URL('../../src/index.tsx',import.meta.url),'utf8');
  const at=entry.indexOf('<UpdateAvailableButton update={update}');assert(at>entry.indexOf('{page === "quick" ? <>'));
  assert(entry.slice(at,at+230).includes("Navigation.Navigate('/gabecubeaura/settings/updates')"));
});
