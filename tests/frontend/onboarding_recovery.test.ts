import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';
import {createElement} from 'react';
import {FACEPLATE_HOME_OPTIONS,FACEPLATE_GAME_OPTIONS,homeFaceChoice,isDashboardChoice,quickFaceOptions} from '../../src/faceplate_choices';
import {recoverSetupDraft,setupReadGate,setupRecoveryMessage} from '../../src/onboardingRecovery';
import {setupSteps,setupNeeds} from '../../src/setupFlow';
import type {SetupSnapshot} from '../../src/onboardingApi';

const ready:SetupSnapshot={draft:{},bar_detected:false,faceplate_detected:false,faceplate_busy:false};
const broken={...ready,draft_error:'unavailable',draft_error_code:'draft_schema'};
const deferred=<T,>()=>{let resolve!:(value:T)=>void;const promise=new Promise<T>(r=>resolve=r);return {promise,resolve};};

test('recovery invalidates old polling and rejects a second simultaneous click',async()=>{
  const gate=setupReadGate(),old=gate.read(),pending=deferred<SetupSnapshot>();
  const calls:string[]=[];
  const deps={gate,reset:()=>{calls.push('request');return pending.promise;},alive:()=>true,
    snapshot:()=>calls.push('snapshot'),recovered:()=>calls.push('recovered'),failed:()=>calls.push('failed')};
  const first=recoverSetupDraft(deps);
  assert.equal(gate.read(),null);assert.equal(gate.accepts(old),false);
  await recoverSetupDraft(deps);assert.deepEqual(calls,['request']);
  pending.resolve(ready);await first;
  assert.deepEqual(calls,['request','snapshot','recovered']);
  assert.equal(gate.accepts(old),false);assert.equal(gate.accepts(gate.read()),true);
});

test('server rejection keeps recovery failed; no false success or default application',async()=>{
  const calls:string[]=[];
  await recoverSetupDraft({gate:setupReadGate(),alive:()=>true,
    reset:async()=>({...broken,draft_reset_error:'draft_permissions'}),
    snapshot:()=>calls.push('snapshot'),failed:code=>calls.push(code),recovered:()=>calls.push('success')});
  assert.deepEqual(calls,['snapshot','draft_permissions']);
});

test('transport failure and invalid payload have visible safe errors',async()=>{
  for(const reset of [async()=>{throw new Error('private/path');},async()=>null as unknown as SetupSnapshot]){
    const calls:string[]=[];
    await recoverSetupDraft({gate:setupReadGate(),alive:()=>true,reset,
      snapshot:()=>calls.push('snapshot'),failed:code=>calls.push(code),recovered:()=>calls.push('success')});
    assert.deepEqual(calls,['draft_transport']);
  }
});

test('timeout releases the button; a late reply cannot repaint the guide',async()=>{
  const pending=deferred<SetupSnapshot>(),gate=setupReadGate(),calls:string[]=[];
  await recoverSetupDraft({gate,alive:()=>true,reset:()=>pending.promise,timeoutMs:1,
    snapshot:()=>calls.push('snapshot'),failed:code=>calls.push(code),recovered:()=>calls.push('success')});
  assert.deepEqual(calls,['draft_transport']);assert.notEqual(gate.read(),null);
  pending.resolve(ready);await Promise.resolve();assert.deepEqual(calls,['draft_transport']);
});

test('unmounted guide ignores recovery replies and read generations are invalidated',async()=>{
  const pending=deferred<SetupSnapshot>(),gate=setupReadGate();let alive=true;
  const action=recoverSetupDraft({gate,alive:()=>alive,reset:()=>pending.promise,
    snapshot:()=>assert.fail('unmounted'),failed:()=>assert.fail('unmounted'),recovered:()=>assert.fail('unmounted')});
  alive=false;gate.invalidate();pending.resolve(ready);await action;
  const old=gate.read();gate.invalidate();assert.equal(gate.accepts(old),false);
});

test('a stuck pending save times out without sending a late archive command',async()=>{
  const pending=deferred<void>(),calls:string[]=[];
  await recoverSetupDraft({gate:setupReadGate(),alive:()=>true,pending:()=>pending.promise,timeoutMs:1,
    reset:async()=>{calls.push('archive');return ready;},
    snapshot:()=>calls.push('snapshot'),failed:code=>calls.push(code),recovered:()=>calls.push('success')});
  pending.resolve();await Promise.resolve();await Promise.resolve();
  assert.deepEqual(calls,['draft_transport']);
});

test('every recovery category has a human FR/EN explanation without raw exceptions',()=>{
  for(const code of ['draft_permissions','draft_unsafe','draft_archive_full','draft_schema',
    'draft_too_large','draft_invalid','draft_io','draft_transport','unknown/private/path']){
    assert.ok(setupRecoveryMessage(code,true).length>30);
    assert.ok(setupRecoveryMessage(code,false).length>30);
    assert.notEqual(setupRecoveryMessage(code,true),setupRecoveryMessage(code,false));
    assert.doesNotMatch(setupRecoveryMessage(code,true),/unknown\/private\/path/);
  }
});

// Run the actual component's native button callback, not an HTML recreation.
function mount(reset:()=>Promise<SetupSnapshot>,initialSnapshot:SetupSnapshot=broken,language='en',initialStatus:Record<string,unknown>={}){
  const source=readFileSync(new URL('../../src/components/FirstRunOnboarding.tsx',import.meta.url),'utf8');
  const ast=ts.createSourceFile('guide.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  const body=ast.statements.filter(node=>!ts.isImportDeclaration(node)).map(node=>node.getText(ast)).join('\n');
  const hooks:any[]=[],navigations:string[]=[],saved:any[]=[];let cursor=0;
  const context=vm.createContext({FACEPLATE_HOME_OPTIONS,FACEPLATE_GAME_OPTIONS,homeFaceChoice,isDashboardChoice,quickFaceOptions,exports:{},React:{createElement},
    useState:(initial:any)=>{const i=cursor++;if(!(i in hooks))hooks[i]=i===0?initialSnapshot:i===1?{...(typeof initial==='function'?initial():initial),...initialSnapshot.draft}:typeof initial==='function'?initial():initial;
      return [hooks[i],(next:any)=>{hooks[i]=typeof next==='function'?next(hooks[i]):next;}];},
    useRef:(initial:any)=>{const i=cursor++;return hooks[i]??(hooks[i]={current:initial});},useEffect:()=>{},
    DialogBody:'body-native',DialogHeader:'header-native',gamepadDialogClasses:{},DialogButton:'button',Focusable:'focusable',ScrollPanel:'scroll',PanelSection:'section',PanelSectionRow:'row',
    DropdownItem:'select',SliderField:'slider',TextField:'input',ToggleField:'toggle',
    setupSteps,setupNeeds,recoverSetupDraft,setupReadGate,setupRecoveryMessage,
    resetOnboardingDraft:reset,QUICK_CONTROL_CSS:'',
    saveOnboardingDraft:async(value:any)=>{saved.push(value);return value;},
    Navigation:{CloseSideMenus(){},Navigate:(route:string)=>navigations.push(route)},
    window:{clearTimeout,setTimeout,clearInterval},
  });
  vm.runInContext(ts.transpileModule(body,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React}}).outputText,context);
  let closed=0;
  const render=()=>{cursor=0;return context.exports.FirstRunOnboarding({status:{ui_language:language,light_bar_day_brightness:9,
    night_mode_enabled:false,night_mode_brightness:35,weather_location:null,
    faceplate:{routing:{routes:{home:'dashboard'}},steamgriddb:{}},...initialStatus},setStatus:()=>assert.fail('active settings changed'),
    onClose:()=>closed++,openBrowser:()=>{}});};
  const walk=(node:any):any[]=>Array.isArray(node)?node.flatMap(walk):!node||typeof node!=='object'?[]:
    [node,...walk(node.props?.children)];
  const text=(node:any):string=>Array.isArray(node)?node.map(text).join(' '):node&&typeof node==='object'?text(node.props?.children):String(node??'');
  return {render,walk,text,navigations,saved,closed:()=>closed};
}

test('calibrated fresh setup retains the supplied brightness and cannot skip to confirmation',()=>{
  const mounted=mount(async()=>ready,{...ready,bar_detected:true,draft:{step:'ambiance'}},'en',{
    onboarding_completed:false,display_preset:'custom',light_bar_day_brightness:15,
    faceplate:{routing:{routes:{home:'artwork-dashboard',game:'artwork-dashboard'}},steamgriddb:{}},
  });
  let tree=mounted.render();assert.match(mounted.text(tree),/Keep initial settings/);
  assert.doesNotMatch(mounted.text(tree),/Set up later|Confirm and finish/);
  const next=mounted.walk(tree).find(node=>node.type==='button'&&mounted.text(node)==='Continue');
  assert.ok(next);next.props.onClick();tree=mounted.render();
  assert.equal(mounted.walk(tree).find(node=>node.type==='slider'&&node.props.max===255)?.props.value,15);
  assert.doesNotMatch(mounted.text(tree),/Confirm and finish/);
  assert.equal(mounted.closed(),0);
});

test('actual guide button displays archive failure at the top and can close without changes',async()=>{
  const mounted=mount(async()=>({...broken,draft_reset_error:'draft_permissions'}));
  let tree=mounted.render();
  const button=mounted.walk(tree).find(node=>node.type==='button'&&mounted.text(node).includes('Archive draft'));
  assert.ok(button);button.props.onClick();
  const progress=mounted.walk(mounted.render()).find(node=>node.type==='button'&&mounted.text(node).includes('Recovering…'));
  assert.ok(progress);assert.equal(progress.props.disabled,true);
  await new Promise(resolve=>setImmediate(resolve));
  tree=mounted.render();
  const alert=mounted.walk(tree).find(node=>node.props?.role==='alert');
  assert.match(mounted.text(alert),/access denied or read-only/);
  const close=mounted.walk(tree).find(node=>node.type==='button'&&mounted.text(node).includes('Close setup'));
  assert.equal(close.props.disabled,false);close.props.onClick();assert.equal(mounted.closed(),1);
});

test('actual guide leaves the error view only after confirmed recovery',async()=>{
  const mounted=mount(async()=>ready);
  const button=mounted.walk(mounted.render()).find(node=>node.type==='button'&&mounted.text(node).includes('Archive draft'));
  button.props.onClick();await new Promise(resolve=>setImmediate(resolve));
  const tree=mounted.render(),text=mounted.text(tree);
  assert.doesNotMatch(text,/The draft could not be read/);
  assert.match(text,/Setup can continue/);
  assert.match(text,/Your active settings are unchanged/);
});


test('GCA review contains no vocal settings or separate assistant links in FR and EN',()=>{
  for(const language of ['en','fr']){
    const mounted=mount(async()=>ready,{...ready,draft:{step:'review',assistant_requested:true,assistant_confirmed:true}},language);
    const tree=mounted.render(),text=mounted.text(tree);
    assert.doesNotMatch(text,/Prepare voice|Préparer la voix|Voice setup|assistant|vocal|voix|DVA/i);
    assert.ok(mounted.walk(tree).some(node=>node.type==='button'&&/Confirm and finish|Confirmer et terminer/.test(mounted.text(node))));
    assert.equal(mounted.saved.length,0);assert.equal(mounted.navigations.length,0);
  }
});

test('memory-only draft opens the actual guide and offers confirmation in FR and EN',()=>{
  for(const language of ['en','fr']){
    const mounted=mount(async()=>ready,{...ready,draft_storage:'memory',draft:{step:'review'}},language);
    const tree=mounted.render(),text=mounted.text(tree);
    assert.doesNotMatch(text,/The draft could not be read|Archive draft|propriétaire|unexpected owner/);
    assert.match(text,/Progress is kept for this session|progression est gardée pour cette session/);
    assert.ok(mounted.walk(tree).some(node=>node.type==='button'&&!node.props.disabled&&/Confirm and finish|Confirmer et terminer/.test(mounted.text(node))));
    assert.equal(mounted.saved.length,0);
  }
});

test('actual quick panel places incomplete setup before update notice and compact controls',()=>{
  const source=readFileSync(new URL('../../src/index.tsx',import.meta.url),'utf8');
  const ast=ts.createSourceFile('index.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  let branch:ts.ConditionalExpression|undefined;
  const visit=(node:ts.Node)=>{if(ts.isConditionalExpression(node)&&node.condition.getText(ast)==='page === "quick"')branch=node;ts.forEachChild(node,visit);};
  visit(ast);assert.ok(branch);
  const navigations:string[]=[],context=vm.createContext({React:{createElement,Fragment:Symbol.for('react.fragment')},exports:{},
    PanelSection:'section',PanelSectionRow:'row',Localized:'localized',QuickAction:'button',FaceplateSetupNotice:'faceplate-setup',UpdateAvailableButton:'update',CompactQuickPanel:'compact',quickSetupCompleted:()=>false,
    Navigation:{CloseSideMenus:()=>navigations.push('close'),Navigate:(route:string)=>navigations.push(route)},
    update:null,active:true,setStatus:()=>{},shownColors:[],statusReads:{current:{writing:()=>{}}},LIGHT_BAR_ARTWORK_ROUTE:'/artwork'});
  vm.runInContext(ts.transpileModule(`export function render(status:any){return ${branch.whenTrue.getText(ast)}}`,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React}}).outputText,context);
  const children=context.exports.render({onboarding_completed:false}).props.children.filter(Boolean);
  assert.equal(children[0].type,'section');assert.equal(children[1].type,'faceplate-setup');assert.equal(children[2].type,'update');assert.equal(children[3].type,'compact');
  assert.equal(children[2].props.disabled,true);
  const button=children[0].props.children[0].props.children;
  assert.equal(button.type,'button');assert.equal(button.props.children,'Open guided setup');
  button.props.onClick();assert.deepEqual(navigations,['close','/gabecubeaura/setup']);
  children[2].props.onOpen();assert.equal(navigations.length,2,'Update route is locked too');
  assert.equal(context.exports.render({onboarding_completed:true}).props.children.filter(Boolean)[1].props.disabled,false);
  assert.deepEqual(context.exports.render({onboarding_completed:true}).props.children.filter(Boolean).map((child:any)=>child.type),['faceplate-setup','update','compact']);
});
