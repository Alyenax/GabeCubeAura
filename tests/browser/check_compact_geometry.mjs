// Render actual CompactQuickPanel with reference Valve CSS and native-shaped
// controls. This is geometry evidence, not Steam gamepad-engine/device proof.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {writeFileSync} from 'node:fs';
const {chromium}=createRequire(import.meta.url)(process.env.GCA_PLAYWRIGHT||'/Users/C/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const browser=await chromium.launch({headless:true,executablePath:process.env.GCA_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const page=await browser.newPage({viewport:{width:340,height:1050}}),errors=[],measurements=[];
page.on('pageerror',error=>errors.push(String(error)));
const near=(actual,expected,message,tolerance=.8)=>assert(Math.abs(actual-expected)<=tolerance,`${message}: ${actual} vs ${expected}`);
const redraw=async patch=>{await page.evaluate(patch=>{Object.assign(window.__gcaQaData.status,patch);window.__gcaQuickRefresh();},patch);};
const focusState=async(locator,focused)=>{
  await locator.evaluate((element,focused)=>{element.classList.toggle('gpfocus',focused);if(focused)element.focus();else element.blur();},focused);
  // Settle Valve's focus scale animation and toggle movement before measuring.
  await page.waitForTimeout(260);
};
const toggleMeasure=locator=>locator.evaluate(element=>{
  const f=window.__gcaQaNative.field,child=key=>element.getElementsByClassName(f[key])[0];
  const box=node=>{const b=node.getBoundingClientRect(),s=getComputedStyle(node),left=parseFloat(s.borderLeftWidth)||0,right=parseFloat(s.borderRightWidth)||0,top=parseFloat(s.borderTopWidth)||0,bottom=parseFloat(s.borderBottomWidth)||0;return{x:b.x,y:b.y,width:b.width,height:b.height,right:b.right,bottom:b.bottom,cx:b.x+b.width/2,cy:b.y+b.height/2,contentLeft:b.left+left,contentRight:b.right-right,contentTop:b.top+top,contentBottom:b.bottom-bottom};};
  return{checked:element.getAttribute('aria-checked'),root:box(element),rail:box(child('ToggleRail')),knob:box(child('ToggleSwitch'))};
});
const sliderMeasure=locator=>locator.evaluate(element=>{
  const s=window.__gcaQaNative.slider,child=key=>element.getElementsByClassName(s[key])[0],box=node=>{const b=node.getBoundingClientRect();return{x:b.x,y:b.y,width:b.width,height:b.height,right:b.right,bottom:b.bottom,cx:b.x+b.width/2,cy:b.y+b.height/2};};
  const track=child('SliderTrack'),handle=child('SliderHandle'),fill=getComputedStyle(track,'::before'),trackBox=box(track),knob=box(handle),style=getComputedStyle(handle);
  const fillLeft=trackBox.x+parseFloat(fill.left),fillRight=fillLeft+parseFloat(fill.width),contentLeft=knob.x+(parseFloat(style.borderLeftWidth)||0),contentRight=knob.right-(parseFloat(style.borderRightWidth)||0);
  return{value:Number(element.getAttribute('aria-valuenow')),track:trackBox,knob,contentLeft,contentRight,fillLeft,fillRight,fillToKnobCenter:fillRight-knob.cx,fillHeight:parseFloat(fill.height),nativeHandleWidth:getComputedStyle(child('SliderControl')).getPropertyValue('--slider-handle-width').trim()};
});
try{
  await page.goto(process.argv[2]||'http://127.0.0.1:63085/');
  await page.locator('#gca-compact-root img').waitFor();
  await page.waitForFunction(()=>document.querySelector('#gca-compact-root img')?.naturalWidth>0);
  for(const language of['fr','en']){
    await page.evaluate(language=>window.__gcaQuickLanguage(language),language);
    for(const width of[300,340,390]){
      await page.setViewportSize({width,height:1050});
      const label=language==='fr'?'Luminosité':'Brightness',slider=page.getByRole('slider',{name:label,exact:true});
      const timer=await page.locator('.gca-compact-timer .gca-compact-line').evaluate(element=>{
        const label=element.querySelector('span').getBoundingClientRect(),button=element.querySelector('button').getBoundingClientRect();
        return{label:{left:label.left,right:label.right,top:label.top,bottom:label.bottom},button:{left:button.left,right:button.right,top:button.top,bottom:button.bottom},gap:button.left-label.right};
      });
      assert(timer.gap>=11,`Timer label/button gap at ${language}/${width}: ${timer.gap}`);
      const toggleNames=language==='fr'?['Éclairage','Micro de l’assistant']:['Lighting','Assistant microphone'];
      for(const name of toggleNames){
        const toggle=page.getByRole('checkbox',{name,exact:true});
        for(const checked of[false,true]){
          if((await toggle.getAttribute('aria-checked'))!==String(checked))await toggle.click();
          await page.waitForFunction(({name,checked})=>[...document.querySelectorAll('[role=checkbox]')].some(el=>el.getAttribute('aria-label')===name&&el.getAttribute('aria-checked')===String(checked)),{name,checked});
          for(const focused of[false,true]){
            await focusState(toggle,focused);const m=await toggleMeasure(toggle);
            near(m.rail.cy,m.knob.cy,`Toggle vertically centred ${language}/${width}/${name}/${checked}/${focused}`);
            assert(m.knob.contentLeft>=m.rail.x-.8&&m.knob.contentRight<=m.rail.right+.8,'Toggle knob content remains inside rail (focus border excluded)');
            assert(m.knob.contentTop>=m.rail.y-.8&&m.knob.contentBottom<=m.rail.bottom+.8,'Toggle knob vertically inside rail');
            near(m.root.width,38,'Native toggle width');near(m.root.height,22,'Native toggle height');
            measurements.push({language,width,kind:'toggle',name,checked,focused,...m});
          }
          await focusState(toggle,false);
        }
      }
      for(const value of[0,5,50,95,100]){
        await redraw({light_bar_day_brightness:Math.round(value/100*255)});
        await page.waitForFunction(value=>document.querySelector('[role=slider]')?.getAttribute('aria-valuenow')===String(value),value);
        for(const focused of[false,true]){
          await focusState(slider,focused);const m=await sliderMeasure(slider);
          near(m.track.cy,m.knob.cy,`Slider vertically centred ${language}/${width}/${value}/${focused}`);
          near(m.knob.height,focused?30:24,'Native slider height plus focus border');
          assert(m.fillRight>=m.contentLeft-.8&&m.fillRight<=m.contentRight+.8,`No fill/thumb gap at ${language}/${width}/${value}/${focused}: ${JSON.stringify(m)}`);
          near(m.fillToKnobCenter,(value/100-.5)*24,'Expected native fill end under thumb, not always centre');
          assert(m.contentLeft>=m.track.x-.8&&m.contentRight<=m.track.right+.8,'Thumb content stays within track endpoints');
          measurements.push({language,width,kind:'slider',focused,...m});
        }
        await focusState(slider,false);
      }
      await redraw({light_bar_day_brightness:128});
      await page.waitForFunction(()=>document.querySelector('[role=slider]')?.getAttribute('aria-valuenow')==='50');
      await page.screenshot({path:`/private/tmp/gca-compact-geometry-${language}-${width}.png`,fullPage:true});
      measurements.push({language,width,kind:'timer',...timer});
    }
  }
  // Negative control: prove these checks detect the exact Lab167 sizing bug,
  // rather than merely accepting whichever geometry the current CSS produces.
  const regression=await page.addStyleTag({content:await page.evaluate(()=>{
    const f=window.__gcaQaNative.field,s=window.__gcaQaNative.slider,selector=classes=>classes.split(/\s+/).map(value=>'.'+CSS.escape(value)).join('');
    return`#gca-compact-root ${selector(f.ToggleRail)}{width:40px!important;height:23px!important;border-radius:14px!important} #gca-compact-root ${selector(f.ToggleSwitch)}{width:17px!important;height:17px!important;border-radius:50%!important} #gca-compact-root ${selector(s.SliderHandle)}{width:16px!important;height:16px!important}`;
  })});
  try{
    const toggle=await toggleMeasure(page.getByRole('checkbox',{name:'Lighting',exact:true}));
    const slider=await sliderMeasure(page.getByRole('slider',{name:'Brightness',exact:true}));
    assert(Math.abs(toggle.rail.cy-toggle.knob.cy)>2,'Negative control must catch Lab167 off-centre toggle');
    assert(Math.abs(slider.track.cy-slider.knob.cy)>3,'Negative control must catch Lab167 off-centre slider');
    measurements.push({kind:'negative-control',toggleCenterError:toggle.knob.cy-toggle.rail.cy,sliderCenterError:slider.knob.cy-slider.track.cy});
  }finally{await regression.evaluate(element=>element.remove());}
  near((await toggleMeasure(page.getByRole('checkbox',{name:'Lighting',exact:true}))).knob.height,22,'Negative CSS removed');
  assert.deepEqual(errors,[]);
  writeFileSync('/private/tmp/gca-compact-geometry-results.json',JSON.stringify({checks:measurements.length,measurements,note:'Native fill end intersects thumb; centre offset ranges -12..12 px intentionally. Focus borders excluded from content inclusion. No real Steam navigation/hardware.'},null,2));
  console.log(`PASS: ${measurements.length} geometry measurements; FR/EN × 300/340/390px; Timer non-overlap; both toggles off/on, unfocused/gpfocus; slider 0/5/50/95/100, unfocused/gpfocus; no fill/thumb gap. Negative control detects original Lab167 toggle/slider defects. Six screenshots and measured JSON in /private/tmp/gca-compact-geometry-*.`);
}finally{await browser.close();}
