// Real setup component with native-shaped controls; Steam footer is a DOM overlay.
// Verifies layout and keyboard callbacks, not physical Steam gamepad navigation.
import {createRequire} from 'node:module';
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import assert from 'node:assert/strict';
const root=process.env.GCA_SOURCE||process.cwd();
const require=createRequire('/Users/C/Documents/Chrome/Xplorarr Project - NEXT/gabecubeaura-interface-preview/interface-preview/package.json');
const {build}=require('esbuild'),{chromium}=require('playwright');
const app=`import React,{useState} from 'react';import {createRoot} from 'react-dom/client';import {FirstRunOnboarding} from '${root}/src/components/FirstRunOnboarding';import {setUILanguage} from '${root}/src/i18n';import {FaceplateSetupNotice} from '${root}/src/components/FaceplateSetupNotice';
function App(){const[s,set]=useState(window.initial);const[mode,changeMode]=useState(window.startMode);if(mode==='notice')return <FaceplateSetupNotice status={s} onOpen={()=>changeMode('faceplate')}/>;return <FirstRunOnboarding faceplateOnly={mode==='faceplate'} status={s} setStatus={set} onClose={()=>{window.closedSetup=true}} openBrowser={()=>{}}/>;}setUILanguage(window.initial.ui_language);createRoot(document.getElementById('app')).render(<App/>);`;
const bundle=(await build({stdin:{contents:app,resolveDir:root,loader:'tsx'},bundle:true,write:false,jsx:'automatic',define:{'process.env.NODE_ENV':'"production"'},plugins:[{name:'fixture',setup(b){
 b.onResolve({filter:/^react(?:\/.*)?$|^react-dom(?:\/.*)?$/},a=>({path:require.resolve(a.path)}));
 b.onResolve({filter:/^@decky\/ui$/},()=>({path:path.join(root,'tests/browser/settings_ui_shim.tsx')}));
 b.onResolve({filter:/^@decky\/api$/},()=>({path:'rpc',namespace:'qa'}));
 b.onLoad({filter:/.*/,namespace:'qa'},()=>({contents:`export const callable=name=>(...args)=>window.rpc(name,args);`,loader:'ts'}));
}}]})).outputFiles[0].text;
const initial={ui_language:'en',light_bar_day_brightness:9,night_mode_enabled:false,night_mode_brightness:35,weather_location:null,faceplate:{routing:{routes:{home:'dashboard',game:'artwork'}},steamgriddb:{configured:false}},controllers:[],onboarding_completed:false};
const server=http.createServer((req,res)=>{
 if(req.url==='/app.js'){res.setHeader('Content-Type','text/javascript');res.end(bundle);return;}
 res.setHeader('Content-Type','text/html');res.end(`<!doctype html><html><meta charset="utf-8"><style>
 html,body,#app{height:100%;margin:0}*{box-sizing:border-box}body{font:16px Arial;background:#0e141b;color:#dcdedf}
 .qa-native-scroll-panel{height:100%;overflow-y:auto}button{font:inherit;padding:12px;color:inherit;background:#263448;border:1px solid #647489}button:focus{outline:3px solid white}p{line-height:1.35}
 #steam-footer{position:fixed;left:0;right:0;bottom:0;height:64px;background:#202a35;z-index:100;padding:16px;color:white}
 </style><div id="app"></div><div id="steam-footer">Steam · A Select · B Back</div><script>
 window.startMode=${JSON.stringify(req.url?.includes('notice')?'notice':'full')};window.initial=${JSON.stringify({...initial,ui_language:req.url?.includes('fr')?'fr':'en',onboarding_completed:Boolean(req.url?.includes('notice')),faceplate_setup_completed:false,faceplate:{...initial.faceplate,available:true}})};window.rpcCalls=[];window.draft={step:'ambiance',preset:'moderate',brightness:9,night:false,night_percentage:35,city:null,faceplate_requested:null,home:'dashboard',game:'artwork'};
 window.rpc=async(name,args)=>{window.rpcCalls.push(name);if(name==='get_onboarding')return {draft:window.draft,bar_detected:true,faceplate_detected:true,faceplate_busy:false};if(name==='save_onboarding_draft'){window.draft=args[0];return window.draft}if(name==='complete_onboarding'){window.applied=args[0];return {...window.initial,onboarding_completed:true,faceplate_setup_completed:true}};if(name==='get_status')return {...window.initial,display_preset_preview:{active:false}};return {};};
 </script><script src="/app.js"></script></html>`);
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const out=process.env.GCA_SETUP_QA_OUTPUT||path.join(root,'out/ui/setup-actions243');mkdirSync(out,{recursive:true});
let browser;const records=[],errors=[];
try{
 browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const page=await browser.newPage();page.on('pageerror',e=>errors.push(e.message));
 for(const [width,height] of [[1280,720],[1280,800],[1920,1080],[1024,600]])for(const language of ['en','fr']){
  await page.setViewportSize({width,height});await page.goto(`http://127.0.0.1:${server.address().port}/${language}`);
  const cta=page.locator('[data-setup-actions]').getByRole('button',{name:language==='fr'?'Continuer':'Continue',exact:true});await cta.waitFor();
  const inspect=async(step)=>{
   const result=await page.evaluate(()=>{const root=document.querySelector('[data-setup-scroll]').parentElement,footer=document.querySelector('[data-setup-actions]'),scroll=document.querySelector('[data-setup-scroll]'),steam=document.querySelector('#steam-footer'),box=x=>{const r=x.getBoundingClientRect();return {top:r.top,bottom:r.bottom,height:r.height}};return {footer:box(footer),steam:box(steam),scroll:box(scroll),outerScroll:window.scrollY,buttons:[...footer.querySelectorAll('button')].map(x=>({label:x.innerText,...box(x)})),insideScroll:scroll.contains(footer),root:box(root)};});
   assert(!result.insideScroll);assert(result.footer.bottom<=result.steam.top-20,JSON.stringify(result));assert(result.scroll.bottom<=result.footer.top+1);assert.equal(result.outerScroll,0);for(const b of result.buttons){assert(b.top>=0);assert(b.bottom<=result.steam.top-20,JSON.stringify(b));}records.push({width,height,language,step,...result});
  };
  await inspect('ambiance');await page.locator('.qa-native-scroll-panel').evaluate(x=>x.scrollTop=x.scrollHeight);await inspect('ambiance-scrolled');
  await cta.focus();await page.keyboard.press('Enter');await page.waitForFunction(()=>document.querySelector('[aria-current="step"]')?.textContent?.includes('Brightness')||document.querySelector('[aria-current="step"]')?.textContent?.includes('Luminosité'));await inspect('brightness');
  await cta.click();await page.getByRole('button',{name:new RegExp(language==='fr'?'Oui, la configurer':'Yes, configure it')}).click();await cta.click();await inspect('services');
  await cta.click();await inspect('review');
  if(width===1280&&height===720){await page.goto(`http://127.0.0.1:${server.address().port}/${language}`);await cta.waitFor();await page.screenshot({path:path.join(out,language+'-1280x720.png')});}
 }
 for(const language of ['en','fr']){
  await page.setViewportSize({width:1280,height:720});await page.goto(`http://127.0.0.1:${server.address().port}/${language}?notice`);
  const open=page.getByRole('button',{name:language==='fr'?'Configurer ma faceplate':'Set up my Faceplate',exact:true});await open.waitFor();
  assert.equal(await page.getByRole('status').evaluate(x=>getComputedStyle(x).color),'rgb(255, 210, 122)');
  await page.screenshot({path:path.join(out,language+'-upgrade-notice.png')});await open.click();
  const cta=page.locator('[data-setup-actions]').getByRole('button',{name:language==='fr'?'Continuer':'Continue',exact:true});await cta.waitFor();
  assert.match(await page.locator('[aria-current="step"]').innerText(),/faceplate/i);
  assert.equal(await page.getByRole('button',{name:/Modéré|Moderate/}).count(),0,'No bar recipe in the upgrade flow');
  await page.getByRole('button',{name:new RegExp(language==='fr'?'Oui, la configurer':'Yes, configure it')}).click();await cta.click();
  await page.waitForFunction(()=>document.querySelector('[aria-current="step"]')?.textContent?.match(/Images/));await cta.click();
  const confirm=page.getByRole('button',{name:language==='fr'?'Confirmer et terminer':'Confirm and finish',exact:true});await confirm.waitFor();
  await confirm.click();await page.waitForFunction(()=>window.closedSetup===true);
  const applied=await page.evaluate(()=>window.applied);assert.deepEqual(Object.keys(applied).sort(),['city','faceplate_requested','game','home']);assert.equal(applied.faceplate_requested,true);
  records.push({language,step:'upgrade-faceplate-only',applied});
 }
 assert.deepEqual(errors,[]);writeFileSync(path.join(out,'RESULT.json'),JSON.stringify({scenarios:records.length,errors,physicalSteamNavigation:'not exercised',records},null,2));console.log(JSON.stringify({scenarios:records.length,errors}));
}finally{await browser?.close();await new Promise(r=>server.close(r));}
