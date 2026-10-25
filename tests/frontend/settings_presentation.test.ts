import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import {createElement,Fragment} from 'react';
import {settingsSlotVisible} from '../../src/settings_structure';
const source=readFileSync(new URL('../../src/settings_presentation.tsx',import.meta.url),'utf8');
function mount(selection:any=null){
 const registry=new Map();let current:any=selection?{selection,help:registry}:null;const effects:any[]=[];
 const context=vm.createContext({exports:{},React:{createElement,Fragment},
  createContext:()=>({}),useContext:()=>current,useRef:(value:any)=>({current:value}),useEffect:(fn:any)=>effects.push(fn),settingsSlotVisible,
  getUILanguage:()=> 'fr',translateNode:(value:any)=>value,
  DialogButton:'button',ConfirmModal:'modal',ScrollPanel:'scroll',showModal:()=>assert.fail('no modal on render'),
 });
 const ast=ts.createSourceFile('presentation.tsx',source,99,true,4),body=ast.statements.filter(n=>!ts.isImportDeclaration(n)).map(n=>n.getText(ast)).join('\n');
 vm.runInContext(ts.transpileModule(body,{compilerOptions:{jsx:ts.JsxEmit.React,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,context);
 return {api:context.exports,registry,effects,set:(value:any)=>{current=value;}};
}
test('outside settings, native descriptions and children remain intact and no help state is registered',()=>{
 const app=mount(),child=createElement('test',{id:'original'});
 const part=app.api.SettingsPart({slot:'faceplate.display',children:child});assert.equal(part.props.children,child);
 const help=app.api.SettingsHelpText({children:child});assert.equal(help.props.children,child);
 app.effects.forEach(fn=>assert.equal(fn(),undefined));assert.equal(app.registry.size,0);
});
test('settings slot mounts children only at its declared destination, independent of translations',()=>{
 const app=mount({category:'faceplate',tab:'dashboard'}),child=createElement('test');
 assert.equal(app.api.SettingsPart({slot:'faceplate.display',children:child}),null);
 assert.equal(app.api.SettingsPart({slot:['faceplate.display','faceplate.dashboard'],children:child}).props.children,child);
});
test('contextual help registers only its label and copy and releases the entry on unmount',()=>{
 const app=mount({category:'display',tab:'daily'}),body=createElement('p',{},'Explanation');
 assert.equal(app.api.SettingsHelpText({label:'Brightness',children:body}),null);
 const cleanup=app.effects[0]();assert.equal(app.registry.size,1);
 assert.deepEqual(Object.keys([...app.registry.values()][0]),['label','body']);
 cleanup();assert.equal(app.registry.size,0);
});
