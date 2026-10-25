import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const file=(path:string)=>readFileSync(new URL(path,import.meta.url),'utf8');
test('Lab194 prioritises frequently used lighting before timer',()=>{
  const panel=file('../../src/components/CompactQuickPanel.tsx');
  assert.ok(panel.indexOf('className="gca-compact-light"')<panel.indexOf('className="gca-compact-timer"'));
  assert.match(panel,/className="gca-compact-led-caption"/);
  assert.doesNotMatch(panel,/JSAUX settings/);
});
test('Lab194 leaves Steam page transitions and focus ownership intact',()=>{
  const page=file('../../src/components/SimpleSettings.tsx');
  assert.match(page,/\bSidebarNavigation\b/);
  assert.match(page,/<Tabs\b/);
  assert.doesNotMatch(page,/className="gca-page-count"/);
  const css=file('../../src/settings_theme.ts');
  assert.doesNotMatch(css,/transition:\s*none/);
  assert.doesNotMatch(css,/transition-duration|tabHeader|sidebarColumn/);
});
