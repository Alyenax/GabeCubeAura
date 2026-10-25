// Browser fixture evidence only, not SteamOS/controller/optical acceptance.
import {createRequire} from 'node:module';
import {mkdirSync} from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
const require=createRequire(path.join(process.cwd(),'../gabecubeaura-interface-preview/interface-preview/package.json'));
const {chromium}=require('playwright');
const browser=await chromium.launch({headless:true});
const page=await browser.newPage();
const errors=[];page.on('pageerror',error=>errors.push(error.message));
const output=path.join(process.cwd(),'output/screen-sync-wiring');mkdirSync(output,{recursive:true});
try{
  await page.goto(process.argv[2]);
  for(const language of ['fr','en']){
    await page.evaluate(language=>window.__gcaQuickLanguage(language),language);
    const label=language==='fr'?'Barre lumineuse en jeu':'In-game light bar';
    const extension=language==='fr'?'Prolongement de l’image faceplate':'Faceplate image extension';
    for(const width of [300,340,390]){
      await page.setViewportSize({width,height:1100});
      const choice=page.getByRole('combobox',{name:label,exact:true});
      await choice.click();
      await page.getByRole('option',{name:extension,exact:true}).click();
      await page.waitForFunction(()=>window.__gcaQaCalls.some(call=>call.name==='set_game_display'&&call.args[0]===292030&&call.args[1]==='faceplate_extension'));
      await choice.scrollIntoViewIfNeeded();
      const box=await choice.boundingBox();assert(box&&box.x>=0&&box.x+box.width<=width+1,`${language}/${width}: selector overflow`);
      await page.screenshot({path:path.join(output,`quick-${language}-${width}.png`),fullPage:true});
      await page.evaluate(()=>{window.__gcaQaData.status.faceplate.available=false;window.__gcaQuickRefresh();});
      await choice.click();
      assert.equal(await page.getByRole('option',{name:extension,exact:true}).count(),0);
      await page.getByRole('option',{name:language==='fr'?'Synchronisation écran':'Screen Sync',exact:true}).click();
      await page.evaluate(()=>{window.__gcaQaData.status.faceplate.available=true;window.__gcaQuickRefresh();});
    }
  }
  await page.evaluate(()=>{window.__gcaQaData.status.game.appid=0;window.__gcaQuickRefresh();});
  await page.waitForFunction(()=>![...document.querySelectorAll('[role=combobox]')].some(el=>el.getAttribute('aria-label')==='In-game light bar'));
  assert.deepEqual(errors,[]);
  console.log('PASS: FR/EN, 300/340/390px, per-game RPC, disconnect/reconnect filtering, Home hidden, no browser exceptions.');
}finally{await browser.close();}
