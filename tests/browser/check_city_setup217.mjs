// Actual setup selection -> draft RPC -> backend validation. Device presence is simulated.
// DOM/native-shaped controls only; physical SteamOS navigation/optics remain pending.
import {createRequire} from 'node:module';
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import http from 'node:http';
import path from 'node:path';
import assert from 'node:assert/strict';
const root=process.cwd(),require=createRequire(path.join(root,'../gabecubeaura-interface-preview/interface-preview/package.json'));
const {build}=require('esbuild'),{chromium}=require('playwright');
const python=String.raw`
import sys,json,tempfile,asyncio,threading
from pathlib import Path
from test_cinema_integration import plugin_class
from test_lab101_runtime_ack import FakeHardware
from signalbar.settings import SettingsStore
from signalbar.backend import Engine
from signalbar.onboarding import OnboardingDraft
with tempfile.TemporaryDirectory() as folder:
 root=Path(folder);store=SettingsStore(str(root/'settings.json'))
 store.update({'home_display':'customization','faceplate_lab_enabled':False,'valve_ownership_policy':'critical'})
 before=(root/'settings.json').read_bytes()
 engine=Engine(store,str(root/'cache'),hardware_factory=FakeHardware)
 plugin=plugin_class()();plugin.engine=engine;plugin.onboarding_draft=OnboardingDraft(root/'setup-draft.json')
 engine.faceplate.device_status=lambda:{"available":True,"busy":False}
 engine.faceplate.port_finder=lambda:None
 engine.start()
 allowed={'get_status','get_onboarding','save_onboarding_draft','preview_display_preset','stop_display_preset_preview'}
 print(json.dumps({'ready':True}),flush=True)
 try:
  for line in sys.stdin:
   request=json.loads(line);name=request['name']
   try:
    if name=='verify_qa':result={'settings_unchanged':before==(root/'settings.json').read_bytes(),'draft':plugin.onboarding_draft.resume(),'route':engine.faceplate_preferences.read().game_scene}
    elif name=='reset_qa':plugin.onboarding_draft.restart();result=True
    elif name in allowed:result=asyncio.run(getattr(plugin,name)(*request['args']))
    else:raise ValueError('Unexpected setup RPC '+name)
    print(json.dumps({'id':request['id'],'result':result}),flush=True)
   except Exception as error:print(json.dumps({'id':request['id'],'error':str(error)}),flush=True)
 finally:engine.stop()
`;
const child=spawn('python3',['-u','-c',python],{cwd:root,env:{...process.env,TMPDIR:'/private/tmp',PYTHONPATH:'py_modules:tests/backend'},stdio:['pipe','pipe','pipe']});
let readyResolve;const ready=new Promise(r=>readyResolve=r),pending=new Map(),calls=[];let id=0,stderr='';child.stderr.on('data',data=>stderr+=data);
createInterface({input:child.stdout}).on('line',line=>{const value=JSON.parse(line);if(value.ready)readyResolve();else{const p=pending.get(value.id);pending.delete(value.id);value.error?p.reject(Error(value.error)):p.resolve(value.result);}});
const rpc=(name,args=[])=>new Promise((resolve,reject)=>{const key=++id;calls.push({name,args});pending.set(key,{resolve,reject});child.stdin.write(JSON.stringify({id:key,name,args})+'\n');});
await ready;
const app=`import React,{useState} from 'react';import {createRoot} from 'react-dom/client';import {FirstRunOnboarding} from '${root}/src/components/FirstRunOnboarding';import {setUILanguage} from '${root}/src/i18n';
function App(){const[s,set]=useState(window.initial),[open,show]=useState(true);return open?React.createElement(FirstRunOnboarding,{status:s,setStatus:set,onClose:()=>show(false),openBrowser:()=>{}}):React.createElement('p',null,'Closed');}
setUILanguage(window.initial.ui_language);const root=createRoot(document.getElementById('app'));window.__unmount=()=>root.unmount();root.render(React.createElement(App));`;
const bundle=(await build({stdin:{contents:app,resolveDir:root,loader:'tsx'},bundle:true,write:false,jsx:'automatic',define:{'process.env.NODE_ENV':'"production"'},plugins:[{name:'native-controls',setup(b){
 b.onResolve({filter:/^react(?:\/.*)?$|^react-dom(?:\/.*)?$/},a=>({path:require.resolve(a.path)}));
 b.onResolve({filter:/^@decky\/ui$/},()=>({path:path.join(root,'tests/browser/settings_ui_shim.tsx')}));
 b.onResolve({filter:/^@decky\/api$/},()=>({path:'rpc',namespace:'qa'}));
 b.onLoad({filter:/.*/,namespace:'qa'},()=>({contents:`export const callable=name=>(...args)=>fetch('/rpc',{method:'POST',body:JSON.stringify({name,args})}).then(async r=>{const d=await r.json();if(d.error)throw Error(d.error);return d.result;});`,loader:'ts'}));
 }}]})).outputFiles[0].text;
const server=http.createServer(async(req,res)=>{try{
 if(req.url==='/rpc'){let raw='';for await(const part of req)raw+=part;const {name,args}=JSON.parse(raw);res.setHeader('Content-Type','application/json');res.end(JSON.stringify({result:await rpc(name,args)}));return;}
 if(req.url==='/app.js'){res.setHeader('Content-Type','text/javascript');res.end(bundle);return;}
 const status=await rpc('get_status');status.ui_language=req.url?.includes('fr')?'fr':'en';
 res.setHeader('Content-Type','text/html');res.end(`<!doctype html><html><meta charset="utf-8"><style>html,body,#app{height:100%;margin:0}body{font:16px Arial;background:#0e141b;color:#dcdedf}button{font:inherit;padding:10px;color:inherit;background:#263448;border:1px solid #647489}button:focus{outline:3px solid white}p{line-height:1.35}</style><div id="app"></div><script>window.initial=${JSON.stringify(status)}</script><script src="/app.js"></script></html>`);
 }catch(error){res.end(JSON.stringify({error:String(error)}));}});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const out=path.join(root,'out/ui/player-city217');mkdirSync(out,{recursive:true});let browser;
try{
 browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[],results=[];page.on('pageerror',e=>errors.push(e.message));
 for(const language of ['en','fr']){
  await rpc('reset_qa');
  await page.goto(`http://127.0.0.1:${server.address().port}/${language}`);
  const next=page.getByRole('button',{name:language==='fr'?'Continuer':'Continue',exact:true});
  await next.click();await page.getByText(language==='fr'?'Diminuer le soir':'Dim in the evening',{exact:true}).waitFor();await next.click();
  await page.getByRole('button',{name:/Oui, la configurer|Yes, configure it/}).click();
  const home=page.getByRole('combobox',{name:language==='fr'?'À l’accueil':'At Home',exact:true});
  await home.click();await page.getByRole('option',{name:/Horloge native|Native clock/}).click();
  const game=page.getByRole('combobox',{name:language==='fr'?'En jeu':'In game',exact:true});
  await game.click();await page.getByRole('option',{name:'Steam Players City',exact:true}).click();
  await page.waitForFunction(()=>document.body.innerText.includes('Steam Players City'));
  await page.waitForTimeout(500);
  const saved=await rpc('verify_qa');assert.equal(saved.draft.game,'player-city');assert(saved.settings_unchanged);
  await page.screenshot({path:path.join(out,`${language}-setup-city.png`),fullPage:true});
  await next.click();
  await page.getByRole('textbox',{name:language==='fr'?'Ville ou code postal':'City or postal code'}).waitFor();
  assert.equal(await page.getByText('SteamGridDB',{exact:true}).count(),0);
  results.push({language,cityOption:true,persistentDraft:true,weatherRequested:true,noArtworkKey:true,settingsUnchanged:saved.settings_unchanged});
  await page.evaluate(()=>window.__unmount());
 }
 assert.deepEqual(errors,[]);
 const record={results,errors,physicalHardware:false};
 writeFileSync(path.join(out,'setup-validation.json'),JSON.stringify(record,null,2));console.log(JSON.stringify(record));
}finally{await browser?.close();await new Promise(r=>server.close(r));child.stdin.end();await new Promise(r=>child.on('exit',r));if(stderr)console.error(stderr);}
