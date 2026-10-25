import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import {LedPreviewStream} from '../../src/led_preview';
import type {RGB} from '../../src/types';

test('the shipped preview hook paints new colours without a status refresh and stops with its native scope', async () => {
  const timers = new Map<number, () => void>(); let id = 0, calls = 0;
  const documentListeners = new Set<() => void>();
  const document = {visibilityState: 'visible', addEventListener: (_: string, fn: () => void) => documentListeners.add(fn), removeEventListener: (_: string, fn: () => void) => documentListeners.delete(fn)};
  let cursor = 0, active = true; const states: any[] = [], deps: any[] = [], cleanups: any[] = [];
  const context = vm.createContext({exports: {}, document, require(name: string) {
    if (name === 'react') return {
      createContext: () => ({}), useContext: () => active,
      useState(initial: unknown) {const index = cursor++; if (!(index in states)) states[index] = initial; return [states[index], (value: unknown) => {states[index] = value;}];},
      useEffect(effect: () => any, next: any[]) {const index = cursor++; if (!deps[index] || next.some((value, i) => value !== deps[index][i])) {cleanups[index]?.(); deps[index] = next; cleanups[index] = effect();}},
    };
    if (name === '../api') return {getLedPreview: async () => {calls++; return {weather: Array.from({length: 17}, () => [0, 250, 176])};}};
    if (name === '../led_preview') return {LedPreviewStream: class extends LedPreviewStream {
      constructor(read: any) {super(read, ((task: () => void) => {timers.set(++id, task); return id;}) as any, ((id: number) => timers.delete(id)) as any);}
    }};
    throw Error(name);
  }});
  const code = readFileSync(new URL('../../src/components/LiveLedPreview.tsx', import.meta.url), 'utf8');
  vm.runInContext(ts.transpileModule(code, {compilerOptions: {module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022}}).outputText, context);
  const fallback: RGB[] = Array.from({length: 17}, () => [0, 45, 74]);
  const render = () => {cursor = 0; return context.exports.useLiveLedColors('weather', fallback);};
  assert.equal(render(), fallback); assert.equal(documentListeners.size, 1);
  const task = timers.entries().next().value!; timers.delete(task[0]); task[1]();
  for (let n = 0; n < 8; n++) await Promise.resolve();
  assert.equal(calls, 1); assert.equal(render()[0][1], 250);
  active = false; assert.equal(render(), fallback);
  assert.equal(timers.size, 0); assert.equal(documentListeners.size, 0);
  active = true; render(); assert.equal(timers.size, 1);
  document.visibilityState = 'hidden'; for (const fn of documentListeners) fn();
  assert.equal(timers.size, 0); assert.equal(render(), fallback);
  for (const cleanup of cleanups) cleanup?.();
  assert.equal(documentListeners.size, 0);
});
