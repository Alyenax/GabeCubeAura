// Isolated CSS-event contract. No Valve JavaScript or controller runtime runs.
// Usage: node tests/browser/check_native_transitions.mjs http://127.0.0.1:PORT/
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const require=createRequire(process.env.GCA_QA_PLAYWRIGHT||'/Users/C/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json');
const {chromium}=require('playwright');
const url=process.argv[2];assert.match(url||'',/^http:\/\/127\.0\.0\.1:\d+\/$/);
const browser=await chromium.launch({headless:true,executablePath:process.env.GCA_QA_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
try{
  const page=await browser.newPage({viewport:{width:1280,height:800}});
  await page.goto(url);await page.locator('#gca-settings-root').waitFor();
  const rows=await page.evaluate(async()=>{
    const native=window.__gcaQaNative,root=document.getElementById('gca-settings-root');
    if(!native.transition?.TransitionGroup||!native.transition?.ContentWrapper)throw new Error('Missing Valve transition CSS registry');
    const frame=()=>new Promise(resolve=>requestAnimationFrame(resolve));
    async function inspect(kind,obsolete=false){
      const map=native[kind],group=document.createElement('div'),node=document.createElement('div');
      const direction=kind==='tabs'?map.Right:map.Down;
      if(!map.Exit||!map.ExitActive||!direction)throw new Error('Missing '+kind+' exit classes');
      group.className=native.transition.TransitionGroup+' '+direction;
      group.style.cssText='position:absolute;left:0;top:0;width:200px;height:60px;pointer-events:none;z-index:-1';
      node.className=native.transition.ContentWrapper+' '+map.ContentTransition+' '+map.Exit;
      group.append(node);root.append(group);
      let regression;
      if(obsolete){regression=document.createElement('style');regression.textContent='#gca-settings-root [data-qa-transition-probe]{transition:none!important;opacity:1!important}';document.head.append(regression);node.style.setProperty('visibility','visible','important');}
      node.dataset.qaTransitionProbe='true';
      const events=[];
      for(const name of ['transitionrun','transitionend','transitioncancel'])node.addEventListener(name,event=>{if(event.target===node)events.push([name,event.propertyName]);});
      const before=getComputedStyle(node).opacity,visibilityBefore=getComputedStyle(node).visibility;
      void node.offsetWidth;await frame();await frame();
      node.classList.add(map.ExitActive);
      const style=getComputedStyle(node),durations=style.transitionDuration.split(',').map(value=>parseFloat(value)*(value.trim().endsWith('ms')?1:1000)),delays=style.transitionDelay.split(',').map(value=>parseFloat(value));
      await new Promise(resolve=>setTimeout(resolve,140));
      const result={kind,obsolete,before,visibilityBefore,visibilityAfter:getComputedStyle(node).visibility,after:getComputedStyle(node).opacity,properties:style.transitionProperty,durations,delays,events};
      group.remove();regression?.remove();return result;
    }
    return [await inspect('tabs'),await inspect('sidebar'),await inspect('tabs',true)];
  });
  for(const row of rows.filter(item=>!item.obsolete)){
    assert.equal(row.before,'1',JSON.stringify(row));assert.equal(row.after,'0',JSON.stringify(row));
    assert.equal(row.visibilityBefore,'hidden',JSON.stringify(row));assert.equal(row.visibilityAfter,'hidden',JSON.stringify(row));
    assert(row.durations.some(value=>value>0&&value<=100),JSON.stringify(row));
    assert(row.delays.every(value=>value===0),JSON.stringify(row));
    assert(row.events.some(([name])=>name==='transitionrun'),JSON.stringify(row));
    assert(row.events.some(([name])=>name==='transitionend'),JSON.stringify(row));
  }
  const old=rows.find(item=>item.obsolete);
  assert.equal(old.after,'1');assert.equal(old.properties,'none');
  assert.equal(old.visibilityAfter,'visible');
  assert(!old.events.some(([name])=>name==='transitionend'));
  console.log(JSON.stringify({contract:'Valve exit CSS must emit completion events',nativeNavigationExecuted:false,rows},null,2));
}finally{await browser.close();}
