import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import {createElement,Fragment} from 'react';

function mount(create:()=>Promise<any>,clipboard?:{writeText:(text:string)=>Promise<void>}){
 const slots:any[]=[];let cursor=0;const events:string[]=[];
 const source=readFileSync(new URL('../../src/components/DiagnosticExport.tsx',import.meta.url),'utf8').replace(/^import .*;\n/gm,'');
 const context=vm.createContext({exports:{},React:{createElement,Fragment},BUILD_VERSION:'1.6.1-beta.2',
  ButtonItem:'button',PanelSectionRow:'row',Localized:'localized',navigator:{clipboard},document:{execCommand:()=>false},
  useState:(initial:any)=>{const i=cursor++;if(!(i in slots))slots[i]=initial;return[slots[i],(value:any)=>slots[i]=value];},
  useRef:(initial:any)=>{const i=cursor++;return slots[i]??={current:initial};}});
 vm.runInContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.React}}).outputText,context);
 return {render(){cursor=0;return context.exports.DiagnosticExport({create});},events};
}
function nodes(n:any):any[]{return Array.isArray(n)?n.flatMap(nodes):n&&typeof n==='object'?[n,...nodes(n.props?.children)]:[];}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const button=(n:any,label:string)=>nodes(n).find(x=>x.type==='button'&&x.props.label===label);

test('one action makes one document and a write failure still exposes the same copyable text',async()=>{
 let calls=0,resolve!:(r:any)=>void;const app=mount(()=>{calls++;return new Promise(done=>resolve=done);});
 const first=button(app.render(),'Export a local diagnostic');first.props.onClick();first.props.onClick();assert.equal(calls,1);
 assert.equal(button(app.render(),'Export a local diagnostic').props.disabled,undefined);
 const text=JSON.stringify({version:'1.6.1-beta.2',power:'unknown'});resolve({saved:false,path:'',text});await flush();
 const tree=app.render();assert.equal(nodes(tree).find(n=>n.type==='textarea').props.value,text);
 assert(button(tree,'Copy diagnostic text'));assert.equal(calls,1);
});
test('copy transfers only the redacted report text, not a file path, and never recollects it',async()=>{
 const copied:string[]=[];let calls=0;const app=mount(async()=>{calls++;return{saved:true,path:'/private/local-file',text:'{"safe":true}'};},
  {writeText:async text=>{copied.push(text);}});
 button(app.render(),'Export a local diagnostic').props.onClick();await flush();
 button(app.render(),'Copy diagnostic text').props.onClick();await flush();
 assert.deepEqual(copied,['{"safe":true}']);assert.equal(calls,1);
});
test('an unavailable clipboard leaves selectable text rather than discarding the report',async()=>{
 const app=mount(async()=>({saved:false,path:'',text:'{}'}));button(app.render(),'Export a local diagnostic').props.onClick();await flush();
 const tree=app.render(),field=nodes(tree).find(n=>n.type==='textarea');let selected=false;
 field.ref.current={focus(){},select(){selected=true;}};
 button(tree,'Copy diagnostic text').props.onClick();await flush();
 assert(selected);assert(nodes(app.render()).some(n=>n.type==='localized'&&n.props.children==='Select and copy the diagnostic text below.'));
});
test('an unavailable backend still produces a client report without copying raw errors',async()=>{
 const app=mount(async()=>{throw new Error('/home/private-user secret-token');});
 button(app.render(),'Export a local diagnostic').props.onClick();await flush();
 const text=nodes(app.render()).find(n=>n.type==='textarea').props.value;
 assert.equal(JSON.parse(text).backend_report_available,false);assert.match(text,/1.6.1-beta.2/);assert.doesNotMatch(text,/private-user|secret-token/);
});

test('the frontend identity matches the package and backend versions',()=>{
 const root=new URL('../../',import.meta.url);
 const version=JSON.parse(readFileSync(new URL('package.json',root),'utf8')).version;
 assert.equal(version,'1.6.1-beta.3');
 assert.match(readFileSync(new URL('src/build_version.ts',root),'utf8'),new RegExp("BUILD_VERSION = '"+version.replaceAll('.','\\.')+"'"));
 assert.match(readFileSync(new URL('py_modules/signalbar/__init__.py',root),'utf8'),new RegExp('__version__ = "'+version.replaceAll('.','\\.')+'"'));
});
