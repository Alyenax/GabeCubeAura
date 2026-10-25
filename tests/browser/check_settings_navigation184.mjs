// Real React/CSS, simulated RPC/shoulders/native ref. Not a Steam nav engine.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {showSettingsTab} from './settings_tabs_helper.mjs';
const {chromium}=createRequire(import.meta.url)('/Users/C/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const url=process.argv[2];assert.match(url||'',/^http:\/\/127\.0\.0\.1:\d+\/$/);
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
try{
 const page=await browser.newPage({viewport:{width:1280,height:800}}),errors=[];
 page.on('pageerror',error=>errors.push(String(error)));
 await page.goto(url);await page.locator('.gca-content').waitFor();
 const side=page.locator('[data-qa-sidebar]>div:first-child [role=tab]');
 const tabs=()=>page.locator('[data-qa-tabs] [role=tab]');
 assert(await tabs().evaluateAll(items=>items.every(el=>el.tabIndex===-1&&getComputedStyle(el).pointerEvents==='none')));
 await side.nth(0).focus();
 const stripe=()=>side.nth(0).evaluate(el=>getComputedStyle(el).borderLeftColor);
 assert.equal(await stripe(),'rgb(143, 201, 242)');
 await showSettingsTab(page,1);
 const choice=page.getByRole('combobox',{name:'Effet à régler',exact:true});
 await choice.waitFor();assert.match(await choice.textContent(),/Personnalisation\+/);
 await choice.focus();assert.equal(await stripe(),'rgba(0, 0, 0, 0)');
 assert.equal(await side.nth(0).evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(34, 59, 80)');
 // The mock native ref records first-content requests only after a shoulder
 // switch made inside content. No production DOM focus workaround is used.
 await page.keyboard.press('e');await page.waitForFunction(()=>window.__gcaQaFocusRequests?.length>0);
 assert.equal(await page.locator('.gca-content').getAttribute('data-gca-tab'),'sync');
 assert(await page.evaluate(()=>document.querySelector('.gca-content button')===document.activeElement));
 assert.equal(await page.evaluate(()=>document.activeElement.getAttribute('role')),'combobox');
 const count=await page.evaluate(()=>window.__gcaQaFocusRequests.length);
 await side.nth(0).focus();assert.equal(await stripe(),'rgb(143, 201, 242)');
 await page.keyboard.press('q');await page.waitForTimeout(100);
 assert.equal(await page.evaluate(()=>window.__gcaQaFocusRequests.length),count,'shoulders in sidebar must not steal focus');
 await page.keyboard.press('ArrowRight');
 assert.equal(await page.locator('.gca-content').getAttribute('data-gca-tab'),'effects','D-pad must not change the selected tab');
 // Start a game, then re-enter the settings content. Selection follows the
 // observed appid, but a subsequent manual choice survives status polling.
 await page.evaluate(()=>{window.__gcaQaData.status.game={appid:42,title:'QA game'};});
 await side.nth(2).click();await side.nth(0).click();
 await page.waitForFunction(()=>document.querySelector('[aria-label="Effet à régler"]')?.textContent.includes('Couleurs'));
 await choice.click();await page.getByRole('option',{name:'Personnalisation+',exact:true}).click();
 await page.waitForTimeout(10_500);assert.match(await choice.textContent(),/Personnalisation\+/);
 await page.screenshot({path:'/private/tmp/gca-lab184-effects.png'});
 assert.deepEqual(await page.evaluate(()=>window.__gcaQaCalls.filter(c=>/^(set_|start_|configure_|prepare_|preview_)/.test(c.name))),[]);
 const deep=await browser.newPage();await deep.addInitScript(()=>{window.__gcaQaParams={source:'artwork'};});
 await deep.goto(url);
 await deep.getByRole('combobox',{name:'Effet à régler',exact:true}).waitFor();
 assert.equal(await deep.locator('.gca-content').getAttribute('data-gca-tab'),'effects');
 assert.match(await deep.getByRole('combobox',{name:'Effet à régler',exact:true}).textContent(),/Couleurs/);
 await deep.close();assert.deepEqual(errors,[]);
 console.log(JSON.stringify({headersNonfocusable:true,onlyShoulderTabSelection:true,focusStripeFollowsArea:true,nativeFirstControlRequest:true,sidebarFocusPreserved:true,gameSelectsArtwork:true,manualChoiceRetained:true,exactArtworkDeepLink:true,writes:0,errors,nativeNavigationExecuted:false},null,2));
}finally{await browser.close();}
