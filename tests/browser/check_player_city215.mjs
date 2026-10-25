// Real Settings/QAM sources and shared RPC fixture. No SteamOS/USB acceptance claim.
import {createRequire} from 'node:module';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {mkdirSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
const root=process.cwd(),require=createRequire(path.join(root,'../gabecubeaura-interface-preview/interface-preview/package.json'));
const {chromium}=require('playwright');
const server=spawn(process.execPath,['tests/browser/settings_preview.mjs'],{cwd:root,env:{...process.env,GCA_QA_VIEW:'player-city'},stdio:['ignore','pipe','pipe']});
let stderr='';server.stderr.on('data',b=>stderr+=b);
const url=await new Promise((resolve,reject)=>{createInterface({input:server.stdout}).on('line',line=>{const match=line.match(/http:\/\/127\.0\.0\.1:\d+\//);if(match)resolve(match[0]);});server.on('exit',code=>reject(Error('Fixture exited '+code+' '+stderr)));});
const out=path.join(root,'out/ui/player-city'+(process.env.GCA_CITY_LAB||'215'));mkdirSync(out,{recursive:true});let browser;
try{
 browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[],results=[];page.on('pageerror',e=>errors.push(e.message));
 for(const language of ['en','fr']){
  await page.goto(url);await page.waitForFunction(()=>!!document.querySelector('#gca-compact-root'));
  await page.evaluate(lang=>window.__gcaQuickLanguage(lang),language);
  const quick=page.getByRole('combobox',{name:language==='en'?'JSAUX screen':'Écran JSAUX',exact:true});await quick.waitFor();
  await quick.click();await page.getByRole('option',{name:'Steam Players City',exact:true}).click();
  await page.waitForFunction(()=>window.__gcaQaData.status.faceplate.routing.routes.game==='player-city');
  await page.getByRole('status').filter({hasText:/32,809/}).waitFor();
  assert.match(await page.getByRole('status').filter({hasText:/32,809/}).innerText(),/32,000/);
  await page.screenshot({path:path.join(out,language+'-quick.png'),fullPage:true});
  await page.evaluate(()=>{window.__gcaQaData.status.faceplate.player_city.sample.state='network_error';});
  await page.getByRole('status').filter({hasText:/connection unavailable|Connexion à Steam indisponible/}).waitFor();
  await page.evaluate(()=>{window.__gcaQaData.status.faceplate.player_city.sample.state='ready';});
  await page.getByRole('status').filter({hasText:/32,809/}).waitFor();
  const home=await page.evaluate(()=>window.__gcaQaData.status.faceplate.routing.routes.home);
  await page.evaluate(()=>window.__gcaCityView('settings'));
  const full=page.getByRole('combobox',{name:language==='en'?'Faceplate in game':'Faceplate en jeu',exact:true});await full.waitFor();
  assert.match(await full.innerText(),/Steam Players City/);
  await page.screenshot({path:path.join(out,language+'-settings.png'),fullPage:true});
  await full.click();await page.getByRole('option',{name:language==='en'?'Weather':'Météo',exact:true}).click();
  await page.waitForFunction(()=>window.__gcaQaData.status.faceplate.routing.routes.game==='weather');
  await page.evaluate(()=>window.__gcaCityView('quick'));await quick.waitFor();
  assert.match(await quick.innerText(),/Weather|Météo/);
  const calls=await page.evaluate(()=>window.__gcaQaCalls.filter(c=>c.name==='set_faceplate_routing'));
  assert.equal(calls.length,2);assert.equal(calls[0].args[1],'player-city');assert.equal(calls[1].args[1],'weather');
  assert.equal(calls[0].args[0],home);assert.equal(calls[1].args[0],home);
  assert.equal(calls[1].args[2],calls[0].args[2]+1,'Both surfaces share preference revision');
  await page.evaluate(()=>window.__gcaQaData.status.faceplate.available=false);await quick.waitFor({state:'detached'});
  await page.evaluate(()=>window.__gcaCityView('settings'));await page.locator('[data-qa-sidebar]').waitFor();
  assert.equal(await page.locator('[data-qa-sidebar]>div:first-child [role=tab]').filter({hasText:/Faceplate/}).count(),0);
  await page.evaluate(()=>{window.__gcaQaData.status.faceplate.available=true;window.__gcaQaData.status.game={appid:0,title:''};window.__gcaCityView('quick');});await quick.waitFor();
  await quick.click();assert.equal(await page.getByRole('option',{name:'Steam Players City',exact:true}).count(),0);await page.keyboard.press('Escape');
  results.push({language,hiddenInSettingsWhenDisconnected:true,absentAtHome:true,quickToSettings:true,settingsToQuick:true,sameRevision:true,hiddenWhenDisconnected:true,measuredAndDisplayedCountsDistinct:true,networkFailureAndRecoveryVisible:true});
 }
 assert.deepEqual(errors,[]);writeFileSync(path.join(out,'ui-validation.json'),JSON.stringify({results,errors,physicalSteamOS:false},null,2));console.log(JSON.stringify({results,errors}));
}finally{await browser?.close();server.kill('SIGTERM');if(server.exitCode===null)await new Promise(r=>server.once('exit',r));}
