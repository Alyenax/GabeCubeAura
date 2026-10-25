import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {faceplateBrightnessNotice,FACEPLATE_BRIGHTNESS_NOTE} from '../../src/faceplate_power';
import {translate} from '../../src/i18n';

test('manual brightness has a short neutral notice only above seventy percent',()=>{
  for(const value of [5,50,70,NaN,Infinity])assert.equal(faceplateBrightnessNotice(value),null);
  for(const value of [71,75,100])assert.equal(faceplateBrightnessNotice(value),FACEPLATE_BRIGHTNESS_NOTE);
  assert.equal(translate(FACEPLATE_BRIGHTNESS_NOTE,'fr'),'Au-delà de 70 %, la stabilité dépend de l’alimentation USB.');
  assert.equal(translate(FACEPLATE_BRIGHTNESS_NOTE,'en'),FACEPLATE_BRIGHTNESS_NOTE);
});

test('every faceplate brightness editor renders neutral status copy from its pending choice',()=>{
  for(const path of ['src/index.tsx','src/components/AmbienceProfilesPanel.tsx']){
    const source=readFileSync(new URL('../../'+path,import.meta.url),'utf8');
    assert.match(source,/faceplateBrightnessNotice\(/);
    assert.match(source,/<small role="status">\{faceplateBrightnessNotice/);
    assert.doesNotMatch(source,/usbProtectionNotice/);
  }
});

test('quick panel omits both advisory messages while options retain them',()=>{
  const quick=readFileSync(new URL('../../src/components/CompactQuickPanel.tsx',import.meta.url),'utf8');
  assert.doesNotMatch(quick,/faceplateBrightnessNotice|Above 70%|See the Dashboard tab/);
  const settings=readFileSync(new URL('../../src/index.tsx',import.meta.url),'utf8');
  assert.match(settings,/faceplateBrightnessNotice/);assert.equal(settings.match(/See the Dashboard tab to configure your choices\./g)?.length,2);
});
