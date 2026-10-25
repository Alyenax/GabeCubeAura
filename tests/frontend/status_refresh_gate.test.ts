import assert from 'node:assert/strict';
import test from 'node:test';
import {statusRefreshGate} from '../../src/status_refresh_gate';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

test('poll before, during or straddling a selection cannot restore Custom/Dashboard',()=>{
  const gate=statusRefreshGate(), before=gate.ticket();
  gate.writing(true);
  const during=gate.ticket();
  assert.equal(gate.accepts(before),false);
  assert.equal(gate.accepts(during),false);
  gate.invalidate(); // Apply the RPC's confirmed settings.
  gate.writing(false);
  assert.equal(gate.accepts(before),false);
  assert.equal(gate.accepts(during),false);
  assert.equal(gate.accepts(gate.ticket()),true);
});

test('slider flush and selection have independent nested write lifetimes',()=>{
  const gate=statusRefreshGate();
  gate.writing(true);gate.writing(true);
  gate.writing(false);
  assert.equal(gate.accepts(gate.ticket()),false);
  const ticket=gate.ticket();gate.writing(false);
  assert.equal(gate.accepts(ticket),false);
  assert.equal(gate.accepts(gate.ticket()),true);
});

test('failure unlocks future reads; another confirmed change invalidates in-flight reads',()=>{
  const gate=statusRefreshGate();
  gate.writing(true);gate.writing(false);
  assert.equal(gate.accepts(gate.ticket()),true);
  const old=gate.ticket();gate.invalidate();
  assert.equal(gate.accepts(old),false);
});

test('the shipped Content poll ignores a late snapshot after the confirmed selection',async()=>{
  const source=readFileSync(new URL('../../src/index.tsx',import.meta.url),'utf8');
  const ast=ts.createSourceFile('index.tsx',source,99,true,4);
  const content=ast.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text==='Content') as ts.FunctionDeclaration;
  const setter=content.body!.statements.find(n=>ts.isVariableStatement(n)&&n.declarationList.declarations.some(d=>d.name.getText()==='setStatus'))!;
  const poll=content.body!.statements.find(n=>ts.isExpressionStatement(n)&&n.getText().startsWith('useEffect(')&&n.getText().includes('statusReads.current.ticket()'))!;
  const gate=statusRefreshGate(),applied:any[]=[],pending:((value:any)=>void)[]=[],scheduled:(()=>void)[]=[],connections:boolean[]=[];
  let cleanup:(()=>void)|undefined;
  const context=vm.createContext({statusReads:{current:gate},retainedStatus:null,active:true,page:'quick',
    setUILanguage(){},publishQuickSetupStatus(){},setStatusState:(s:any)=>applied.push(s),console,
    onFaceplateConnectionChange:(connected:boolean)=>connections.push(connected),
    statusRefreshDelay:()=>2000,getStatus:()=>new Promise(resolve=>pending.push(resolve)),
    useEffect:(fn:()=>()=>void)=>{cleanup=fn();},manualTimer:{current:null},artworkVibranceTimer:{current:null},
    window:{setTimeout:(fn:()=>void)=>scheduled.push(fn),clearTimeout(){}},
  });
  const code=ts.transpileModule(setter.getText(ast)+'\n'+poll.getText(ast)+'\nthis.apply=setStatus;',
    {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
  vm.runInContext(code,context);
  gate.writing(true);
  context.apply({display_preset:'atmosphere',ui_language:'en',faceplate:{available:false}});
  gate.writing(false);
  pending[0]({display_preset:'custom',ui_language:'en',faceplate:{available:true}});
  for(let i=0;i<6;i++)await Promise.resolve();
  assert.equal(applied.length,1);
  assert.equal(applied[0].display_preset,'atmosphere');
  scheduled.shift()!();
  pending[1]({display_preset:'atmosphere',ui_language:'en',faceplate:{available:true}});
  for(let i=0;i<6;i++)await Promise.resolve();
  assert.equal(applied.length,2,'Fresh status continues to update LEDs/timer normally');
  assert.deepEqual(connections,[false,true],'stale snapshots cannot resurrect a disconnected Faceplate');
  cleanup!();
});
