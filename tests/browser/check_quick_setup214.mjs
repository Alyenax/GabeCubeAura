// Actual QAM components and Steam CSS fixture; native gamepad navigation is not emulated.
import {createRequire} from 'node:module';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {mkdirSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
const root=process.cwd(),require=createRequire(path.join(root,'../gabecubeaura-interface-preview/interface-preview/package.json'));
const {chromium}=require('playwright');
const server=spawn(process.execPath,['tests/browser/settings_preview.mjs'],{cwd:root,env:{...process.env,GCA_QA_VIEW:'setup-gate'},stdio:['ignore','pipe','pipe']});
let stderr='';server.stderr.on('data',b=>stderr+=b);
const url=await new Promise((resolve,reject)=>{
 createInterface({input:server.stdout}).on('line',line=>{const match=line.match(/http:\/\/127\.0\.0\.1:\d+\//);if(match)resolve(match[0]);});
 server.on('exit',code=>reject(Error('Fixture exited '+code+' '+stderr)));
});
const out=path.join(root,'out/ui/setup214');mkdirSync(out,{recursive:true});let browser;
try{
 browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const page=await browser.newPage({viewport:{width:440,height:1100}}),errors=[],results=[];
 page.on('pageerror',e=>errors.push(e.message));
 for(const language of ['fr','en']){
  await page.goto(url);await page.waitForFunction(()=>!!document.querySelector('#gca-compact-root'));
  await page.evaluate(lang=>window.__gcaQuickLanguage(lang),language);
  const setup=page.getByRole('button',{name:language==='fr'?'Ouvrir la configuration guidée':'Open guided setup',exact:true});
  await setup.waitFor();
  const enabled=await page.locator('button:not(:disabled):not([aria-disabled=true]),[role=checkbox]:not([aria-disabled=true]),[role=slider]:not([aria-disabled=true])').allTextContents();
  assert.equal(enabled.length,1,JSON.stringify(enabled));assert.match(enabled[0],/configuration guidée|Open guided setup/);
  await page.keyboard.press('Tab');assert.equal(await setup.evaluate(n=>n===document.activeElement),true);
  await page.keyboard.press('Tab');assert.equal(await setup.evaluate(n=>document.activeElement===n||document.activeElement===document.body),true,'Focus stays on setup or returns to the page');
  await setup.click();assert.equal(await page.evaluate(()=>window.__gcaQaNavigation),'/gabecubeaura/setup');
  assert.equal(await page.evaluate(()=>window.__gcaQaCalls.filter(c=>!c.name.startsWith('get_')&&c.name!=='report_runtime_diagnostic').length),0);
  await page.screenshot({path:path.join(out,language+'-locked.png'),fullPage:true});
  await page.evaluate(()=>window.__gcaQaData.status.onboarding_completed=true);
  await setup.waitFor({state:'detached'});await page.getByRole('button',{name:language==='fr'?'Réglages':'Settings',exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:language==='fr'?'Réglages':'Settings',exact:true}).isEnabled(),true);
  assert.equal(await page.getByRole('checkbox').isEnabled(),true);
  await page.screenshot({path:path.join(out,language+'-unlocked.png'),fullPage:true});
  await page.evaluate(()=>window.__gcaQaData.status.onboarding_completed=false);await setup.waitFor();
  assert.equal(await page.getByRole('button',{name:language==='fr'?'Réglages':'Settings',exact:true}).isDisabled(),true);
  assert.equal(await page.locator('button:not(:disabled):not([aria-disabled=true])').count(),1);
  results.push({language,onlySetupActive:true,confirmationUnlocks:true,resetRelocks:true,noMutationWhileLocked:true});
 }
 assert.deepEqual(errors,[]);
 writeFileSync(path.join(out,'validation.json'),JSON.stringify({results,errors,physicalSteamOS:false},null,2));
 console.log(JSON.stringify({results,errors}));
}finally{await browser?.close();server.kill('SIGTERM');if(server.exitCode===null)await new Promise(r=>server.once('exit',r));}
