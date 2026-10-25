import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

test('a missing shared Steam title class cannot abort the plugin initializer', () => {
  const source = readFileSync(new URL('../../src/index.tsx', import.meta.url), 'utf8');
  const expression = source.match(/titleView: <div className=\{([^}]+)\}/)?.[1];
  assert.equal(expression, "[staticClasses?.Title,'gca-compact-title'].filter(Boolean).join(' ')");
  const getClass = new Function('staticClasses', `return ${expression}`);
  assert.equal(getClass(undefined), 'gca-compact-title');
  assert.equal(getClass({ Title: 'native-title' }), 'native-title gca-compact-title');
  assert.doesNotMatch(source, /staticClasses\.Title/);
});
