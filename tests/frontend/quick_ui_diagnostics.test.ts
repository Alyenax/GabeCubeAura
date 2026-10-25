import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import vm from 'node:vm';
const source=readFileSync(new URL('../../src/quick_panel_ui.ts',import.meta.url),'utf8').replace(/^import .*;\n/,'');
const code=ts.transpileModule(source.replace('export function','function')+'\nthis.report=reportQuickUI;',
  {compilerOptions:{target:ts.ScriptTarget.ES2020}}).outputText;
test('quick UI journal uses a closed vocabulary and excludes raw messages/secrets',()=>{
  const calls:any[]=[],context=vm.createContext({reportRuntimeDiagnostic:(...args:any[])=>{calls.push(args);return Promise.resolve();}});
  vm.runInContext(code,context);
  context.report('ambience','opening');context.report('ambience','selected','atmosphere');
  context.report('faceplate','failed','secret-token-or-system-path');
  context.report('unknown-user-value','selected','dashboard');
  assert.deepEqual(calls.map(c=>c[2]),['ambience:opening','ambience:selected:atmosphere','faceplate:failed']);
  assert(calls.every(c=>c[0]==='quick_panel_ui'&&c[1]===0&&c[3]===0));
});
test('both synchronous and asynchronous diagnostic failures cannot break a UI action',async()=>{
  for(const reportRuntimeDiagnostic of [()=>{throw Error('offline');},()=>Promise.reject(Error('offline'))]){
    const context=vm.createContext({reportRuntimeDiagnostic});vm.runInContext(code,context);
    assert.doesNotThrow(()=>context.report('timer','opened'));await Promise.resolve();
  }
});
