// Public settings source in a native-shaped browser fixture; no installation runs.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {mkdirSync} from 'node:fs';
import {showSettingsTab} from './settings_tabs_helper.mjs';
const {chromium}=createRequire(import.meta.url)('/Users/C/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const out=process.argv[3];mkdirSync(out,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const errors=[];
try{
 for(const width of [800,1280]){
  const page=await browser.newPage({viewport:{width,height:900}});page.on('pageerror',e=>errors.push(String(e)));
  await page.goto(process.argv[2]);await page.locator('.gca-content').waitFor();
  await page.evaluate(()=>window.__gcaQuickLanguage('en'));await page.getByRole('tab',{name:'Updates',exact:true}).click();await showSettingsTab(page,1);
  for(const lang of ['fr','en']){
   await page.evaluate(lang=>window.__gcaQuickLanguage(lang),lang);
   const toggle=page.getByRole('checkbox',{name:lang==='fr'?'Vérifier automatiquement les mises à jour':'Automatically check for updates',exact:true});await toggle.waitFor();
   assert.equal(await page.getByRole('checkbox',{name:/Download and install updates automatically|Télécharger et installer automatiquement les mises à jour/}).count(),0);
   const interval=page.getByRole('combobox',{name:lang==='fr'?'Intervalle de vérification':'Check interval',exact:true});
   await interval.click();for(const label of ['5 minutes','15 minutes'])assert.equal(await page.getByRole('option',{name:label,exact:true}).count(),0);
   for(const label of [lang==='fr'?'1 heure':'1 hour',lang==='fr'?'24 heures':'24 hours'])assert.equal(await page.getByRole('option',{name:label,exact:true}).count(),1);
   await page.screenshot({path:`${out}/public-choices-${lang}-${width}.png`});
   await page.getByRole('option',{name:lang==='fr'?'24 heures':'24 hours',exact:true}).click();await page.waitForFunction(()=>window.__gcaQaData.update.check_interval_minutes===1440);
   await toggle.click();await page.waitForFunction(()=>window.__gcaQaData.update.auto_check===false);assert.equal(await interval.isEnabled(),false);
   await toggle.click();await page.waitForFunction(()=>window.__gcaQaData.update.auto_check===true);assert.equal(await interval.isEnabled(),true);
  }
  await page.getByRole('tab',{name:'Advanced',exact:true}).click();
  assert.equal(await page.getByRole('tab',{name:/Compatibility|Compatibilité/,exact:true}).count(),0);
  await showSettingsTab(page,2);
  assert.equal(await page.getByRole('button',{name:/Previous screensaver collections|Anciennes collections/}).count(),0);
  assert.equal(await page.locator('.gca-content').getByText(/Previous screensaver collections|TW3-SteamRGB compatibility|StripMine compatibility/).count(),0);
  await page.screenshot({path:`${out}/data-${width}.png`});
  await page.evaluate(()=>{const s=window.__gcaQaData.status;s.faceplate.flash_protection={enabled:true,history_state:'ready',session:{confirmed:12},total:{confirmed:42,reused:8,deferred:2,uncertain:1},recent:[]};});
  for(const lang of ['en','fr']){
   await page.evaluate(lang=>window.__gcaQuickLanguage(lang),lang);
   await page.getByRole('tab',{name:lang==='fr'?'Faceplate JSAUX':'Faceplate Jsaux',exact:true}).click();await showSettingsTab(page,3);
   const economy=page.getByRole('checkbox',{name:lang==='fr'?'Actualisation économe':'Economy refresh',exact:true});await economy.waitFor();
   const text=await page.locator('.gca-content').innerText();assert.match(text,/77.*75/);assert.match(text,/14:03.*14:00/);assert.match(text,/42/);
   assert.doesNotMatch(text,/Hardware endurance is unknown|Groups non-urgent changes/);
   await page.screenshot({path:`${out}/economy-${lang}-${width}.png`});
   assert.equal(await page.getByText(lang==='fr'?'Diagnostic Faceplate':'Faceplate diagnostics',{exact:true}).count(),1);
   assert.equal(await page.getByText(/^(Technical details|Faceplate technical details|Détails techniques de la faceplate)$/).count(),0);
   const diagnostic=page.getByRole('button',{name:lang==='fr'?'Ouvrir':'Open',exact:true});assert.equal(await diagnostic.count(),1);await diagnostic.click();
   assert.deepEqual(await page.locator('.gca-content h3').allTextContents(),lang==='fr'?['Connexion','Affichage','Transferts']:['Connection','Display','Transfers']);
   await page.getByRole('heading',{name:lang==='fr'?'Transferts':'Transfers',exact:true}).scrollIntoViewIfNeeded();
   await page.screenshot({path:`${out}/diagnostics-${lang}-${width}.png`});
   await page.getByRole('button',{name:lang==='fr'?'Masquer':'Hide',exact:true}).click();

  }

  assert.equal(await page.evaluate(()=>window.__gcaQaCalls.some(c=>['prepare_update','install_prepared_update'].includes(c.name))),false);await page.close();
 }
 assert.deepEqual(errors,[]);console.log('PASS public updates: FR/EN 800/1280px, no 5/15-minute choices or automatic-install option; 24-hour selection and check toggle work.');
}finally{await browser.close();}
