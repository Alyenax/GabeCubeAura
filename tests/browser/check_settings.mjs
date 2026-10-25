// DOM/CSS contract only. This does NOT execute Steam's controller navigation.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
import {showSettingsTab} from './settings_tabs_helper.mjs';
const require=createRequire(process.env.GCA_QA_PLAYWRIGHT||'/Users/C/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json');
const {chromium}=require('playwright');
const url=process.argv[2];assert.match(url||'',/^http:\/\/127\.0\.0\.1:\d+\/$/);
const browser=await chromium.launch({headless:true,executablePath:process.env.GCA_QA_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
try{
 const page=await browser.newPage({viewport:{width:1280,height:800}}),errors=[],consoleErrors=[];
 page.on('pageerror',e=>errors.push(String(e)));page.on('console',e=>{if(e.type()==='error')consoleErrors.push(e.text());});
 await page.goto(url);await page.locator('.gca-content').waitFor();
 const sidebar=page.locator('[data-qa-sidebar]>div:first-child [role=tab]');
 const categories=await sidebar.allTextContents();
 assert.deepEqual(categories,['Éclairage','Signaux lumineux','Météo','Assistant vocal','Faceplate JSAUX','Mises à jour','Avancé']);
 const tabs=()=>page.locator('[data-qa-tabs] [role=tab]');
 const audit=[];
 async function inspect(){
   return page.evaluate(()=>{
     const maps=window.__gcaQaNative;
     const sel=(key,map=maps.field)=>`[class~="${map[key]}"]`;
     const content=document.querySelector('.gca-content'),heading=document.querySelector('.gca-heading');
     const scroller=document.querySelector(sel('TabContentsScroll',maps.tabs));
     const tabHeader=document.querySelector(sel('TabHeaderRowWrapper',maps.tabs));
     const brand=document.querySelector('.gca-brand'),title=heading.querySelector('h1');
     const y=heading.getBoundingClientRect().y;
     content.querySelector('.gca-help').scrollIntoView({block:'nearest'});
     const controls=[...content.querySelectorAll('.gca-native-field')].flatMap(field=>{
       const kind=field.dataset.gcaControl;if(!['action','dropdown','slider'].includes(kind))return[];
       const right=field.querySelector(sel('FieldRightColumn')),inner=field.querySelector(sel('FieldChildrenInner'));
       const control=field.querySelector('.DialogButton,[role=combobox],[role=slider]');
       if(!right||!inner||!control)return[{kind,missing:true}];
       const r=right.getBoundingClientRect(),i=inner.getBoundingClientRect(),c=control.getBoundingClientRect();
       return[{kind,right:r.width,inner:i.width,width:c.width,height:c.height,x:c.x,end:c.right,fieldEnd:field.getBoundingClientRect().right}];
     });
     return{category:document.querySelector('.gca-heading h1').textContent,tab:content.dataset.gcaTab,
       controls,headingStayed:heading.getBoundingClientRect().y===y,headingY:y,
       outerScroll:[...document.querySelectorAll('#gca-settings-root,.gca-category-page,.gca-tabs-host')].every(el=>el.scrollTop===0),
       scrolled:scroller.scrollTop,scrollWidth:scroller.scrollWidth,clientWidth:scroller.clientWidth,
       compactHeading:Math.abs(brand.getBoundingClientRect().y+brand.getBoundingClientRect().height/2-title.getBoundingClientRect().y-title.getBoundingClientRect().height/2)<1&&parseFloat(getComputedStyle(title).fontSize)<=16,
       tabsRaised:Math.abs(tabHeader.getBoundingClientRect().top-heading.getBoundingClientRect().bottom)<1,
       separateScrollBounds:scroller.getBoundingClientRect().top>=tabHeader.getBoundingClientRect().bottom-.5,
       headerBounds:[tabHeader.getBoundingClientRect().top,tabHeader.getBoundingClientRect().bottom],scrollTopBound:scroller.getBoundingClientRect().top,
       headerOwnsPaint:tabHeader.contains(document.elementFromPoint(tabHeader.getBoundingClientRect().left+10,tabHeader.getBoundingClientRect().top+10)),
       flatFields:[...content.querySelectorAll(sel('Field'))].every(el=>getComputedStyle(el).backgroundColor==='rgba(0, 0, 0, 0)'),
       titles:[...content.querySelectorAll('.gca-section-title')].every(el=>getComputedStyle(el).textTransform==='none'),
       overflow:document.documentElement.scrollWidth>innerWidth};
   });
 }
 for(const width of[1280,1024,800,736]){
   await page.setViewportSize({width,height:800});
   for(let category=0;category<7;category++){
     await sidebar.nth(category).click();const count=await tabs().count();
     for(let tab=0;tab<count;tab++){
       await showSettingsTab(page,tab);await page.waitForTimeout(60);
       const row={width,...await inspect()};audit.push(row);
       assert(!row.overflow&&row.headingStayed&&row.outerScroll&&row.flatFields&&row.titles,JSON.stringify(row));
       assert(row.compactHeading&&row.tabsRaised&&row.separateScrollBounds&&row.headerOwnsPaint,JSON.stringify(row));
       assert(row.scrollWidth<=row.clientWidth+1,JSON.stringify(row));
       for(const control of row.controls){
         assert(!control.missing,JSON.stringify(row));assert(control.inner>=Math.min(200,width/3),JSON.stringify(row));
         // Native contextual Dropdown deliberately uses min-width:initial,
         // so short labels need not fill the entire 250px Field ancestor.
         // Keep the ancestor-width gate; detect narrow vertical controls and
         // escaped boundaries without pretending Dropdown is a full-row action.
         assert(control.width>=(control.kind==='action'?120:control.kind==='dropdown'?42:150),JSON.stringify(row));
         assert(control.height>=24&&control.height<100,JSON.stringify(row));
         assert(control.end<=control.fieldEnd+1,JSON.stringify(row));
       }
     }
   }
 }
 assert.equal(audit.length,100);await page.setViewportSize({width:1280,height:800});
 // This fixture checks boundary state only, not real Steam D-pad focus. The
 // latter must leave the first header using Steam's native parent graph.
 for(let category=0;category<7;category++){
   await sidebar.nth(category).click();const count=await tabs().count();
   await showSettingsTab(page,0);
   for(let press=0;press<count+3;press++)await page.keyboard.press('e');
   assert.equal(await tabs().last().getAttribute('aria-selected'),'true');
   for(let press=0;press<count+3;press++)await page.keyboard.press('q');
   assert.equal(await tabs().first().getAttribute('aria-selected'),'true');
 }
 for(const[category,tab,name]of[[0,0,'display'],[2,0,'weather'],[3,0,'voice'],[4,3,'maintenance']]){
   await sidebar.nth(category).click();await showSettingsTab(page,tab);
   await page.evaluate(()=>document.querySelector(`.${window.__gcaQaNative.tabs.TabContentsScroll}`).scrollTop=0);
   await page.screenshot({path:`/private/tmp/gca-lab163-${name}-steam-css.png`});
 }
 await sidebar.nth(2).click();await showSettingsTab(page,0);
 // The old bad inner clamp must reproduce a measurable regression in the
 // real right-column + icon + inner wrapper hierarchy.
 const regression=await page.evaluate(async()=>{
   const field=document.querySelector('[data-gca-control=action]'),f=window.__gcaQaNative.field;
   const inner=field.querySelector(`.${f.FieldChildrenInner}`),before=inner.getBoundingClientRect().width;
   const style=document.createElement('style');style.textContent=await(await fetch('/baseline.css')).text();document.body.append(style);
   const after=inner.getBoundingClientRect().width;style.remove();return{before,after};
 });
 assert(regression.before>=200&&regression.after<regression.before*.75,JSON.stringify(regression));
 await page.getByRole('button',{name:'Aide sur ces réglages',exact:true}).click();await page.getByRole('dialog').waitFor();
 await page.getByRole('button',{name:'Fermer',exact:true}).click();
 const writes=await page.evaluate(()=>window.__gcaQaCalls.filter(call=>/^(set_|configure_|prepare_|activate_|start_|preview_|trigger_)/.test(call.name)));
 assert.deepEqual(writes,[],'navigation alone must not act on hardware or settings');assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors,[]);
 console.log(JSON.stringify({categories,views:audit.length,widths:[1280,1024,800,736],valveCSS:true,nativeNavigationExecuted:false,
   regression,boundedShoulders:true,fixedHeading:audit.every(r=>r.headingStayed&&r.outerScroll),navigationWrites:writes.length,errors,consoleErrors},null,2));
}finally{await browser.close();}
