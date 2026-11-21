import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source=readFileSync(new URL('../../src/components/PixelClocksIntegration.tsx',import.meta.url),'utf8').replace(/^import .*;\n/gm,'');
const javascript=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2020,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React}}).outputText;
const flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
function harness(){
  let cursor=0;const values:any[]=[],effects:(()=>void)[]=[],intervals:(()=>void)[]=[],cleanups:(()=>void)[]=[];
  const reads:((s:any)=>void)[]=[],writes:{args:any[];resolve:(s:any)=>void;reject:(error:any)=>void}[]=[];
  const element=(type:any,props:any,...children:any[])=>({type,props:props||{},children});
  const ctx=vm.createContext({exports:{},React:{createElement:element},PanelSectionRow:'row',QuickInlineChoice:'choice',
    useState:(initial:any)=>{const n=cursor++;if(!(n in values))values[n]=initial;return[values[n],(v:any)=>values[n]=v];},
    useRef:(initial:any)=>{const n=cursor++;if(!(n in values))values[n]={current:initial};return values[n];},
    useEffect:(fn:()=>any)=>{const n=cursor++;if(!(n in values)){values[n]=true;effects.push(()=>{const clean=fn();if(clean)cleanups.push(clean);});}},
    callable:(name:string)=>name==='get_pixel_clocks_state'?()=>new Promise(resolve=>reads.push(resolve)):(...args:any[])=>new Promise((resolve,reject)=>writes.push({args,resolve,reject})),
    setInterval:(fn:()=>void)=>{intervals.push(fn);return 1;},clearInterval:()=>{},
  });
  vm.runInContext(javascript,ctx);
  return{reads,writes,intervals,unmount:()=>cleanups.forEach(fn=>fn()),render:()=>{cursor=0;const result=ctx.exports.PixelClocksIntegration({active:true,french:true});for(const fn of effects.splice(0))fn();return result;}};
}
function find(root:any,type:string):any{if(!root)return null;if(root.type===type)return root;for(const c of root.children??[]){if(Array.isArray(c)){for(const x of c){const r=find(x,type);if(r)return r;}}else{const r=find(c,type);if(r)return r;}}return null;}
const state=(revision:number,destination='none')=>({present:true,compatible:true,revision,destination,context:'home',state:'applied'});

test('both panels use the four exact destination labels, hidden without a live companion',async()=>{
 const h=harness();assert.equal(h.render(),null);h.reads.shift()!({...state(1),present:false});await flush();assert.equal(h.render(),null);
 h.intervals[0]();h.reads.shift()!(state(1));await flush();const control=find(h.render(),'choice');
 assert.deepEqual(Array.from(control.props.rgOptions,(o:any)=>[o.data,o.label]),[['home','À l’accueil'],['game','En jeu'],['both','Les deux'],['none','Aucun']]);
});
test('stale poll cannot overwrite confirmed mutation, and absent companion can be removed',async()=>{
 const h=harness();h.render();h.reads.shift()!(state(1));await flush();let tree=h.render();
 h.intervals[0]();const stale=h.reads.shift()!;
 find(tree,'choice').props.onChange({data:'both'});assert.deepEqual(h.writes[0].args,['both',1]);
 h.writes.shift()!.resolve(state(2,'both'));await flush();stale(state(1));await flush();
 assert.equal(find(h.render(),'choice').props.selectedOption,'both');
 h.intervals[0]();h.reads.shift()!({...state(2,'both'),present:false,compatible:false,state:'disconnected'});await flush();
 tree=h.render();assert.equal(find(tree,'choice').props.disabled,false);
 find(tree,'choice').props.onChange({data:'none'});assert.deepEqual(h.writes[0].args,['none',2]);h.unmount();
});

test('a revision conflict awaits its resync before enabling the control',async()=>{
 const h=harness();h.render();h.reads.shift()!(state(1));await flush();
 find(h.render(),'choice').props.onChange({data:'both'});h.writes.shift()!.reject(new Error('REVISION_CONFLICT'));await flush();
 assert.equal(find(h.render(),'choice').props.disabled,true);
 h.reads.shift()!(state(2,'game'));await flush();const tree=h.render();
 assert.equal(find(tree,'choice').props.disabled,false);assert.equal(find(tree,'choice').props.selectedOption,'game');
 h.unmount();
});
