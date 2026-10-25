import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {QUICK_AMBIENCES,LEGACY_AMBIENCES,presetSummary,quickAmbienceOptions} from '../../src/lighting_presets';
import {translate} from '../../src/i18n';

test('quick preset order is Custom first then all six requested named presets',()=>{
 assert.deepEqual(QUICK_AMBIENCES.map(p=>p.data),['custom','moderate','atmosphere','signals','immersive','immersive-plus','festive']);
 assert.deepEqual(QUICK_AMBIENCES.map(p=>p.label),['Custom','Moderate','Atmosphere','Signals','Immersive','Immersive+','Festive']);
 assert.equal(new Set(QUICK_AMBIENCES.map(p=>p.data)).size,7);
 for(const option of LEGACY_AMBIENCES){
  const options=quickAmbienceOptions(option.data);assert.equal(options.length,8);assert.equal(options.at(-1)?.label,option.label);
 }
});
test('every preset has a short translated summary; full settings retain detailed help and old modes',()=>{
 for(const option of [...QUICK_AMBIENCES,...LEGACY_AMBIENCES]){
  const summary=presetSummary(option.data);assert(summary.length>10&&summary.length<=90);
  assert.notEqual(translate(summary,'fr'),summary);assert.equal(translate(summary,'en'),summary);
 }
 const source=readFileSync(new URL('../../src/index.tsx',import.meta.url),'utf8');
 assert.match(source,/\.\.\.QUICK_AMBIENCES,\.\.\.LEGACY_AMBIENCES/);
 assert.match(source,/className="gca-preset-summary"/);
 assert.match(source,/DISPLAY_PRESET_DESCRIPTIONS\[status.display_preset\]/,'Detailed help remains');
});
test('settings retain the Steam label palette across every hardware category',()=>{
 const theme=readFileSync(new URL('../../src/settings_theme.ts',import.meta.url),'utf8');
 assert.doesNotMatch(theme,/gca-faceplate-label|--gca-field-label|data-gca-active-category/);
});
