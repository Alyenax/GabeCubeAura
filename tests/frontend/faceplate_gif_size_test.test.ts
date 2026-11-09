import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import {createElement, Fragment} from 'react';
import ts from 'typescript';

test('the collapsed size test sends only after the user confirms a selected size', async () => {
  const calls: number[] = [];
  const slots: unknown[] = [];
  let cursor = 0;
  let complete!: (value: unknown) => void;
  const source = readFileSync(new URL('../../src/components/FaceplateGifSizeTest.tsx', import.meta.url), 'utf8')
    .replace(/^import .*;\n/gm, '');
  const context = vm.createContext({
    exports: {}, React: {createElement, Fragment}, ButtonItem: 'button',
    DropdownItem: 'dropdown', Localized: 'text', PanelSectionRow: 'row',
    callable: (name: string) => {
      assert.equal(name, 'run_faceplate_gif_size_test');
      return (size: number) => { calls.push(size); return new Promise(resolve => { complete = resolve; }); };
    },
    useState: (initial: unknown) => {
      const i = cursor++;
      if (!(i in slots)) slots[i] = initial;
      return [slots[i], (value: unknown) => { slots[i] = value; }];
    },
    useRef: (initial: unknown) => slots[cursor++] ??= {current: initial},
  });
  vm.runInContext(ts.transpileModule(source, {compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React,
  }}).outputText, context);
  function nodes(value: any): any[] {
    return Array.isArray(value) ? value.flatMap(nodes) :
      value && typeof value === 'object' ? [value, ...nodes(value.props?.children)] : [];
  }
  const render = () => { cursor = 0; return nodes(context.exports.FaceplateGifSizeTest()); };
  const button = (label: string) => render().find(node => node.type === 'button' && node.props.label === label);

  assert.equal(button('Send one test GIF'), undefined);
  button('Faceplate GIF transfer test').props.onClick();
  const dropdown = () => render().find(node => node.type === 'dropdown');
  const choices = Array.from(dropdown().props.rgOptions, (option: {data: number}) => option.data);
  assert.deepEqual(choices, [1, 4, 32768, 32769, 32, 56, 64, 80]);
  dropdown().props.onChange({data: 32768});
  assert.deepEqual(calls, []);
  const send = button('Send one test GIF');
  send.props.onClick();
  send.props.onClick();
  assert.deepEqual(calls, [32768]);
  assert.equal(button('Send one test GIF').props.disabled, true);
  complete({state: 'confirmed', size_bytes: 32768});
  await new Promise(resolve => setImmediate(resolve));
  dropdown().props.onChange({data: 32769});
  assert.deepEqual(calls, [32768]);
  button('Send one test GIF').props.onClick();
  assert.deepEqual(calls, [32768, 32769]);
  complete({state: 'begin-refused', size_bytes: 32769});
  await new Promise(resolve => setImmediate(resolve));
  assert(render().some(node => node.type === 'text' && node.props.children.includes('before any image data')));
  assert.equal(button('Send one test GIF').props.disabled, false);
});
