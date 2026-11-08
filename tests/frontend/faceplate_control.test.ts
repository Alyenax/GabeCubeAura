import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {faceplateControlLabel} from '../../src/faceplate_control';
import {SETTINGS_CATEGORIES,settingsSlotVisible} from '../../src/settings_structure';
import {translate} from '../../src/i18n';

test('Priority is a Faceplate Settings tab and has no quick-panel selector',()=>{
  const tabs=SETTINGS_CATEGORIES.find(c=>c.id==='faceplate')!.tabs.map(t=>t[0]);
  assert.deepEqual(tabs,['display','dashboard','artwork','priority','maintenance']);
  assert.equal(settingsSlotVisible({category:'faceplate',tab:'priority'},'faceplate.priority'),true);
  assert.equal(settingsSlotVisible({category:'faceplate',tab:'display'},'faceplate.priority'),false);
  const quick=readFileSync(new URL('../../src/components/CompactQuickPanel.tsx',import.meta.url),'utf8');
  assert.doesNotMatch(quick,/FaceplatePrioritySettings|faceplate_control_mode|Priority settings/);
});

test('release pending never claims that USB is already free',()=>{
  const status={faceplate_control_mode:'other-app' as const,faceplate_control:{phase:'releasing'} as any};
  assert.equal(faceplateControlLabel(status),'Releasing Faceplate access...');
  status.faceplate_control.phase='released';
  assert.equal(faceplateControlLabel(status),'USB access released to other apps');
  assert.equal(faceplateControlLabel({faceplate_control_mode:'other-app'}),'Releasing Faceplate access...');
});

test('priority waits for the actual descriptor and does not claim visible playback',()=>{
  const status={faceplate_control_mode:'gca-priority' as const,faceplate_control:{phase:'waiting'} as any};
  assert.equal(faceplateControlLabel(status),'Waiting to reserve the Faceplate');
  status.faceplate_control.phase='reserved';
  assert.equal(faceplateControlLabel(status),'USB reserved for GCA');
});

test('priority controls and states have English/French product copy',()=>{
  for(const text of ['Faceplate control','GCA Priority','Other app','Allow Decky Animated Screensaver','Allow Decky Vocal Assistant','USB reserved for GCA','Releasing Faceplate access...']){
    assert.equal(translate(text,'en'),text);assert.notEqual(translate(text,'fr'),text);
  }
});
