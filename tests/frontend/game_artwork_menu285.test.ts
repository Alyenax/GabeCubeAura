import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import {createElement,cloneElement,isValidElement,Component} from 'react';
import {addGameArtworkItem,artworkGamePath,GAME_ARTWORK_ITEM,menuAppId,menuItemLabel,steamAppId} from '../../src/game_artwork_menu';
const launch=()=>{const launchSource='library';return launchSource;};
const properties=()=>{const AppProperties=true;return AppProperties;};
function menu(appid?:number){return [createElement('item',{key:'launch',onSelected:launch,...(appid?{app:{appid}}:{})}),
 createElement('item',{key:'sgdb-change-artwork'}),createElement('item',{key:'properties',onSelected:properties})];}

test('only an identified game menu is decorated; other plugins and source arrays stay intact',()=>{
 const original=Object.freeze(menu(620));
 const next=addGameArtworkItem(original as any,undefined,id=>createElement('our-item',{key:GAME_ARTWORK_ITEM,appid:id}));
 assert.notEqual(next,original);assert.deepEqual(next.map((n:any)=>n.key),['launch','sgdb-change-artwork',GAME_ARTWORK_ITEM,'properties']);
 assert.equal((next[2] as any).props.appid,620);assert.equal(original.length,3);
 const duplicate=addGameArtworkItem(next,undefined,id=>createElement('our-item',{key:GAME_ARTWORK_ITEM,appid:id}));
 assert.equal(duplicate.filter((n:any)=>n.key===GAME_ARTWORK_ITEM).length,1);
 const media=[createElement('item',{key:'properties'})];assert.equal(addGameArtworkItem(media,620,()=>{throw new Error('not a game');}),media);
});

test('a nested child array is not mistaken for the outer menu container',()=>{
 const inner=menu(620),outer=[inner];assert.equal(addGameArtworkItem(outer,620,()=>{throw new Error('outer array');}),outer);
});

test('visible game identity overrides a stale owner; ambiguity and missing IDs never guess a game',()=>{
 assert.equal(menuAppId(menu(730),620),730);
 assert.equal(menuAppId([...menu(620),createElement('item',{app:{appid:730}})],620),null);
 const original=menu();assert.equal(addGameArtworkItem(original,undefined,()=>{throw new Error('no default app');}),original);
 for(const value of [0,-1,NaN,1.5,{},'620x',true,0x100000000])assert.equal(steamAppId(value),null);
 assert.equal(artworkGamePath(0xffffffff),'/gabecubeaura/faceplate-artwork/4294967295');
});

test('only the GCA French setting changes the native menu label',()=>{
 assert.match(menuItemLabel('fr'),/^Illustration/);for(const language of ['en','de',undefined])assert.equal(menuItemLabel(language),'JSAUX Faceplate artwork…');
});

function hook(available=true,buildInside=false,detected=true){
 let lang='en',now=1000;const paths:string[]=[],timers:Function[]=[],patches:any[]=[];
 class MenuRoot extends Component<any>{render(){return createElement('native-menu',{},this.props.makeItems?this.props.makeItems():this.props.children);}}
 function Layer(props:any){return createElement(MenuRoot,buildInside?{makeItems:()=>menu()}:{children:props.children});}
 class LibraryContextMenu{constructor(public props:any){}render(){return createElement(Layer,{children:menu()});}}
 const original=LibraryContextMenu.prototype.render;
 function findMarker(){return '().LibraryContextMenu';}
 function wrapper(){return 'navigator:';}
 const context=vm.createContext({exports:{},Date:{now:()=>now},React:{createElement},cloneElement,isValidElement,
  addGameArtworkItem,artworkGamePath,GAME_ARTWORK_ITEM,menuAppId,menuItemLabel,getUILanguage:()=>lang,
  MenuItem:'our-item',Navigation:{CloseSideMenus(){},Navigate:(path:string)=>paths.push(path)},
  findModuleByExport:(predicate:Function)=>available&&predicate(findMarker)?{wrapper}:undefined,
  fakeRenderComponent:()=>({type:LibraryContextMenu}),
  setTimeout:(fn:Function)=>{timers.push(fn);return timers.length;},clearTimeout(){},
  afterPatch:(object:any,key:string,handler:Function)=>{const previous=object[key];const patch={hasUnpatched:false,unpatch(){object[key]=previous;patch.hasUnpatched=true;}};
    object[key]=function(...args:any[]){return handler.call(this,args,previous.apply(this,args));};patches.push(patch);return patch;},
 });
 const source=readFileSync(new URL('../../src/game_artwork_menu_patch.tsx',import.meta.url),'utf8').replace(/^import .*;\n/gm,'');
 vm.runInContext(ts.transpileModule(source,{compilerOptions:{jsx:ts.JsxEmit.React,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,context);
 const controller=context.exports.startGameArtworkMenu();
 if(detected)controller.setFaceplateAvailable(true);
 const render=(appid:number)=>{
  let element:any=new LibraryContextMenu({overview:{appid}}).render();
  for(let i=0;i<5&&typeof element.type==='function';i++)element=element.type.prototype?.render?new element.type(element.props).render():element.type(element.props);
  return element.props.children;
 };
 return {controller,render,paths,patches,timers,advance:(ms:number)=>{now+=ms;},setLanguage:(next:string)=>{lang=next;},original,current:()=>LibraryContextMenu.prototype.render};
}

test('native wrapper reuses component types without retaining the previous game ID',()=>{
 const ui=hook();assert.equal(ui.controller.available,true);
 const first=ui.render(620),second=ui.render(730);
 first.find((n:any)=>n.key===GAME_ARTWORK_ITEM).props.onSelected();second.find((n:any)=>n.key===GAME_ARTWORK_ITEM).props.onSelected();
 assert.deepEqual(ui.paths,['/gabecubeaura/faceplate-artwork/620','/gabecubeaura/faceplate-artwork/730']);
 ui.setLanguage('fr');assert.equal(ui.render(730).find((n:any)=>n.key===GAME_ARTWORK_ITEM).props.children,'Illustration JSAUX Faceplate…');
 const retained=second.find((n:any)=>n.key===GAME_ARTWORK_ITEM);ui.controller.stop();retained.props.onSelected();assert.equal(ui.paths.length,2);
 assert.equal(ui.current(),ui.original);assert(ui.patches.every(p=>p.hasUnpatched));ui.controller.stop();
});

test('unsupported Steam builds remain usable and retries are bounded and cancellable',()=>{
 const ui=hook(false);assert.equal(ui.controller.available,false);assert.equal(ui.timers.length,3);
 for(const retry of ui.timers)retry();assert.equal(ui.patches.length,0);ui.controller.stop();
 for(const retry of ui.timers)retry();assert.equal(ui.patches.length,0);
});


test('a class-rendered menu retains the current context even when items are built inside render',()=>{
 const ui=hook(true,true);const first=ui.render(620),second=ui.render(730);
 first.find((n:any)=>n.key===GAME_ARTWORK_ITEM).props.onSelected();second.find((n:any)=>n.key===GAME_ARTWORK_ITEM).props.onSelected();
 assert.deepEqual(ui.paths,['/gabecubeaura/faceplate-artwork/620','/gabecubeaura/faceplate-artwork/730']);ui.controller.stop();
});


test('native game entry stays hidden without a detected Faceplate and follows hotplug evidence',()=>{
 const ui=hook(true,false,false);
 assert.deepEqual(ui.render(620).map((n:any)=>n.key),['launch','sgdb-change-artwork','properties']);
 ui.controller.setFaceplateAvailable(true);
 const connected=ui.render(620);const item=connected.find((n:any)=>n.key===GAME_ARTWORK_ITEM);assert.ok(item);
 item.props.onSelected();assert.equal(ui.paths.length,1);
 ui.controller.setFaceplateAvailable(false);
 assert.equal(ui.render(620).some((n:any)=>n.key===GAME_ARTWORK_ITEM),false);
 item.props.onSelected();assert.equal(ui.paths.length,1);
 ui.controller.setFaceplateAvailable(true);assert.ok(ui.render(730).find((n:any)=>n.key===GAME_ARTWORK_ITEM));
 ui.controller.stop();ui.controller.setFaceplateAvailable(true);item.props.onSelected();assert.equal(ui.paths.length,1);
});


test('unknown or stale hardware evidence cannot expose a game entry',()=>{
 const ui=hook(true,false,false);
 assert.equal(ui.render(620).some((n:any)=>n.key===GAME_ARTWORK_ITEM),false);
 ui.controller.setFaceplateAvailable(true);const item=ui.render(620).find((n:any)=>n.key===GAME_ARTWORK_ITEM);assert.ok(item);
 ui.advance(15001);assert.equal(ui.render(620).some((n:any)=>n.key===GAME_ARTWORK_ITEM),false);
 item.props.onSelected();assert.equal(ui.paths.length,0);
 ui.controller.setFaceplateAvailable(true);assert.ok(ui.render(620).find((n:any)=>n.key===GAME_ARTWORK_ITEM));ui.controller.stop();
});

function weatherObserver(onStatus:(status:any)=>void,weatherFails=false){
 let resolve!:(status:any)=>void,reject!:(error:Error)=>void,calls=0;let tick!:()=>void,cleared=false;
 const context=vm.createContext({exports:{},getStatus:()=>{calls++;return new Promise((yes,no)=>{resolve=yes;reject=no;});},
  weatherTopBarReading:()=>{if(weatherFails)throw new Error('weather UI unavailable');return null;},window:{setInterval(fn:()=>void,delay:number){assert.equal(delay,5000);tick=fn;return 1;},clearInterval(){cleared=true;},clearTimeout(){}},
 });
 const source=readFileSync(new URL('../../src/weather_topbar.ts',import.meta.url),'utf8').replace(/^import .*;\n/gm,'');
 vm.runInContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,context);
 const indicator=context.exports.startWeatherTopBar(onStatus);
 return {indicator,tick:()=>tick(),resolve:(status:any)=>resolve(status),reject:()=>reject(new Error('RPC unavailable')),calls:()=>calls,cleared:()=>cleared};
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));

test('existing status poll controls the menu even with weather disabled; errors and teardown hide it',async()=>{
 const ui=hook(true,false,false);const observer=weatherObserver(status=>ui.controller.setFaceplateAvailable(status?.faceplate?.available===true));
 assert.equal(ui.render(620).some((n:any)=>n.key===GAME_ARTWORK_ITEM),false);
 observer.resolve({weather_topbar_enabled:false,faceplate:{available:true,enabled:false}});await flush();
 assert.ok(ui.render(620).find((n:any)=>n.key===GAME_ARTWORK_ITEM));
 observer.tick();observer.resolve({faceplate:{available:false}});await flush();
 assert.equal(ui.render(620).some((n:any)=>n.key===GAME_ARTWORK_ITEM),false);
 observer.tick();observer.resolve({faceplate:{available:true}});await flush();
 const item=ui.render(620).find((n:any)=>n.key===GAME_ARTWORK_ITEM);assert.ok(item);
 observer.tick();observer.reject();await flush();
 assert.equal(ui.render(620).some((n:any)=>n.key===GAME_ARTWORK_ITEM),false);item.props.onSelected();assert.equal(ui.paths.length,0);
 observer.tick();observer.indicator.stop();ui.controller.stop();observer.resolve({faceplate:{available:true}});await flush();
 assert.equal(observer.cleared(),true);assert.equal(observer.calls(),5);item.props.onSelected();assert.equal(ui.paths.length,0);
});


test('a weather UI failure does not revoke a successful hardware observation',async()=>{
 const ui=hook(true,false,false);const observer=weatherObserver(status=>ui.controller.setFaceplateAvailable(status?.faceplate?.available===true),true);
 observer.resolve({faceplate:{available:true}});await flush();assert.ok(ui.render(620).find((n:any)=>n.key===GAME_ARTWORK_ITEM));
 observer.indicator.stop();ui.controller.stop();
});
