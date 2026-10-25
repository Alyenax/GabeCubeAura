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
const app=`import React,{useState} from 'react';import {createRoot} from 'react-dom/client';import {CompactQuickPanel} from '${root}/src/components/CompactQuickPanel';import {setUILanguage} from '${root}/src/i18n';
const Navigation={CloseSideMenus:()=>window.navigation.push('close'),Navigate:url=>window.navigation.push(url)};
const openArtwork=${callback};
function App(){const[s,set]=useState(window.state);window.refresh=next=>{setUILanguage(next.ui_language);set(next)};return <CompactQuickPanel active={false} status={s} setStatus={set} colors={[]} onOpenGame={()=>{}} onOpenSettings={()=>{}} onOpenArtwork={openArtwork}/>;}setUILanguage(window.state.ui_language);createRoot(document.getElementById('app')).render(<App/>);`;
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
res.setHeader('Content-Type','text/html');res.end(`<!doctype html><meta charset="utf-8"><style>body{margin:0;background:#0e141b;color:#dcdedf;font:16px Arial;padding:12px}*{box-sizing:border-box}button,select{max-width:100%;padding:9px}section{margin-bottom:14px}</style><div id="app"></div><script>window.state=${JSON.stringify(initial)};window.calls=[];window.navigation=[];window.rpc=async(name,args)=>{window.calls.push(name);return {}};</script><script src="/app.js"></script>`);});
await new Promise(r=>server.listen(0,'127.0.0.1',r));const out=process.env.GCA_ARTWORK_QA_OUTPUT||path.join(root,'out/artwork-guidance254');mkdirSync(out,{recursive:true});
let browser;const records=[],errors=[];
try{
 browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const page=await browser.newPage({viewport:{width:340,height:1050}});page.on('pageerror',e=>errors.push(e.message));
 await page.goto(`http://127.0.0.1:${server.address().port}`);await page.locator('#gca-compact-root').waitFor();assert.equal(await page.getByText('Transfer confirmed by Faceplate.',{exact:true}).count(),0,'A weather fallback receipt must not imply prepared Home artwork');
 for(const language of ['fr','en'])for(const game of [false,true])for(const choice of ['artwork','artwork-dashboard']){
  const s=structuredClone(initial);s.ui_language=language;s.game={appid:game?42:0,title:game?'Current game':'Home'};
  s.faceplate.routing.routes[game?'game':'home']=choice;s.faceplate.routing.desired_scene=choice;s.faceplate.routing.preparation.state='pending';
  await page.evaluate(s=>{window.navigation=[];window.refresh(s)},s);
  const notice=page.locator('[data-artwork-guidance]');await notice.waitFor();
  assert.equal(await notice.locator('small').evaluate(e=>getComputedStyle(e).color),'rgb(255, 210, 122)');
  assert.match(await notice.textContent(),language==='fr'?/conserve son image actuelle/:/keeps its current image/);
  const button=notice.getByRole('button',{name:language==='fr'?'Créer un artwork':'Create artwork',exact:true});
  await button.focus();await page.keyboard.press('Enter');
  assert.deepEqual(await page.evaluate(()=>window.navigation),['close','/gabecubeaura/settings/pixel-artwork']);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false);
  await page.screenshot({path:path.join(out,`${language}-${game?'game':'home'}-${choice}.png`),fullPage:true});
  s.faceplate_dashboard_home_appid=42;s.faceplate.home_artwork_prepared=true;s.faceplate.routing.effective_scene=choice;s.faceplate.routing.preparation.state='ready';
  await page.evaluate(s=>window.refresh(s),s);await notice.waitFor({state:'detached'});
  records.push({language,context:game?'game':'home',choice,yellow:true,production_navigation_callback:true,ready_hides_notice:true});
 }
 for(const choice of ['weather','dashboard','native-clock']){const s=structuredClone(initial);s.faceplate_dashboard_home_source='weather';s.faceplate.routing.routes.home=choice;await page.evaluate(s=>window.refresh(s),s);assert.equal(await page.locator('[data-artwork-guidance]').count(),0);}
 const writes=(await page.evaluate(()=>window.calls)).filter(n=>n!=='report_runtime_diagnostic');assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);
 writeFileSync(path.join(out,'VALIDATION.json'),JSON.stringify({records,errors,no_extra_rpc_reads_or_hardware_writes:true,physicalSteamOSNavigation:false},null,2));
 console.log(JSON.stringify({scenarios:records.length,errors,no_extra_rpc_reads_or_hardware_writes:true}));
}finally{await browser?.close();await new Promise(r=>server.close(r));}
