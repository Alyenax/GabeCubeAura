// Actual React sources with simulated Decky controls; no physical USB actions.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {mkdirSync} from 'node:fs';
const {chromium}=createRequire(import.meta.url)('/Users/C/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const out=process.argv[4]||'/private/tmp/gca-lab185-browser';mkdirSync(out,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const errors=[];
try{
 for(const kind of ['quick','settings']){
  const page=await browser.newPage({viewport:kind==='quick'?{width:340,height:900}:{width:1280,height:900}});
  page.on('pageerror',error=>errors.push(String(error)));await page.goto(process.argv[kind==='quick'?3:2]);
  if(kind==='quick'){
   await page.waitForFunction(()=>typeof window.__gcaQuickRefresh==='function');
   await page.evaluate(()=>{const s=window.__gcaQaData.status;s.faceplate_lab_enabled=true;s.faceplate.available=true;s.faceplate.enabled=true;s.faceplate.powered=true;s.faceplate.phase='ready';window.__gcaQuickRefresh();});
  }else{
   await page.locator('.gca-content').waitFor();await page.locator('[data-qa-sidebar]>div:first-child [role=tab]').nth(4).click();
  }
  assert.equal(await page.evaluate(()=>window.__gcaQaData.status.faceplate_brightness),70);
  const slider=kind==='quick'?page.locator('.gca-compact-jsaux [role=slider]'):page.locator('[data-gca-category=faceplate] [role=slider]');
  // Use the live native-shaped slider rather than replacing the request in a status fixture.
  const control=await slider.count()?slider.first():page.getByRole('slider').last();
  await control.waitFor();
  for(const language of ['fr','en']){
   await page.evaluate(language=>window.__gcaQuickLanguage(language),language);
   const text=language==='fr'?'Au-delà de 70 %, la stabilité dépend de l’alimentation USB.':'Above 70%, stability depends on USB power.';
   const notice=page.getByRole('status').filter({hasText:text});await notice.waitFor({state:'hidden'});
   await control.focus();await page.keyboard.press('ArrowRight');await notice.waitFor();
   assert.equal(await control.getAttribute('aria-valuenow'),'75');
   const colour=await notice.evaluate(el=>getComputedStyle(el).color);assert.notEqual(colour,'rgb(255, 0, 0)');
   const bounds=await notice.boundingBox();assert(bounds&&bounds.x>=0&&bounds.x+bounds.width<=(kind==='quick'?341:1281));
   await notice.scrollIntoViewIfNeeded();await page.screenshot({path:`${out}/${kind}-${language}.png`,fullPage:kind==='quick'});
   await page.waitForFunction(()=>window.__gcaQaData.status.faceplate_brightness===75);
   await control.focus();await page.keyboard.press('ArrowLeft');await notice.waitFor({state:'hidden'});
   await page.waitForFunction(()=>window.__gcaQaData.status.faceplate_brightness===70);
  }
  assert.equal(await page.getByText(/USB protection:|Protection USB :/).count(),0);
  await page.close();
 }
 assert.deepEqual(errors,[]);
 console.log('PASS: fresh 70%, live 70→75→70 neutral notice in FR/EN, quick 340px and full settings 1280px, no obsolete automatic-limit caption or browser errors.');
}finally{await browser.close();}
