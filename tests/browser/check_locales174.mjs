// Real React sources with simulated Decky controls/RPC, no physical actions.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
import {showSettingsTab} from './settings_tabs_helper.mjs';
const require=createRequire('/Users/C/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json');
const {chromium}=require('playwright');
const url=process.argv[2];assert.match(url||'',/^http:\/\/127\.0\.0\.1:\d+\/$/);
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
try{
 const page=await browser.newPage({viewport:{width:1280,height:800}}),errors=[];
 page.on('pageerror',error=>errors.push(String(error)));
 await page.goto(url);await page.locator('.gca-content').waitFor();
 const side=page.locator('[data-qa-sidebar]>div:first-child [role=tab]');
 const tabs=()=>page.locator('[data-qa-tabs] [role=tab]');
 let views=0;
 for(const locale of ['fr','en']){
  const expected=locale==='fr'?['Éclairage','Signaux lumineux','Météo','Assistant vocal','Faceplate JSAUX','Mises à jour','Avancé']:['Display Light','Signals light','Weather','Voice Assistant','Faceplate Jsaux','Updates','Advanced'];
  assert.deepEqual(await side.allTextContents(),expected);
  for(let category=0;category<7;category++){
   await side.nth(category).click();
   const count=await tabs().count();
   for(let tab=0;tab<count;tab++){
    await showSettingsTab(page,tab);await page.waitForTimeout(45);views++;
    assert.equal(await page.locator('.gca-heading h1').textContent(),expected[category]);
   }
  }
  await side.nth(0).click();await showSettingsTab(page,3);
  const edit=page.getByRole('checkbox',{name:locale==='fr'?'Modifier le profil':'Edit profile details',exact:true});
  await edit.click();
  const profiles=await page.locator('.gca-content').textContent();
  assert.match(profiles,locale==='fr'?/Gabe : « mets un mode soirée »/:/Gabe: “set evening mode”/);
  if(locale==='en')assert.doesNotMatch(profiles,/mets un mode|retour automatique|Crée les profils/);
  await side.nth(3).click();await showSettingsTab(page,1);
  await page.getByRole('checkbox',{name:locale==='fr'?'Tous les assistants à la voix':'All assistants by voice',exact:true}).waitFor();
  await page.screenshot({path:`/private/tmp/gca174-voice-${locale}.png`});
  await side.nth(3).click();await showSettingsTab(page,0);
  await page.getByRole('combobox',{name:locale==='fr'?'Assistant assigné':'Assigned assistant',exact:true}).waitFor();
  if(locale==='fr'){
   await side.nth(6).click();await showSettingsTab(page,0);
   await page.getByRole('checkbox',{name:'Interface en français',exact:true}).click();
   await page.waitForFunction(()=>window.__gcaQaData.status.ui_language==='en');
  }
 }
 // A French stock backend failure must be English in the English UI, while
 // the selected spoken conversation language deliberately remains French.
 await page.evaluate(()=>{window.__gcaQaData.voice.error='La banque de voix locale manque ou est invalide. Réinstalle GabeCubeAura.';});
 await side.nth(0).click();await side.nth(3).click();
 await page.getByText('The local voice bank is missing or invalid. Reinstall GabeCubeAura.',{exact:true}).waitFor();
 assert.equal(await page.evaluate(()=>window.__gcaQaData.voice.config.language),'fr');
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({views,locales:['fr','en'],runtimeLanguageSwitch:true,backendErrorTranslated:true,conversationLanguageUnchanged:true,errors,nativeNavigationExecuted:false},null,2));
}finally{await browser.close();}
