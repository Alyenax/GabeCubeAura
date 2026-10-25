import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import {createElement,Fragment} from 'react';
import {FACEPLATE_GAME_OPTIONS,FACEPLATE_HOME_OPTIONS,homeFaceChoice,isDashboardChoice} from '../../src/faceplate_choices';
import {translate} from '../../src/i18n';

const source=readFileSync(new URL('../../src/components/CreationBackupSettings.tsx',import.meta.url),'utf8');
const nodes=(node:any):any[]=>!node?[]:Array.isArray(node)?node.flatMap(nodes):[node,...nodes(node.props?.children)];
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function harness(){
  const hooks:any[]=[];let index=0,reads=0,complete:any;
  const uploads:any[]=[],opens:string[]=[];
  const context=vm.createContext({React:{createElement,Fragment},
    useRef:(value:any)=>{const at=index++;return hooks[at]??={current:value};},
    useState:(value:any)=>{const at=index++;if(!(at in hooks))hooks[at]=value;return [hooks[at],(v:any)=>{hooks[at]=v;}];},
    getFaceplateArtworkLibrary:async()=>{reads++;return {entries:[{appid:620,name:'Example',mode:'animated',active:true,sha256:'abc'},
      {appid:620,name:'Example',mode:'static',active:false,sha256:'def'}]};},
    exportCreation:(...args:any[])=>{uploads.push(args);return new Promise(resolve=>{complete=resolve;});},
    ButtonItem:'button',DropdownItem:'dropdown',PanelSectionRow:'row',Localized:'localized'});
  vm.runInContext(ts.transpileModule(source.replace(/^import .*$/gm,'').replace('export function','function'),
    {compilerOptions:{jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2020}}).outputText+'\nthis.component=CreationBackupSettings;',context);
  return {uploads,opens,get reads(){return reads;},complete(value:any){complete(value);},render(connected=true){index=0;return nodes(context.component({connected,open:(url:string)=>opens.push(url)}));}};
}

test('Display catalogues follow the exact hierarchy and preserve legacy Home artwork',()=>{
  assert.deepEqual(FACEPLATE_GAME_OPTIONS.map(x=>x.label),['Steam Players City','Artwork','Dashboard Artwork','Weather','Dashboard Weather']);
  assert.deepEqual(FACEPLATE_HOME_OPTIONS.slice(0,4),FACEPLATE_GAME_OPTIONS.slice(1));
  assert.equal(FACEPLATE_HOME_OPTIONS.at(-1)?.data,'native-clock');
  const legacy:any={faceplate_dashboard_home_source:'artwork',faceplate:{routing:{routes:{home:'dashboard'}}}};
  assert.equal(homeFaceChoice(legacy),'artwork-dashboard');legacy.faceplate.routing.routes.home='artwork';assert.equal(homeFaceChoice(legacy),'artwork');
  for(const option of FACEPLATE_GAME_OPTIONS)assert.equal(isDashboardChoice(option.data),option.label.startsWith('Dashboard'));
  assert.equal(translate('See the Dashboard tab to configure your choices.','fr'),'Voir l’onglet Dashboard pour paramétrer ses choix.');
  const dashboard=readFileSync(new URL('../../src/components/FaceplateDashboardSettings.tsx',import.meta.url),'utf8');
  assert.doesNotMatch(dashboard,/write\('faceplate_dashboard_home_source'|label="Dashboard at Home"/);
  const app=readFileSync(new URL('../../src/index.tsx',import.meta.url),'utf8');
  assert.equal(app.match(/See the Dashboard tab to configure your choices\./g)?.length,2);
  const prepare=app.slice(app.indexOf('      if (useForDashboardHome) {'),app.indexOf('      const removed ='));
  assert.doesNotMatch(prepare,/setFaceplateRouting|faceplate_dashboard_home_source/,'Applying game artwork leaves Home selection to Display');
});

test('retriever is manual, sends the exact selected active digest once, and exposes its receipt',async()=>{
  const ui=harness();ui.render();assert.equal(ui.reads,0);assert.deepEqual(ui.uploads,[]);
  ui.render(false).find(n=>n.type==='button').props.onClick();await flush();assert.equal(ui.reads,0);
  ui.render().find(n=>n.type==='button').props.onClick();await flush();assert.equal(ui.reads,1);
  const selector=ui.render().find(n=>n.type==='dropdown');assert.equal(selector.props.rgOptions.length,2,'Inactive variants are excluded');
  assert.equal(ui.render().find(n=>n.props?.label==='Export creation locally').props.disabled,true);
  selector.props.onChange({data:'620'});
  let button=ui.render().find(n=>n.props?.label==='Export creation locally');button.props.onClick();button.props.onClick();
  assert.deepEqual(ui.uploads,[[620,'animated','abc']]);
  assert.equal(ui.render().find(n=>n.type==='dropdown').props.disabled,true);
  ui.complete({path:'/Documents/creation.zip',url:'private-commit-url',digest:'digest'});await flush();
  assert.equal(ui.opens.length,0);assert.equal(ui.uploads.length,1);
  assert(ui.render().some(n=>String(n.props?.children).includes('/Documents/creation.zip')));
  assert.match(readFileSync(new URL('../../src/index.tsx',import.meta.url),'utf8'),/<CreationBackupSettings connected=\{status.faceplate.available\}/);
});
