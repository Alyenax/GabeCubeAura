import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import {createElement} from 'react';
const source=readFileSync(new URL('../../src/components/QuickInlineChoice.tsx',import.meta.url),'utf8');
const body=source.replace(/^import.*\n/,'').replace('export function','function');
function choice(disabled=false){
 const selected:any[]=[],opened:any[]=[],context=vm.createContext({React:{createElement},DropdownItem:'native-dropdown'});
 vm.runInContext(ts.transpileModule(body+'\nthis.render=QuickInlineChoice;',{compilerOptions:{jsx:ts.JsxEmit.React,module:ts.ModuleKind.CommonJS}}).outputText,context);
 const options=[{data:'none',label:'Do nothing'},{data:'sleep',label:'Sleep'},{data:'shutdown',label:'Shut down'}];
 const tree=context.render({label:'When finished',selectedOption:'sleep',rgOptions:options,disabled,onChange:(v:any)=>selected.push(v.data),onMenuWillOpen:()=>opened.push('opening'),onMenuOpened:()=>opened.push('opened')});
 return{tree,selected,opened,options};
}
test('selection uses the actual Steam DropdownItem and preserves saved option/disabled state',()=>{
 for(const disabled of [false,true]){const ui=choice(disabled);assert.equal(ui.tree.type,'native-dropdown');assert.equal(ui.tree.props.disabled,disabled);assert.equal(ui.tree.props.selectedOption,'sleep');assert.equal(ui.tree.props.rgOptions,ui.options);assert.deepEqual(ui.selected,[]);}
});
test('native menu opening invokes the Steam show callback once without selecting or writing',()=>{
 const ui=choice();let shown=0;ui.tree.props.onMenuWillOpen(()=>shown++);ui.tree.props.onMenuOpened();assert.equal(shown,1);assert.deepEqual(ui.opened,['opening','opened']);assert.deepEqual(ui.selected,[]);
});
test('only a native onChange event forwards a choice; no custom cancel/focus trap remains',()=>{
 const ui=choice();ui.tree.props.onChange(ui.options[2]);assert.deepEqual(ui.selected,['shutdown']);
 assert.doesNotMatch(source,/onCancelButton|\.focus\(|setTimeout|setInterval|showModal|createPortal/);
});
