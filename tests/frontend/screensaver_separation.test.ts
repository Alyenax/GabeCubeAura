import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import {createElement} from 'react';
import {translate} from '../../src/i18n';

const index=readFileSync(new URL('../../src/index.tsx',import.meta.url),'utf8');
function flatten(node:any):any[]{
  if(Array.isArray(node))return node.flatMap(flatten);
  if(!node||typeof node!=='object')return [];
  if(typeof node.type==='function')return flatten(node.type(node.props));
  return [node,...flatten(node.props?.children)];
}

test('Screensaver dropdown preserves saved modes and gates extension on current hardware detection',async()=>{
  const component=index.slice(index.indexOf('function ScreenSyncPanel'),index.indexOf('function AudioContextMapping'));
  const writes:any[]=[],snapshots:any[]=[];
  const context=vm.createContext({React:{createElement},useState:()=>[false,()=>{}],
    PanelSection:'section',PanelSectionRow:'row',ToggleField:'toggle',ButtonItem:'button',
    SettingsHelpText:({children}:any)=>children,SettingsDetails:({children}:any)=>children,
    DropdownItem:'dropdown',SliderField:'slider',displayLabel:(value:string)=>value,
    SCREEN_SYNC_STYLE_OPTIONS:[],SCREEN_SYNC_REACTIVITY_OPTIONS:[],SCREEN_SYNC_COLOUR_OPTIONS:[],
    setSetting:async(key:string,value:unknown)=>{writes.push([key,value]);return {saved:value};}});
  const choice=readFileSync(new URL('../../src/components/ScreensaverLightBarChoice.tsx',import.meta.url),'utf8');
  vm.runInContext(ts.transpileModule(choice.slice(choice.indexOf('export function')).replace('export function','function'),{
    compilerOptions:{jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2022}}).outputText,context);
  vm.runInContext(ts.transpileModule(component,{compilerOptions:{jsx:ts.JsxEmit.React,
    target:ts.ScriptTarget.ES2022}}).outputText+'\nthis.render=ScreenSyncPanel;',context);
  for(const saved of ['none','screen_sync','faceplate_extension'])for(const detected of [false,true]){
    const status={screen_sync_screensaver_enabled:saved==='screen_sync',screensaver_light_bar_mode:saved,faceplate:{available:detected},
      screen_sync:{activation:{reason:'steam-screensaver'},capture_selector:'',node_id:null},
      game:{appid:0},game_display:'customization',display_override:'inherit'};
    const nodes=flatten(context.render({status,setStatus:(next:any)=>snapshots.push(next)}));
    const choice=nodes.find(node=>node.type==='dropdown'&&node.props.label==='During Steam screensaver');
    assert(choice);assert.equal(choice.props.selectedOption,saved==='faceplate_extension'&&!detected?'none':saved);
    assert.equal(choice.props.rgOptions.some((option:any)=>option.data==='faceplate_extension'),detected);
    assert(nodes.some(node=>node.props?.children==='Following Steam screensaver'));
    await choice.props.onChange({data:'none'});
    assert.deepEqual(writes.at(-1),['screensaver_light_bar_mode','none']);
    assert.deepEqual(snapshots.at(-1),{saved:'none'});
  }
});

test('screensaver separation is localized, recoverable and has no Studio frontend RPC',()=>{
  for(const text of ['During Steam screensaver',
    'Syncs the light bar with any compatible Steam screensaver. Your usual display returns when it closes. This does not enable the JSAUX matrix.']){
    assert.equal(translate(text,'en'),text);assert.notEqual(translate(text,'fr'),text);
  }
  assert.doesNotMatch(index,/Previous screensaver collections|advanced\.migration/);
  assert.doesNotMatch(index,/settings\/screensaver|showPage\("screensaver"\)|studioClient|AnimatedScreensaverStudio/);
  const api=readFileSync(new URL('../../src/api.ts',import.meta.url),'utf8');
  assert.doesNotMatch(api,/animated_screensaver_studio|set_cinema_context|cinemaClient|studioClient/);
  assert.match(api,/set_screen_sync_context/);
  assert.match(index,/status\.screensaver_light_bar_mode === "faceplate_extension" \? <>/,
    'Display routing must expose its existing mapping even when only screensaver extension is selected');
  for(const text of ['No screensaver effect','Faceplate extension',
    'Temporarily follows the screen or the Faceplate image, then restores your usual lighting. Extension uses the mapping selected in Display routing. None keeps your usual lighting.']){
    assert.notEqual(translate(text,'fr'),text);
  }
});
