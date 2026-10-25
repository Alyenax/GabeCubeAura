// Real React setup and native-shaped controls, mocked RPC boundary only.
import {createRequire} from 'node:module';
import {mkdirSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import assert from 'node:assert/strict';
const root=process.env.GCA_SOURCE||process.cwd();
const require=createRequire('/Users/C/Documents/Chrome/Xplorarr Project - NEXT/gabecubeaura-interface-preview/interface-preview/package.json');
const {build}=require('esbuild'),{chromium}=require('playwright');
const app=`import React,{useState} from 'react';import {createRoot} from 'react-dom/client';import {FirstRunOnboarding} from '${root}/src/components/FirstRunOnboarding';import {setUILanguage} from '${root}/src/i18n';
function App(){const[s,set]=useState(window.state);return <FirstRunOnboarding faceplateOnly status={s} setStatus={set} onClose={()=>{window.closedSetup=true}} openBrowser={()=>{}}/>;}setUILanguage(window.state.ui_language);createRoot(document.getElementById('app')).render(<App/>);`;
const bundle=(await build({stdin:{contents:app,resolveDir:root,loader:'tsx'},bundle:true,write:false,jsx:'automatic',define:{'process.env.NODE_ENV':'"production"'},plugins:[{name:'fixture',setup(b){
 b.onResolve({filter:/^react(?:\/.*)?$|^react-dom(?:\/.*)?$/},a=>({path:require.resolve(a.path)}));
 b.onResolve({filter:/^@decky\/ui$/},()=>({path:path.join(root,'tests/browser/settings_ui_shim.tsx')}));
 b.onResolve({filter:/^@decky\/api$/},()=>({path:'rpc',namespace:'qa'}));
 b.onLoad({filter:/.*/,namespace:'qa'},()=>({contents:`export const callable=name=>(...args)=>window.rpc(name,args);`,loader:'ts'}));
}}]})).outputFiles[0].text;
const initial={ui_language:'en',light_bar_day_brightness:15,night_mode_enabled:false,night_mode_brightness:75,
 weather_location:null,onboarding_completed:true,faceplate_setup_completed:true,display_preset:'custom',
 signalbar_enabled:true,faceplate_lab_enabled:true,current_display:'weather',faceplate_dashboard_home_source:'weather',game:{appid:0},
 faceplate:{available:true,powered:false,steamgriddb:{configured:false},delivery:{state:'idle'},power_recovery:{suspended:false,route_state:'idle'},
 routing:{routes:{home:'dashboard',game:'artwork'},desired_scene:'dashboard',effective_scene:'artwork',desired_content_key:'new',effective_content_key:'old',preparation:{state:'pending'}}}};
const server=http.createServer((req,res)=>{
 if(req.url==='/app.js'){res.setHeader('Content-Type','text/javascript');res.end(bundle);return;}
 const fr=req.url?.includes('fr');res.setHeader('Content-Type','text/html');res.end(`<!doctype html><html><meta charset="utf-8"><style>html,body,#app{height:100%;margin:0}body{font:16px Arial;background:#0e141b;color:white}.qa-native-scroll-panel{height:100%;overflow:auto}button{padding:12px}</style><div id="app"></div><script>
 window.state=${JSON.stringify({...initial,ui_language:fr?'fr':'en'})};window.closedSetup=false;window.calls=[];window.ack=false;window.offset=0;
 const realNow=Date.now;Date.now=()=>realNow()+window.offset;
 window.rpc=async(name,args)=>{window.calls.push(name);if(name==='complete_onboarding')window.applied=args[0];if(name==='get_onboarding')return {draft:{step:'review',preset:'custom',brightness:15,night:false,night_percentage:75,city:null,faceplate_requested:window.notNow?false:true,home:'artwork',game:'keep'},bar_detected:true,faceplate_detected:true,faceplate_busy:false};
 if(name==='complete_onboarding'){if(window.disconnect)window.state.faceplate.available=false;return structuredClone(window.state);}
 if(name==='get_status'){if(window.ack){const p=window.state.faceplate;p.powered=true;p.delivery.state='confirmed';p.routing.effective_scene=window.wrongScene?'artwork':'dashboard';p.routing.effective_content_key='new';p.routing.preparation.state='ready';}return structuredClone(window.state);}
 return {};};</script><script src="/app.js"></script></html>`);
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const out=process.env.GCA_SETUP_QA_OUTPUT||path.join(root,'out/ui/setup-confirmation252');mkdirSync(out,{recursive:true});
let browser;const records=[],errors=[];
try{
 browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const page=await browser.newPage({viewport:{width:1280,height:800}});page.on('pageerror',e=>errors.push(e.message));
 for(const language of ['en','fr']){
  const load=async()=>{await page.goto(`http://127.0.0.1:${server.address().port}/${language}`);await page.getByRole('button',{name:language==='fr'?'Confirmer et terminer':'Confirm and finish',exact:true}).waitFor();};
  await load();await page.getByRole('button',{name:language==='fr'?'Modifier les affichages':'Edit displays',exact:true}).click();
  await page.getByText(language==='fr'?'À l’accueil : Dashboard Weather':'At Home: Dashboard Weather',{exact:true}).waitFor();
  await page.getByText(language==='fr'?'Aucun artwork n’est fourni.':'No artwork is included.',{exact:false}).waitFor();
  assert.equal(await page.getByText(language==='fr'?'À l’accueil':'At Home',{exact:true}).count(),0);
  await page.screenshot({path:path.join(out,`home-policy-${language}.png`)});
  records.push({language,scenario:'fixed Dashboard Weather and create-your-own artwork notice',passed:true});
  const finish=()=>page.getByRole('button',{name:language==='fr'?'Confirmer et terminer':'Confirm and finish',exact:true}).click();
  await load();await finish();assert.equal(await page.evaluate(()=>window.applied.home),'dashboard');await page.waitForFunction(()=>window.calls.includes('get_status'));
  assert.equal(await page.evaluate(()=>window.closedSetup),false);await page.getByRole('status').filter({hasText:language==='fr'?'Activation':'Activating'}).waitFor();
  await page.screenshot({path:path.join(out,`waiting-${language}.png`)});
  await page.evaluate(()=>{window.ack=true;window.wrongScene=true;});await page.waitForTimeout(900);
  assert.equal(await page.evaluate(()=>window.closedSetup),false,'An old confirmed artwork is not the selected Weather');
  await page.evaluate(()=>window.wrongScene=false);await page.waitForFunction(()=>window.closedSetup===true);
  assert.equal(await page.evaluate(()=>window.calls.filter(n=>n==='complete_onboarding').length),1);
  records.push({language,scenario:'wait for current-route USB receipt',passed:true});
  await load();await finish();await page.waitForFunction(()=>window.calls.includes('get_status'));await page.evaluate(()=>window.offset=100000);
  await page.getByRole('alert').waitFor();assert.equal(await page.evaluate(()=>window.closedSetup),false);
  await page.screenshot({path:path.join(out,`retry-${language}.png`)});
  await page.evaluate(()=>window.ack=true);await finish();await page.waitForFunction(()=>window.closedSetup===true);
  records.push({language,scenario:'timeout keeps guide open and explicit retry succeeds',passed:true});
 }
 assert.deepEqual(errors,[]);writeFileSync(path.join(out,'VALIDATION.json'),JSON.stringify({records,errors,physicalSteamOS:false},null,2));
 console.log(JSON.stringify({scenarios:records.length,errors,physicalSteamOS:false}));
}finally{await browser?.close();await new Promise(r=>server.close(r));}
