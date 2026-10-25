import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
const root=new URL('../../',import.meta.url);
const css=readFileSync(new URL('src/components/compact_quick_style.ts',root),'utf8');
const component=readFileSync(new URL('src/components/CompactQuickPanel.tsx',root),'utf8');

test('compact controls retain Steam paint, focus, and toggle/slider geometry',()=>{
  assert.doesNotMatch(css,/ToggleRail|ToggleSwitch|SliderHandle|SliderTrack|outline:|box-shadow:/);
  assert.doesNotMatch(css,/#gca-compact-root \*/);
  assert.doesNotMatch(css,/gca-compact-title|gca-quick-choice-trigger/);
});
test('compact native sections own gutters and selectors own their measured widths',()=>{
  assert.match(component,/<PanelSection/);assert.match(component,/<PanelSectionRow/);
  assert.doesNotMatch(css,/DialogDropDown|\.DialogButton|gca-quick-choice/);
  assert.doesNotMatch(css,/#gca-compact-root\{[^}]*padding:/);
});
