// Product behaviour and CSS in the actual React fixture, not physical USB proof.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {showSettingsTab} from './settings_tabs_helper.mjs';
const {chromium}=createRequire(import.meta.url)('/Users/C/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
try{
 const quick=await browser.newPage({viewport:{width:340,height:900}}),errors=[];
 quick.on('pageerror',e=>errors.push(String(e)));await quick.goto(process.argv[3]);
 const choose=async(name,value)=>{await quick.getByRole('combobox',{name,exact:true}).click();await quick.getByRole('option',{name:value,exact:true}).click();};
 for(const language of ['fr','en']){
  await quick.evaluate(language=>window.__gcaQuickLanguage(language),language);
  const name=language==='fr'?'Ambiance':'Ambience';await quick.getByRole('combobox',{name,exact:true}).click();
  const expected=language==='fr'?['Personnalisé','Modéré','Atmosphère','Signaux','Immersif','Immersif+','Festif']:['Custom','Moderate','Atmosphere','Signals','Immersive','Immersive+','Festive'];
  assert.deepEqual((await quick.getByRole('option').allTextContents()).map(s=>s.replace('✓','').trim()),expected);
  await quick.keyboard.press('Escape');
  for(const option of expected){await choose(name,option);const text=await quick.locator('.gca-preset-summary').textContent();assert(text.length>10&&text.length<100);}
 }
 const jsaux=quick.getByRole('slider',{name:'JSAUX brightness',exact:true});await jsaux.waitFor();
 await quick.evaluate(()=>{
  const prior=window.__gcaQaRpc;window.__gcaRejectBrightness=true;
  window.__gcaQaRpc=async(name,args)=>{if(name==='set_setting'&&args[0]==='faceplate_brightness'&&window.__gcaRejectBrightness){window.__gcaRejectBrightness=false;throw Error('Simulated save failure');}return prior(name,args);};
 });
 await jsaux.focus();await quick.keyboard.press('ArrowLeft');
 await quick.getByRole('alert').filter({hasText:'JSAUX brightness could not be saved'}).waitFor();
 assert.equal(await jsaux.getAttribute('aria-valuenow'),'100','Failure keeps confirmed setting');
 // Failure must not poison every later action by retaining a rejected writer chain.
 await choose('Ambience','Moderate');
 assert.equal(await quick.evaluate(()=>window.__gcaQaData.status.display_preset),'moderate');
 await jsaux.focus();await quick.keyboard.press('ArrowLeft');await quick.waitForTimeout(500);
 assert.equal(await quick.evaluate(()=>window.__gcaQaData.status.faceplate_brightness),95);
 await choose('JSAUX screen','Off');assert.equal(await jsaux.getAttribute('aria-disabled'),'true');
 await choose('JSAUX screen','Weather');assert.notEqual(await jsaux.getAttribute('aria-disabled'),'true');
 await quick.screenshot({path:'/private/tmp/gca-lab182-quick-en.png',fullPage:true});
 await quick.evaluate(()=>window.__gcaQuickLanguage('fr'));
 await quick.screenshot({path:'/private/tmp/gca-lab182-quick-fr.png',fullPage:true});
 assert.deepEqual(errors,[]);
 const full=await browser.newPage({viewport:{width:1280,height:900}});await full.goto(process.argv[2]);await full.locator('.gca-content').waitFor();
 const tabs=()=>full.locator('[data-qa-tabs] [role=tab]');
 const sidebar=full.locator('[data-qa-sidebar]>div:first-child [role=tab]');
 assert(await full.locator('.gca-preset-summary').count()>0,'Selected preset summary remains visible outside detailed help');
 await sidebar.nth(4).click();
 for(let index=0;index<await tabs().count();index++){
  await showSettingsTab(full,index);
  const colors=await full.evaluate(()=>{
   const f=window.__gcaQaNative.field,root=document.querySelector('[data-gca-category=faceplate]');
   return{heading:getComputedStyle(document.querySelector('.gca-heading h1')).color,
    labels:[...root.getElementsByClassName(f.FieldLabel)].map(el=>getComputedStyle(el).color),
    selected:getComputedStyle(root.querySelector('[role=tab][aria-selected=true]')).color};
  });
  assert.equal(colors.heading,'rgb(209, 194, 237)');assert.equal(colors.selected,'rgb(209, 194, 237)');
  assert(colors.labels.every(color=>color==='rgb(209, 194, 237)'),JSON.stringify(colors));
 }
 await showSettingsTab(full,0);await full.screenshot({path:'/private/tmp/gca-lab182-jsaux-settings.png'});
 await sidebar.first().click();
 const label=full.locator('[data-gca-control=slider]').first();
 assert.notEqual(await label.evaluate(el=>getComputedStyle(el.getElementsByClassName(window.__gcaQaNative.field.FieldLabel)[0]).color),'rgb(209, 194, 237)','Purple does not leak to lighting');
 console.log('PASS: seven options in order FR/EN; visible short summaries; JSAUX brightness failure/retry and independent ambience after failure; powered-off gating; purple labels across four JSAUX tabs only.');
}finally{await browser.close();}
