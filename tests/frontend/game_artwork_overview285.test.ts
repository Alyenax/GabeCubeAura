import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import {readFileSync} from 'node:fs';
import {createElement,Fragment} from 'react';
import {artworkGamePath,GAME_ARTWORK_ROUTE,steamGameTitle} from '../../src/game_artwork_menu';
const entries=[{appid:620,name:'Portal 2',source:'artwork',animated:false,thumb:''},{appid:730,name:'Counter-Strike',source:'layout',animated:false,thumb:''}];
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function mount(language='en',reset:(id:number)=>Promise<any>=async()=>({})){let cursor=0;const hooks:any[]=[],cleanup:Function[]=[];
 const paths:string[]=[],modals:any[]=[],statuses:any[]=[],requests:number[]=[];
 const context=vm.createContext({exports:{},React:{createElement,Fragment},
  useState:(value:any)=>{const i=cursor++;if(!(i in hooks))hooks[i]=value;return[hooks[i],(next:any)=>{hooks[i]=typeof next==='function'?next(hooks[i]):next;}];},
  useRef:(value:any)=>{const i=cursor++;return hooks[i]??={current:value};},
  useEffect:(fn:Function)=>{const i=cursor++;if(!(i in hooks)){hooks[i]=true;cleanup.push(fn());}},
  getFaceplateGameArtworkOverrides:async()=>({entries,count:2}),resetFaceplateGameArtwork:(id:number)=>{requests.push(id);return reset(id);},
  getGamepadNavigationTrees:()=>[],takeArtworkNativeFocus:()=>false,
  Navigation:{CloseSideMenus(){},Navigate:(path:string)=>paths.push(path)},showModal:(node:any)=>{modals.push(node);return{Close(){}};},
  artworkGamePath,GAME_ARTWORK_ROUTE,steamGameTitle,
  ButtonItem:'action',DialogButton:'button',ConfirmModal:'confirm',PanelSection:'section',PanelSectionRow:'row',TextField:'input',Focusable:'focusable',Localized:'localized',
 });
 const source=readFileSync(new URL('../../src/components/GameArtworkOverview.tsx',import.meta.url),'utf8').replace(/^import .*;\n/gm,'');
 vm.runInContext(ts.transpileModule(source,{compilerOptions:{jsx:ts.JsxEmit.React,module:ts.ModuleKind.CommonJS}}).outputText,context);
 return{paths,modals,statuses,requests,render(){cursor=0;return context.exports.GameArtworkOverview({status:{ui_language:language},setStatus:(next:any)=>statuses.push(next)});},unmount(){cleanup.forEach(fn=>fn?.());}};
}
function nodes(value:any):any[]{return Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?[value,...nodes(value.props?.children)]:[];}
function text(value:any):string{return Array.isArray(value)?value.map(text).join(' '):value&&typeof value==='object'?text(value.props?.children):String(value??'');}

test('overview opens only saved customizations, edits the chosen game and leaves other controls unchanged',async()=>{
 const ui=mount();ui.render();await flush();const tree=ui.render();
 assert.equal(ui.requests.length,0);assert.equal(nodes(tree).filter(n=>n.props?.translate==='no').length,2);
 const edits=nodes(tree).filter(n=>n.type==='button'&&text(n)==='Edit artwork');edits[1].props.onClick();
 assert.deepEqual(ui.paths,['/gabecubeaura/faceplate-artwork/730']);
 const choose=nodes(tree).find(n=>n.type==='action');choose.props.onClick();assert.equal(ui.paths.at(-1),GAME_ARTWORK_ROUTE);ui.unmount();
});

test('reset requires confirmation and duplicate callbacks send one exact app ID',async()=>{
 let resolve!:(v:any)=>void;const ui=mount('en',()=>new Promise(done=>{resolve=done;}));ui.render();await flush();
 nodes(ui.render()).find(n=>n.type==='button'&&text(n)==='Use default').props.onClick();
 assert.equal(ui.requests.length,0);ui.modals[0].props.onCancel();assert.equal(ui.requests.length,0);
 nodes(ui.render()).find(n=>n.type==='button'&&text(n)==='Use default').props.onClick();
 ui.modals[1].props.onOK();ui.modals[1].props.onOK();assert.deepEqual(ui.requests,[620]);assert.equal(ui.statuses.length,0);
 resolve({restored:620});await flush();assert.equal(ui.statuses[0].restored,620);ui.unmount();
});

test('French appears only when GCA settings use French, and reset errors stay retryable',async()=>{
 const ui=mount('fr',async()=>{throw new Error('private backend message');});ui.render();await flush();
 const tree=ui.render();assert.equal(tree.props.title,'Jeux personnalisés');assert(nodes(tree).some(n=>n.type==='button'&&text(n)==='Modifier l’illustration'));
 nodes(tree).find(n=>n.type==='button'&&text(n)==='Par défaut').props.onClick();ui.modals[0].props.onOK();await flush();
 assert.match(text(ui.render()),/n’a pas pu être rétabli/);assert.doesNotMatch(text(ui.render()),/private backend message/);assert.equal(ui.statuses.length,0);ui.unmount();
 const en=mount('de');assert.equal(en.render().props.title,'Customized games');en.unmount();
});
