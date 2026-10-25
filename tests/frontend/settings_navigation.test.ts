import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {SETTINGS_TAB_INDICATOR,focusSettingsTab,initialSettingsEffect,EFFECTS_HELP} from '../../src/settings_navigation';
import {SETTINGS_ALIASES} from '../../src/settings_structure';
import {translate} from '../../src/i18n';

test('headers are native nonfocusable indicators; effect deep link resolves exact subtab',()=>{
 assert.equal(SETTINGS_TAB_INDICATOR.focusable,false);assert.equal(SETTINGS_TAB_INDICATOR.preferredFocus,false);
 assert.equal(SETTINGS_TAB_INDICATOR.onFocus(),undefined);assert.equal(SETTINGS_TAB_INDICATOR.onActivate(),undefined);
 assert.deepEqual(SETTINGS_ALIASES.artwork,{category:'display',tab:'effects'});
 assert.equal(initialSettingsEffect(undefined,42),'artwork');assert.equal(initialSettingsEffect(undefined,0),'customization');
 assert.equal(initialSettingsEffect('artwork',0),'artwork');
 assert.match(translate(EFFECTS_HELP,'en'),/Configure Customization\+ effects or/);
 assert.notEqual(translate(EFFECTS_HELP,'fr'),EFFECTS_HELP);
});
test('profile names remain protected and saved ambience controls do not advertise voice',()=>{
 const profile=readFileSync(new URL('../../src/components/AmbienceProfilesPanel.tsx',import.meta.url),'utf8');
 assert.match(profile,/<span translate="no">\{item.name\}<\/span>/);
 assert.doesNotMatch(profile,/\bGabe\b|voice activation|vocal|assistant/i);
});
function harness(){
 let id=0,active=true,ready=false;const pending=new Map<number,()=>void>(),taken:number[]=[];
 const stop=focusSettingsTab(()=>ready?{TakeFocus:(direction?:number)=>{taken.push(direction!);return true;}}:undefined,
  ()=>active,fn=>{pending.set(++id,fn);return id;},key=>pending.delete(key),12);
 return{taken,pending,stop,setReady(){ready=true;},leave(){active=false;},frame(){const entries=[...pending];pending.clear();for(const[,fn]of entries)fn();}};
}
test('explicit content tab change focuses first through native ref only after native restore',()=>{
 const ui=harness();ui.setReady();ui.frame();ui.frame();assert.deepEqual(ui.taken,[]);
 ui.frame();assert.deepEqual(ui.taken,[12]);assert.equal(ui.pending.size,0);
});
test('slow content registration is bounded; moving to sidebar or unmount cancels focus theft',()=>{
 const delayed=harness();for(let i=0;i<5;i++)delayed.frame();delayed.setReady();delayed.frame();assert.deepEqual(delayed.taken,[12]);
 const left=harness();left.setReady();left.frame();left.leave();left.frame();assert.deepEqual(left.taken,[]);assert.equal(left.pending.size,0);
 const gone=harness();gone.setReady();gone.stop();gone.frame();assert.deepEqual(gone.taken,[]);
 const missing=harness();for(let i=0;i<30;i++)missing.frame();assert.equal(missing.pending.size,0);assert.deepEqual(missing.taken,[]);
});
test('content entry resets natively; headers/B are not captured and no DOM focus scan is shipped',()=>{
 const src=readFileSync(new URL('../../src/components/SimpleSettings.tsx',import.meta.url),'utf8');
 assert.match(src,/cancelSkipTabHeader/);assert.match(src,/footer:SETTINGS_TAB_INDICATOR/);
 assert.match(src,/resetNavOnEntry:true/);assert.match(src,/navEntryPreferPosition=\{NavEntryPositionPreferences.FIRST\}/);
 assert.doesNotMatch(src,/document\.querySelector|\.focus\(|onCancelButton|onGamepadDirection/);
 const css=readFileSync(new URL('../../src/settings_theme.ts',import.meta.url),'utf8');
 assert.doesNotMatch(css,/\$\{N.sidebarActive\}\{/);
 assert.doesNotMatch(css,/outline:|box-shadow:/);
});
