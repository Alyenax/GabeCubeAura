// Confirmation/RPC checks only: destructive behavior is tested on temporary files in Python.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
import {mkdirSync,writeFileSync} from 'node:fs';
import {showSettingsTab} from './settings_tabs_helper.mjs';
const require=createRequire('/Users/C/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json');
const {chromium}=require('playwright');
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const out='out/ui/reset201';mkdirSync(out,{recursive:true});const results=[];
try{
 for(const language of ['en','fr']){
  const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/app.js',async route=>{
   const response=await route.fetch();const setup=`{window.__gcaQaData.status.ui_language='${language}';const prior=window.__gcaQaRpc;window.__gcaQaRpc=async(name,args)=>{if(name==='factory_reset_configuration'||name==='reset_settings_only'){window.__gcaQaCalls.push({name,args});return structuredClone(window.__gcaQaData.status);}return prior(name,args);};}`;
   await route.fulfill({response,body:setup+(await response.text()).replaceAll("setUILanguage('fr')",`setUILanguage('${language}')`)});
  });
  await page.goto(process.argv[2]);await page.locator('.gca-content').waitFor();
  await page.locator('[data-qa-sidebar]>div:first-child [role=tab]').filter({hasText:/Advanced|Avancé/}).first().focus();
  await showSettingsTab(page,3);
  const action=all=>page.locator('[data-gca-control=action]').filter({hasText:language==='en'?(all?'Reset to defaults':'Reset settings only'):(all?'Rétablir les valeurs par défaut':'Réinitialiser les réglages uniquement')}).getByRole('button');
  const labels=await page.locator('[data-gca-control=action]').allTextContents();
  const fullIndex=labels.findIndex(s=>s.includes(language==='en'?'Reset to defaults':'Rétablir les valeurs par défaut'));
  assert.equal(labels.findIndex(s=>s.includes(language==='en'?'Reset settings only':'Réinitialiser les réglages uniquement')),fullIndex+1);
  await action(false).scrollIntoViewIfNeeded();await page.screenshot({path:`${out}/${language}-choices.png`});
  for(const all of [true,false]){
   await action(all).click();await page.getByRole('dialog').waitFor();
   const dialog=page.getByRole('dialog');assert((await dialog.innerText()).includes('SteamGridDB'));
   await dialog.getByRole('button',{name:language==='en'?'Cancel':'Annuler',exact:true}).click();
   assert.deepEqual(await page.evaluate(()=>window.__gcaQaCalls.filter(c=>/^(factory_reset|reset_settings)/.test(c.name))),[]);
  }
  for(const all of [false,true]){
   await action(all).click();const dialog=page.getByRole('dialog');await dialog.waitFor();
   await page.screenshot({path:`${out}/${language}-${all?'total':'settings'}-confirmation.png`});
   const name=language==='en'?(all?'Erase all GCA data':'Reset settings only'):(all?'Tout effacer dans GCA':'Réinitialiser les réglages uniquement');
   await dialog.getByRole('button',{name,exact:true}).click();
   await page.waitForFunction(name=>window.__gcaQaCalls.some(c=>c.name===name),all?'factory_reset_configuration':'reset_settings_only');
  }
  const calls=await page.evaluate(()=>window.__gcaQaCalls.filter(c=>/^(factory_reset|reset_settings)/.test(c.name)));
  assert.deepEqual(calls,[{name:'reset_settings_only',args:[]},{name:'factory_reset_configuration',args:['delete-gca-settings-content-and-access']}]);
  assert.deepEqual(errors,[]);results.push({language,cancelledWithoutWrites:true,calls,errors});await page.close();
 }
 writeFileSync(`${out}/validation.json`,JSON.stringify({results,actualUserDataTouched:false},null,2));console.log(JSON.stringify({scenarios:results.length,passed:true}));
}finally{await browser.close();}
