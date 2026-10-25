import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import {createElement} from 'react';
import {rgbToHsl,hslStringToRgb} from '../../src/performance';

function mount(color:number[]){
  let cursor=0;const slots:any[]=[];let confirmed:any;
  const context=vm.createContext({exports:{},React:{createElement},ConfirmModal:'modal',TextField:'text',SliderField:'slider',ButtonItem:'button',
    rgbToHsl,hslStringToRgb,useEffect:()=>{},useState:(initial:any)=>{const index=cursor++;if(!(index in slots))slots[index]=initial;return [slots[index],(value:any)=>slots[index]=value];}});
  const source=readFileSync(new URL('../../src/components/PreciseColorEditor.tsx',import.meta.url),'utf8').replace(/^import .*;\n/gm,'');
  vm.runInContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React}}).outputText,context);
  const render=()=>{cursor=0;return (context.exports as any).OpaqueColorPickerModal({title:'Exact',color,closeModal:()=>{},onConfirm:(value:any)=>confirmed=value});};
  return {render,confirmed:()=>Array.from(confirmed)};
}
const walk=(node:any):any[]=>!node||typeof node!=='object'?[]:Array.isArray(node)?node.flatMap(walk):[node,...walk(node.props?.children)];
for(const hex of ['010101','FEFEFE','123456','000000','FFFFFF','FF0001']){
  test(`GH-07: ${hex} survives open/OK and exact hex input`,()=>{
    const rgb=[0,2,4].map(at=>parseInt(hex.slice(at,at+2),16));const app=mount(rgb);
    app.render().props.onOK();assert.deepEqual(app.confirmed(),rgb);
    let tree=app.render();walk(tree).find(node=>node.type==='text').props.onChange({currentTarget:{value:'#'+hex.toLowerCase()}});
    tree=app.render();tree.props.onOK();assert.deepEqual(app.confirmed(),rgb);
    walk(tree).find(node=>node.type==='slider'&&node.props.label==='Lightness').props.onChange(50);
    tree=app.render();tree.props.onOK();assert.notDeepEqual(app.confirmed(),rgb);
    assert.ok(app.confirmed().every((value:any)=>Number.isInteger(value)&&value>=0&&value<=255));
  });
}
