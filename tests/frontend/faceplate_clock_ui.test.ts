import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import {selectedClock,CLOCK_TRANSFER_NOTICE,clockCountdown} from '../../src/faceplate_clock';

type Node={type:any;props:any;children:any[]};
function flatten(value:any):Node[]{return Array.isArray(value)?value.flatMap(flatten):value&&typeof value==='object'&&'type'in value?[value,...flatten(value.children)]:[];}
function harness(entries:any[],context:'home'|'game'='home'){
  const saved:any[]=[],writes:any[]=[],routes:any[]=[];let closed=0,reads=0,index=0;const states:any[]=[];
  const current:any={faceplate_clock_home:'old',faceplate_clock_game:'other',faceplate_clock:{catalog:entries},faceplate:{routing:{routes:{home:'weather',game:'artwork'},preference_revision:7}}};
  const ctx=vm.createContext({React:{createElement:(type:any,props:any,...children:any[])=>({type,props,children})},
    useState:(initial:any)=>{const i=index++;if(!(i in states))states[i]=initial;return[states[i],(v:any)=>{states[i]=v;}];},
    useRef:(initial:any)=>{const i=index++;return states[i]??(states[i]={current:initial});},useEffect:()=>{},
    DialogBody:'body',DialogHeader:'header',ModalRoot:'modal',ButtonItem:'button',DialogButton:'close',Localized:'localized',PanelSectionRow:'row',DropdownItem:'dropdown',
    CLOCK_TRANSFER_NOTICE,selectedClock,clockCountdown,
    getStatus:async()=>{reads++;return current;},setSetting:async(key:string,value:string)=>{writes.push([key,value]);return current;},
    setFaceplateRouting:async(...args:any[])=>{routes.push(args);return current;},showModal:()=>({Close(){}})});
  const source=readFileSync(new URL('../../src/components/FaceplateClocks.tsx',import.meta.url),'utf8').replace(/^import .*$/gm,'').replace(/export function/g,'function');
  vm.runInContext(ts.transpileModule(source,{compilerOptions:{jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2020}}).outputText+'\nthis.picker=ClockPicker;this.transfer=ClockTransferSettings;',ctx);
  return {saved,writes,routes,current,get reads(){return reads;},get closed(){return closed;},renderTransfer(){index=0;return flatten(ctx.transfer({status:current,setStatus:(s:any)=>saved.push(s),context}));},render(){index=0;return flatten(ctx.picker({initial:current,context,onSaved:(s:any)=>saved.push(s),close:()=>closed++}));}};
}
test('opening empty beta picker performs no write, request or route change',()=>{
  const h=harness([]),nodes=h.render();assert(nodes.some(n=>n.type==='modal'));
  assert.equal(nodes.filter(n=>n.type==='button').length,0);assert.equal(h.reads,0);
  assert.deepEqual(h.writes,[]);assert.deepEqual(h.routes,[]);
});
test('clock choice writes only its context and uses fresh routes/revision',async()=>{
  const h=harness([{id:'standard',label:'Standard',private:false}],'game');
  const choose=h.render().find(n=>n.type==='button')!;
  await choose.props.onClick();
  // onClick intentionally starts an async UI operation without returning it.
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(h.writes,[['faceplate_clock_game','standard']]);
  assert.deepEqual(h.routes,[['weather','clock',7]]);assert.equal(h.saved.length,1);assert.equal(h.closed,1);
});
test('clock removed while modal is open cannot mutate settings or routing',async()=>{
  const h=harness([{id:'standard',label:'Standard',private:false}]);const choose=h.render().find(n=>n.type==='button')!;
  h.current.faceplate_clock.catalog=[];choose.props.onClick();await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(h.writes,[]);assert.deepEqual(h.routes,[]);assert.equal(h.closed,0);
  assert(h.render().some(n=>n.props?.role==='alert'));
});

test('transfer mode opens without mutation and saves only its context with duplicate submits fenced',async()=>{
  const h=harness([{id:'standard',label:'Standard',private:false}],'game');
  const dropdown=h.renderTransfer().find(n=>n.type==='dropdown')!;
  assert.equal(dropdown.props.selectedOption,'conservative');
  assert.equal(dropdown.props.rgOptions.length,2);
  assert.deepEqual(h.writes,[]);assert.deepEqual(h.routes,[]);assert.equal(h.reads,0);
  dropdown.props.onChange({data:'minute'});dropdown.props.onChange({data:'conservative'});
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(h.writes,[['faceplate_clock_cadence_game','minute']]);
  assert.equal(h.saved.length,1);assert.deepEqual(h.routes,[]);
});
