// UI-only fixture: never confirms a power action or calls a real Steam API.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
import {showSettingsTab} from './settings_tabs_helper.mjs';
const require=createRequire('/Users/C/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json');
const {chromium}=require('playwright'),url=process.argv[2];
assert.match(url||'',/^http:\/\/127\.0\.0\.1:\d+\/$/);
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
try{
 const page=await browser.newPage({viewport:{width:1280,height:800}}),errors=[];
 page.on('pageerror',error=>errors.push(String(error)));
 await page.goto(url);
 await page.locator('[data-qa-sidebar]>div:first-child [role=tab]').nth(1).click();
 await showSettingsTab(page,3);
 const choice=page.getByRole('combobox',{name:'À la fin du prochain minuteur'});
 assert.match(await choice.textContent(),/Ne rien faire/);
 await page.screenshot({path:'/private/tmp/gca-lab166-playtime.png'});
 for(const[label,title]of[['Mettre la console en veille','Lancer le minuteur avec mise en veille ?'],['Éteindre la console','Lancer le minuteur avec extinction ?']]){
   await choice.click();await page.getByRole('option',{name:label,exact:true}).click();
   await page.getByRole('button',{name:'Démarrer / redémarrer',exact:true}).click();
   const modal=page.getByRole('dialog');await modal.waitFor();assert.match(await modal.textContent(),/Pense à sauvegarder/);
   assert.equal(await modal.locator('h2').textContent(),title);
   await page.screenshot({path:label.startsWith('Éteindre')?'/private/tmp/gca-lab166-timer-shutdown.png':'/private/tmp/gca-lab166-timer-sleep.png'});
   await modal.getByRole('button',{name:'Annuler',exact:true}).click();
 }
 const starts=await page.evaluate(()=>window.__gcaQaCalls.filter(call=>call.name==='start_free_timer'));
 assert.deepEqual(starts,[]);assert.deepEqual(errors,[]);
 console.log(JSON.stringify({choices:3,confirmations:['sleep','shutdown'],cancelledWithoutTimerStart:true,realPowerActions:0,errors},null,2));
}finally{await browser.close();}
