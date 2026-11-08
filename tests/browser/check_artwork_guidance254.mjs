import {createRequire} from 'node:module';
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import assert from 'node:assert/strict';
const root=process.cwd(),req=createRequire(path.join(root,'package.json'));
const require=createRequire('/Users/C/Documents/Chrome/Xplorarr Project - NEXT/gabecubeaura-interface-preview/interface-preview/package.json');
const {build}=require('esbuild'),{chromium}=require('playwright');
const ts=req('typescript'),source=ts.createSourceFile('index.tsx',readFileSync(path.join(root,'src/index.tsx'),'utf8'),99,true,4);let callback;
function visit(node){if(ts.isJsxAttribute(node)&&node.name.getText(source)==='onOpenArtwork')callback=node.initializer.expression.getText(source);ts.forEachChild(node,visit);}visit(source);assert(callback);
const app=`import React,{useState} from 'react';import {createRoot} from 'react-dom/client';import {flushSync} from 'react-dom';import {CompactQuickPanel} from '${root}/src/components/CompactQuickPanel';import {setUILanguage} from '${root}/src/i18n';import {LedPreviewActivity} from '${root}/src/components/LiveLedPreview';
const Navigation={CloseSideMenus:()=>window.navigation.push('close'),Navigate:url=>window.navigation.push(url)};
const openArtwork=${callback};
function App(){const[s,set]=useState(window.state),[active,setActive]=useState(true),[mounted,setMounted]=useState(true);window.refresh=next=>flushSync(()=>{setUILanguage(next.ui_language);set(next)});window.setPanelActive=value=>flushSync(()=>setActive(value));window.setPanelMounted=value=>flushSync(()=>setMounted(value));return mounted?<LedPreviewActivity.Provider value={false}><CompactQuickPanel active={active} status={s} setStatus={set} colors={[]} onOpenGame={()=>{}} onOpenSettings={()=>{}} onOpenArtwork={openArtwork}/></LedPreviewActivity.Provider>:null;}setUILanguage(window.state.ui_language);flushSync(()=>createRoot(document.getElementById('app')).render(<App/>));`;
const bundle=(await build({stdin:{contents:app,resolveDir:root,loader:'tsx'},bundle:true,write:false,jsx:'automatic',define:{'process.env.NODE_ENV':'"production"'},plugins:[{name:'fixture',setup(b){
 b.onResolve({filter:/^react(?:\/.*)?$|^react-dom(?:\/.*)?$/},a=>({path:require.resolve(a.path)}));
 b.onResolve({filter:/^@decky\/ui$/},()=>({path:path.join(root,'tests/browser/settings_ui_shim.tsx')}));
 b.onResolve({filter:/^@decky\/api$/},()=>({path:'rpc',namespace:'qa'}));
 b.onLoad({filter:/.*/,namespace:'qa'},()=>({contents:`export const callable=name=>(...args)=>window.rpc(name,args);`,loader:'ts'}));
}}]})).outputFiles[0].text;
const initial={ui_language:'en',onboarding_completed:true,faceplate_setup_completed:true,game:{appid:0,title:'Home'},
 available:true,active:true,signalbar_enabled:true,current_display:'weather',display_preset:'custom',light_bar_day_brightness:15,faceplate_brightness:70,
 thermal_protection:{active:false},debug:{engine_running:true},timer_end_action:{phase:'idle'},countdown:{active:false,source:'free'},personal_timer:{active:false},free_timer_minutes:30,
 faceplate_lab_enabled:true,faceplate_dashboard_home_source:'artwork',faceplate_dashboard_home_appid:0,
 faceplate:{available:true,powered:true,busy:false,phase:'ready',delivery:{state:'confirmed'},automation:{busy:false,queued:false,last_error:''},power_recovery:{suspended:false},
 routing:{routes:{home:'dashboard',game:'artwork'},desired_scene:'dashboard',effective_scene:'dashboard',desired_content_key:'previous',effective_content_key:'previous',preparation:{state:'ready',error:''}}}};
const server=http.createServer((request,res)=>{if(request.url==='/app.js'){res.setHeader('Content-Type','text/javascript');res.end(bundle);return;}
res.setHeader('Content-Type','text/html');res.end(`<!doctype html><meta charset="utf-8"><style>body{margin:0;background:#0e141b;color:#dcdedf;font:16px Arial;padding:12px}*{box-sizing:border-box}button,select{max-width:100%;padding:9px}section{margin-bottom:14px}</style><div id="app"></div><script>window.state=${JSON.stringify(initial)};window.calls=[];window.navigation=[];window.rpc=async(name,args)=>{window.calls.push(name);return name==='get_quick_artwork'?{appid:args[0],found:false,data_uri:''}:{}};</script><script src="/app.js"></script>`);});
await new Promise(r=>server.listen(0,'127.0.0.1',r));const out=process.env.GCA_ARTWORK_QA_OUTPUT||path.join(root,'out/artwork-delay255');mkdirSync(out,{recursive:true});
let browser;const records=[],errors=[];
try{
 browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const page=await browser.newPage({viewport:{width:340,height:1050}});page.on('pageerror',e=>errors.push(e.message));
 await page.clock.install({time:new Date('2026-10-25T12:00:00Z')});await page.clock.pauseAt(new Date('2026-10-25T12:00:01Z'));
 await page.goto(`http://127.0.0.1:${server.address().port}`);await page.locator('#gca-compact-root').waitFor();
 const notice=page.locator('[data-artwork-guidance]');
 const hidden=async()=>assert.equal(await notice.count(),0);
 const shown=async()=>{await notice.waitFor();assert.equal(await notice.count(),1);};
 const tick=ms=>page.clock.runFor(ms);
 const refresh=s=>page.evaluate(s=>window.refresh(s),s);
 const activate=value=>page.evaluate(v=>window.setPanelActive(v),value);
 const start=async s=>{await activate(false);await refresh(s);await activate(true);await hidden();};
 const pending=(game=false,choice='artwork')=>{
  const s=structuredClone(initial);s.game={appid:game?42:0,title:game?'Current game':'Home'};
  s.faceplate.routing.routes[game?'game':'home']=choice;s.faceplate.routing.desired_scene=choice;s.faceplate.routing.preparation.state='pending';return s;
 };
 await hidden();assert.equal(await page.getByText('Transfer confirmed by Faceplate.',{exact:true}).count(),0,'A weather fallback receipt must not imply prepared Home artwork during the delay');
 for(const language of ['fr','en'])for(const game of [false,true])for(const choice of ['artwork','artwork-dashboard']){
  const s=pending(game,choice);s.ui_language=language;
  await page.evaluate(()=>{window.navigation=[]});await start(s);
  await tick(2500);await hidden();await refresh(structuredClone(s));
  const callsBefore=await page.evaluate(()=>window.calls.filter(n=>n!=='report_runtime_diagnostic').length);
  await tick(2499);await hidden();await tick(1);await shown();
  assert.equal(await page.evaluate(()=>window.calls.filter(n=>n!=='report_runtime_diagnostic').length),callsBefore,'The UI delay must not poll or transfer');
  assert.equal(await notice.locator('small').evaluate(e=>getComputedStyle(e).color),'rgb(255, 210, 122)');
  assert.match(await notice.textContent(),language==='fr'?/conserve son image actuelle/:/keeps its current image/);
  const button=notice.getByRole('button',{name:language==='fr'?'Créer un artwork':'Create artwork',exact:true});
  await button.focus();await page.keyboard.press('Enter');
  assert.deepEqual(await page.evaluate(()=>window.navigation),['close','/gabecubeaura/settings/pixel-artwork']);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false);
  await page.screenshot({path:path.join(out,`${language}-${game?'game':'home'}-${choice}.png`),fullPage:true});
  s.faceplate_dashboard_home_appid=42;s.faceplate.home_artwork_prepared=true;s.faceplate.routing.effective_scene=choice;s.faceplate.routing.preparation.state='ready';
  await refresh(s);await hidden();await tick(6000);await hidden();
  records.push({language,context:game?'game':'home',choice,hidden_until_4999ms:true,visible_at_5000ms:true,status_refresh_preserves_deadline:true,yellow:true,production_navigation_callback:true,ready_hides_notice:true});
 }
 const timing=[];
 // A ready artwork cancels a still-pending warning, with no delayed flash.
 const early=pending();await start(early);await tick(3000);
 early.faceplate.home_artwork_prepared=true;early.faceplate.routing.effective_scene='artwork';early.faceplate.routing.preparation.state='ready';
 await refresh(early);await tick(6000);await hidden();timing.push('ready_before_deadline_cancels');
 for(const [name,mutate] of [
  ['Off',s=>{s.faceplate.powered=false;}],
  ['disconnect',s=>{s.faceplate.available=false;}],
  ['mandatory_setup',s=>{s.onboarding_completed=false;}],
  ['weather',s=>{s.faceplate_dashboard_home_source='weather';s.faceplate.routing.routes.home='weather';}],
 ]){
  const s=pending();await start(s);await tick(3000);const cancelled=structuredClone(s);mutate(cancelled);await refresh(cancelled);
  await tick(6000);await hidden();await refresh(s);await tick(4999);await hidden();await tick(1);await shown();timing.push(name+'_cancels_and_reentry_waits_five_seconds');
 }
 // A different Artwork mode/game cannot inherit a previous context's timer.
 for(const [name,initialState,next] of [
  ['mode',pending(),s=>{s.faceplate.routing.routes.home='artwork-dashboard';s.faceplate.routing.desired_scene='artwork-dashboard';}],
  ['game',pending(true),s=>{s.game.appid=99;}],
  ['home_to_game',pending(),s=>{s.game.appid=42;}],
 ]){
  await start(initialState);await tick(3000);const s=structuredClone(initialState);next(s);await refresh(s);
  await tick(2000);await hidden();await tick(2999);await hidden();await tick(1);await shown();timing.push(name+'_restarts_deadline');
 }
 for(const toggle of ['setPanelActive','setPanelMounted']){
  const s=pending();await start(s);await tick(3000);await page.evaluate(t=>window[t](false),toggle);await tick(6000);await hidden();
  await page.evaluate(t=>window[t](true),toggle);await tick(4999);await hidden();await tick(1);await shown();
  // Closing an already visible hint also clears it immediately and starts anew.
  await page.evaluate(t=>window[t](false),toggle);await hidden();await page.evaluate(t=>window[t](true),toggle);await hidden();
  await tick(4999);await hidden();await tick(1);await shown();timing.push(toggle+'_cancels_pending_and_visible_hint');
 }
 for(const choice of ['weather','dashboard','native-clock']){const s=structuredClone(initial);s.faceplate_dashboard_home_source='weather';s.faceplate.routing.routes.home=choice;await refresh(s);await tick(6000);await hidden();}
 const writes=(await page.evaluate(()=>window.calls)).filter(n=>!['report_runtime_diagnostic','get_quick_artwork'].includes(n));assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);
 writeFileSync(path.join(out,'VALIDATION.json'),JSON.stringify({records,timing,errors,delay_ms:5000,no_timer_rpc_reads_or_hardware_writes:true,physicalSteamOSNavigation:false},null,2));
 console.log(JSON.stringify({scenarios:records.length,timing_checks:timing.length,errors,no_timer_rpc_reads_or_hardware_writes:true}));
}finally{await browser?.close();await new Promise(r=>server.close(r));}
