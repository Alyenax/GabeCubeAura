import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import {createElement,Fragment} from 'react';
import {translate} from '../../src/i18n';
import {selectedClock} from '../../src/faceplate_clock';

const source=readFileSync(new URL('../../src/components/FaceplateClocks.tsx',import.meta.url),'utf8');
const js=ts.transpileModule(source.slice(source.indexOf('export function ClockAppearance')).replace(/export function/g,'function'),
  {compilerOptions:{target:ts.ScriptTarget.ES2020,jsx:ts.JsxEmit.React}}).outputText;
const nodes=(t:any):any[]=>Array.isArray(t)?t.flatMap(nodes):t&&typeof t==='object'?[t,...nodes(t.props?.children)]:[];
test('appearance saves only the edited context, blocks overlapping writes and reports failed saves',async()=>{
  const values:any[]=[],writes:any[]=[],saved:any[]=[];let index=0,resolve:Function=()=>{},reject:Function=()=>{};
  const ctx=vm.createContext({selectedClock,React:{createElement,Fragment},DropdownItem:'dropdown',Localized:'localized',PanelSectionRow:'row',
    useRef:(v:any)=>{const i=index++;return values[i]??(values[i]={current:v});},
    useState:(v:any)=>{const i=index++;if(!(i in values))values[i]=v;return[values[i],(value:any)=>values[i]=value];},
    setSetting:(...args:any[])=>{writes.push(args);return new Promise((a,b)=>{resolve=a;reject=b;});}});
  vm.runInContext(js+'\nthis.component=ClockAppearance;',ctx);
  const render=()=>{index=0;return nodes(ctx.component({status:{faceplate_clock_game:'halo',faceplate_clock:{catalog:[{id:'halo',family:'analog'}]},faceplate_clock_palette_game:'rose',faceplate_clock_format_game:'12'},context:'game',setStatus:(s:any)=>saved.push(s)}));};
  const choose=(label:string)=>render().find(x=>x.props?.label===label);
  assert.equal(choose('Clock colours').props.selectedOption,'rose');
  assert.deepEqual(Array.from(choose('Clock format').props.rgOptions,(v:any)=>v.label),['Without AM/PM','With AM/PM']);
  choose('Clock colours').props.onChange({data:'sage'});
  choose('Clock format').props.onChange({data:'24'});
  assert.deepEqual(writes,[['faceplate_clock_palette_game','sage']]);
  resolve({saved:true});await new Promise(r=>setImmediate(r));assert.equal(saved.length,1);
  choose('Clock format').props.onChange({data:'24'});reject(new Error('disk failure'));await new Promise(r=>setImmediate(r));
  assert.deepEqual(writes[1],['faceplate_clock_format_game','24']);
  assert(render().some(x=>x.props?.role==='alert'));assert.equal(saved.length,1);
});
test('clock palette and format labels are localized',()=>{
  for(const label of ['Clock colours','Clock format','Amber','Glacier blue','Dusty rose','Sage green','Lavender','Ivory','Meridian','Almanac','Cardinal markers','Column','Week','Date card']){
    assert.notEqual(translate(label,'fr'),label,label);
  }
});
