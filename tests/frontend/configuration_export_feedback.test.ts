import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import {createElement,Fragment} from 'react';
import {translate} from '../../src/i18n';
const source=readFileSync(new URL('../../src/components/ConfigurationExportSettings.tsx',import.meta.url),'utf8');
const nodes=(node:any):any[]=>!node?[]:Array.isArray(node)?node.flatMap(nodes):[node,...nodes(node.props?.children)];
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function harness(save:()=>Promise<unknown>){
 const hooks:any[]=[];let index=0;const busy:boolean[]=[];
 const context=vm.createContext({React:{createElement,Fragment},useRef:(v:any)=>{const i=index++;return hooks[i]??={current:v};},useState:(v:any)=>{const i=index++;if(!(i in hooks))hooks[i]=v;return [hooks[i],(next:any)=>hooks[i]=next];},exportConfiguration:save,ButtonItem:'button',PanelSectionRow:'row',Localized:'localized'});
 vm.runInContext(ts.transpileModule(source.replace(/^import .*$/gm,'').replace('export function','function'),{compilerOptions:{jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2020}}).outputText+'\nthis.component=ConfigurationExportSettings;',context);
 return {busy,render(disabled=false){index=0;return nodes(context.component({disabled,onBusyChange:(v:boolean)=>busy.push(v)}));}};
}
test('export is manual, reports progress, blocks repeat clicks and shows the returned path',async()=>{
 let calls=0,complete:any;const ui=harness(()=>{calls++;return new Promise(resolve=>complete=resolve);});
 const first=ui.render().find(n=>n.type==='button');assert.equal(calls,0);first.props.onClick();first.props.onClick();assert.equal(calls,1);
 let view=ui.render();assert.equal(view.find(n=>n.type==='button').props.disabled,true);assert(view.some(n=>n.props?.role==='status'&&n.props.children==='Exporting configuration…'));
 complete({path:'/home/deck/Documents/GabeCubeAura/configuration.json'});await flush();view=ui.render();
 const receipt=view.find(n=>n.props?.role==='status');assert(receipt);assert(nodes(receipt).some(n=>n.props?.translate==='no'&&n.props.children==='/home/deck/Documents/GabeCubeAura/configuration.json'));
 assert(nodes(receipt).some(n=>n.props?.children==='Configuration exported. Saved locally at:'));assert.deepEqual(ui.busy,[true,false]);assert.equal(calls,1);
 for(const text of ['Exporting configuration…','Configuration exported. Saved locally at:','Use Import JSON to restore this file.'])assert.notEqual(translate(text,'fr'),text);
});
test('busy settings block export; failed retry clears an earlier success and allows retry',async()=>{
 let calls=0;const ui=harness(async()=>{calls++;if(calls===1)return {path:'/Documents/snapshot.json'};throw new Error('Disk full');});
 ui.render(true).find(n=>n.type==='button').props.onClick();assert.equal(calls,0);
 ui.render().find(n=>n.type==='button').props.onClick();await flush();assert(ui.render().some(n=>n.props?.role==='status'));
 ui.render().find(n=>n.type==='button').props.onClick();await flush();const view=ui.render();assert.equal(calls,2);assert(!view.some(n=>n.props?.role==='status'));assert(view.some(n=>n.props?.role==='alert'));assert.equal(view.find(n=>n.type==='button').props.disabled,false);
 assert(nodes(view.find(n=>n.props?.role==='alert')).some(n=>n.props?.children==='Disk full'));
});
test('missing location is an error and the real settings page mounts the feedback component',async()=>{
 const ui=harness(async()=>({}));ui.render().find(n=>n.type==='button').props.onClick();await flush();assert(ui.render().some(n=>n.props?.role==='alert'));
 const app=readFileSync(new URL('../../src/index.tsx',import.meta.url),'utf8');assert.match(app,/<ConfigurationExportSettings disabled=\{configurationBusy\} onBusyChange=\{setConfigurationBusy\}/);
});
