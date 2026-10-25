// Actual settings components with isolated RPC and Steam CSS. No device I/O.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
import {mkdirSync,writeFileSync} from 'node:fs';
import {showSettingsTab} from './settings_tabs_helper.mjs';
const require=createRequire(process.env.GCA_QA_PLAYWRIGHT||'/Users/C/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json');
const {chromium}=require('playwright');
const url=process.argv[2];assert.match(url||'',/^http:\/\/127\.0\.0\.1:\d+\/$/);
const out='out/ui/dashboard201';mkdirSync(out,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const results=[];
try{
 for(const language of ['en','fr'])for(const width of [1280,800])for(const ready of [false,true]){
  const page=await browser.newPage({viewport:{width,height:900}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/app.js',async route=>{
   const response=await route.fetch();
   const setup=`{const s=window.__gcaQaData.status;s.ui_language=${JSON.stringify(language)};s.faceplate.routing.routes.home='dashboard';s.faceplate_dashboard_home_source=${JSON.stringify(ready?'artwork':'weather')};s.faceplate_dashboard_home_appid=${ready?620:0};s.faceplate_dashboard_show_clock=false;const prior=window.__gcaQaRpc;window.__gcaQaRpc=async(name,args)=>name==='get_faceplate_dashboard_background_status'?{appid:${ready?620:0},ready:${ready}}:name==='get_faceplate_artwork_library'?{entries:${JSON.stringify(ready?[{appid:620,mode:'static',dashboard_ready:true,name:'Portal 2',active:true}]:[])}}:prior(name,args);}`;
   await route.fulfill({response,body:setup+(await response.text()).replaceAll("setUILanguage('fr')",`setUILanguage('${language}')`)});
  });
  await page.goto(url);await page.locator('.gca-content').waitFor();
  await page.locator('[data-qa-sidebar]>div:first-child [role=tab]').filter({hasText:/Faceplate/}).first().focus();
  await page.getByRole('combobox',{name:/Faceplate/}).first().waitFor();
  await page.screenshot({path:`${out}/debug-${language}-${width}.png`});
  // Display uses a valid cross-tab label in both languages.
  assert(!/below|ci-dessous/.test(await page.getByRole('combobox',{name:language==='en'?'Faceplate at Home':'Faceplate à l’accueil',exact:true}).innerText()));
  await showSettingsTab(page,1);
  const headings=await page.locator('.DialogControlsSectionHeader').allTextContents();
  const expected=language==='en'?['Home background','Clock and weather','Bottom row']:['Fond à l’accueil','Horloge et météo','Ligne du bas'];
  assert.deepEqual(headings.filter(text=>expected.includes(text)),expected);
  const openArtwork=page.getByRole('button',{name:language==='en'?'Open Artwork tab':'Ouvrir Illustrations',exact:true});
  await openArtwork.waitFor();
  const notice=page.getByRole('status').filter({hasText:language==='en'?'No Artwork Dashboard is assigned.':'Aucun fond illustré n’est assigné.'});
  assert.equal(await notice.count(),ready?0:1);
  const before=await page.evaluate(()=>window.__gcaQaCalls.filter(c=>c.name.startsWith('set_')));assert.deepEqual(before,[]);
  if(!ready){
   const selector=page.getByRole('combobox',{name:language==='en'?'Dashboard at Home':'Tableau de bord à l’accueil',exact:true});
   await selector.press('ArrowDown');
   assert.equal(await page.evaluate(()=>window.__gcaQaData.status.faceplate_dashboard_home_source),'weather');
   await openArtwork.click();
   assert.equal(await page.locator('[data-qa-tabs] [role=tab]').nth(2).getAttribute('aria-selected'),'true');
   await page.locator('[data-qa-sidebar]>div:first-child [role=tab]').filter({hasText:/Faceplate/}).first().focus();
   await showSettingsTab(page,1);
  }
  const row=page.getByRole('checkbox',{name:language==='en'?'Show Dashboard bottom row':'Afficher la ligne du bas',exact:true});
  const content=page.getByRole('combobox',{name:language==='en'?'Default row content':'Contenu par défaut',exact:true});
  await row.click();await page.waitForFunction(()=>window.__gcaQaData.status.faceplate_dashboard_show_bottom_row===false);
  assert.equal(await content.count(),0);
  await row.click();await content.waitFor();
  await content.press('ArrowDown');await page.waitForFunction(()=>window.__gcaQaData.status.faceplate_dashboard_bottom_mode==='today');
  const clock=page.getByRole('checkbox',{name:language==='en'?'Home Dashboard Clock':'Horloge à l’accueil',exact:true});
  await clock.click();await page.getByRole('combobox',{name:language==='en'?'Dashboard clock':'Horloge du tableau de bord',exact:true}).waitFor();
  const geometry=await page.locator('[data-gca-control]').evaluateAll(nodes=>nodes.map(n=>({text:n.innerText,overflow:n.scrollWidth>n.clientWidth+2})));
  assert(geometry.every(item=>!item.overflow),JSON.stringify(geometry));
  await page.waitForTimeout(220);
  await page.screenshot({path:`${out}/${language}-${width}-${ready?'saved':'empty'}.png`});
  assert.deepEqual(errors,[]);
  results.push({language,width,ready,headings:expected,errors});await page.close();
 }
 writeFileSync(`${out}/validation.json`,JSON.stringify({scenarios:results.length,results,nativeNavigationExecuted:false,hardwareTested:false},null,2));
 console.log(JSON.stringify({scenarios:results.length,passed:true,output:out}));
}finally{await browser.close();}
