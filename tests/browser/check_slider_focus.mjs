// Native CSS/DOM geometry, not real Steam gamepad or hardware acceptance.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {writeFileSync} from 'node:fs';
import {showSettingsTab} from './settings_tabs_helper.mjs';
const {chromium}=createRequire(import.meta.url)('/Users/C/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const results=[];
const near=(a,b,msg)=>assert(Math.abs(a-b)<.8,`${msg}: ${a} vs ${b}`);
try{
 for(const [surface,url,widths] of [['settings',process.argv[2],[736,1280]],['quick',process.argv[3],[300,340,390]]]){
  const page=await browser.newPage(),errors=[];page.on('pageerror',error=>errors.push(String(error)));
  await page.goto(url);
  if(surface==='settings'){
   await page.locator('.gca-content').waitFor();
   const tabs=page.locator('[data-qa-tabs] [role=tab]');
   for(let i=0;i<await tabs.count();i++){await showSettingsTab(page,i);if(await page.getByRole('slider',{name:'Luminosité de jour',exact:true}).count())break;}
  }
  const slider=page.getByRole('slider',{name:surface==='settings'?'Luminosité de jour':'Luminosité',exact:true});
  await slider.waitFor();await slider.scrollIntoViewIfNeeded();
  const measure=()=>slider.evaluate(el=>{
   const s=window.__gcaQaNative.slider,child=key=>el.getElementsByClassName(s[key])[0];
   const row=el.closest('.gca-native-field,.gca-compact-slider'),box=node=>{const b=node.getBoundingClientRect();return{x:b.x,y:b.y,width:b.width,height:b.height,cx:b.x+b.width/2,cy:b.y+b.height/2,right:b.right};};
   const handle=child('SliderHandle'),track=child('SliderTrack'),style=getComputedStyle(handle),fill=getComputedStyle(track,'::before');
   return{handle:box(handle),track:box(track),row:box(row),sizing:style.boxSizing,
    border:parseFloat(style.borderLeftWidth),shadow:getComputedStyle(row).boxShadow,bg:getComputedStyle(row).backgroundColor,
    fillRight:box(track).x+parseFloat(fill.left)+parseFloat(fill.width)};
  });
  const clear=()=>slider.evaluate(el=>{
   document.activeElement?.blur();el.classList.remove('gpfocus','gpfocuswithin');
   el.closest('.gca-native-field,.gca-compact-slider').querySelectorAll('.gpfocus,.gpfocuswithin').forEach(n=>n.classList.remove('gpfocus','gpfocuswithin'));
  });
  for(const width of widths){
   await page.setViewportSize({width,height:900});await slider.scrollIntoViewIfNeeded();
   for(const value of[0,5,50,95,100]){
    await clear();await slider.evaluate((el,value)=>el.style.setProperty('--normalized-slider-value',String(value/100)),value);
    const base=await measure();assert.equal(base.shadow,'none');
    for(const focus of ['gpfocus','gpfocuswithin','keyboard','field']){
     await clear();
     if(focus==='keyboard')await slider.focus();
     else await slider.evaluate((el,focus)=>{const target=focus==='field'?el.closest('.gca-native-field,.gca-compact-slider').firstElementChild:el;target.classList.add(focus==='field'?'gpfocus':focus);},focus);
     await page.waitForTimeout(220);const next=await measure();
     if(surface==='settings')assert.notEqual(next.shadow,'none',`${surface} ${focus} must show an underline`);
     else assert.equal(next.shadow,'none','Quick panel must not have an underline');
     assert.equal(next.bg,'rgb(32, 44, 58)','Subtle focus background kept on both surfaces');
     assert.equal(next.sizing,'content-box');near(next.handle.width,next.handle.height,'Round native handle');
     near(next.handle.cy,next.track.cy,'Handle remains vertically centred');
     near(next.handle.cx,base.handle.cx,'No horizontal focus shift');near(next.handle.cy,base.handle.cy,'No vertical focus shift');
     near(next.row.height,base.row.height,'Underline does not reflow row');
     assert(next.fillRight>=next.handle.x+next.border-.8&&next.fillRight<=next.handle.right-next.border+.8,'Fill still intersects handle');
     if(focus==='gpfocus')near(next.handle.width,30,'Native focus growth kept');
     results.push({surface,width,value,focus,...next});
    }
   }
  }
  // Focus must be a read-only paint operation, even when disabled.
  await clear();await slider.evaluate(el=>{el.classList.add('gpfocus',window.__gcaQaNative.slider.Disabled);el.setAttribute('aria-disabled','true');});
  assert.equal((await measure()).shadow,'none','Disabled slider has no enabled cue');
  await slider.evaluate(el=>{el.classList.remove(window.__gcaQaNative.slider.Disabled);el.removeAttribute('aria-disabled');});
  // Negative control proves settings-wide border-box reproduces the defect.
  if(surface==='settings'){
   await clear();await slider.evaluate(el=>el.classList.add('gpfocus'));
   const bad=await page.addStyleTag({content:'#gca-settings-root .gca-native-field .SliderHandle{box-sizing:border-box!important}'});
   await page.waitForTimeout(220);
   const broken=await measure();assert(Math.abs(broken.handle.cy-broken.track.cy)>2,`Old sizing must fail the centre check: ${JSON.stringify(broken)}`);
   await bad.evaluate(el=>el.remove());near((await measure()).handle.cy,(await measure()).track.cy,'Fix restored');
  }
  assert.deepEqual(await page.evaluate(()=>window.__gcaQaCalls.filter(c=>/^(set_|start_|preview_|prepare_|configure_)/.test(c.name))),[],'Focus performs no write');
  assert.deepEqual(errors,[]);
  await clear();await slider.evaluate(el=>{el.style.removeProperty('--normalized-slider-value');
   const value=Number(el.getAttribute('aria-valuenow')),min=Number(el.getAttribute('aria-valuemin')),max=Number(el.getAttribute('aria-valuemax'));
   el.style.setProperty('--normalized-slider-value',String((value-min)/(max-min)));el.classList.add('gpfocus');});
  await page.waitForTimeout(220);
  await slider.scrollIntoViewIfNeeded();await page.screenshot({path:`/private/tmp/gca-lab181-${surface}-slider.png`});
  await page.close();
 }
 writeFileSync('/private/tmp/gca-lab181-slider-results.json',JSON.stringify(results,null,2));
 console.log(`PASS ${results.length} slider focus/geometry cases; both surfaces, 0/5/50/95/100%, field/gamepad/DOM focus, disabled, no reflow or writes; old border-box defect reproduced.`);
}finally{await browser.close();}
