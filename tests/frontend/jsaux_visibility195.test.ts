import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {quickPanelState} from '../../src/quick_panel';
import {settingsSelection,visibleSettingsCategories,visibleSettingsSelection} from '../../src/settings_structure';
const source=(p:string)=>readFileSync(new URL(p,import.meta.url),'utf8');
test('Lab195: JSAUX UI is absent after disconnect even when recently detected',()=>{
  const status:any={faceplate:{available:false,recently_detected:true},game:{appid:0},current_display:'artwork'};
  assert.equal(quickPanelState(status).faceplateControls,false);
  assert.equal(visibleSettingsCategories(false).some(category=>category.id==='faceplate'),false);
  assert.equal(visibleSettingsCategories(true).some(category=>category.id==='faceplate'),true);
  status.faceplate.available=true;
  assert.equal(quickPanelState(status).faceplateControls,true);
});
test('Lab195: external Faceplate routes fall back and existing status poll is reused',()=>{
  const requested=settingsSelection('faceplate','maintenance');
  assert.deepEqual(visibleSettingsSelection(requested,false),settingsSelection('display','daily'));
  assert.deepEqual(visibleSettingsSelection(requested,true),requested);
  const shell=source('../../src/components/SimpleSettings.tsx');
  assert.match(shell,/pages=\{visibleSettingsCategories\(faceplateConnected\)\.map/);
  assert.match(shell,/if\(faceplateConnected\|\|requestedSelection.category!=='faceplate'\)return/);
  assert.doesNotMatch(shell,/getStatus\(|setTimeout\(|setInterval\(/);
  const index=source('../../src/index.tsx');
  assert.match(index,/onFaceplateConnectionChange\?\.\(next.faceplate.available===true\)/);
  assert.match(index,/onFaceplateConnectionChange=\{setFaceplateConnected\}/);
  assert.doesNotMatch(source('../../src/components/CompactQuickPanel.tsx'),/JSAUX settings/);
});
