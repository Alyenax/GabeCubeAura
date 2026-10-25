import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const {chromium}=createRequire(import.meta.url)(process.env.GCA_PLAYWRIGHT||'/Users/C/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const browser=await chromium.launch({headless:true,executablePath:process.env.GCA_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[];
page.on('pageerror',e=>errors.push(String(e)));
const choose=async(name,option)=>{await page.getByRole('combobox',{name,exact:true}).click();await page.getByRole('option',{name:option,exact:true}).click();};
const data=()=>page.evaluate(()=>window.__gcaQaData);
const redraw=patch=>page.evaluate(patch=>{Object.assign(window.__gcaQaData.status,patch);window.__gcaQuickRefresh();},patch);
try{
  await page.goto(process.argv[2]);await page.locator('#gca-compact-root img').waitFor();
  await page.waitForFunction(()=>document.querySelector('#gca-compact-root img')?.naturalWidth>0);
  assert.equal(await page.locator('.gca-compact-led i').count(),17);
  assert.deepEqual((await page.evaluate(()=>window.__gcaQaCalls)).filter(c=>!c.name.startsWith('get_')&&c.name!=='report_runtime_diagnostic'),[],'Opening performs only reads and a diagnostic marker');
  await page.screenshot({path:'/private/tmp/gca-lab167-quick-fr.png',fullPage:true});
  const slider=page.getByRole('slider',{name:'Luminosité',exact:true});await slider.focus();
  await page.keyboard.press('ArrowRight');await page.keyboard.press('ArrowRight');await page.waitForTimeout(350);
  const brightness=(await data()).status.light_bar_day_brightness;
  const mounts=()=>page.evaluate(()=>window.__gcaQaCalls.filter(c=>c.name==='report_runtime_diagnostic'&&c.args[2]==='panel:mounted').length);
  const initialMounts=await mounts();
  const beforeCancel=await page.evaluate(()=>window.__gcaQaCalls.filter(c=>c.name==='set_setting').length);
  await page.getByRole('combobox',{name:'Ambiance',exact:true}).focus();await page.keyboard.press('Enter');
  await page.getByRole('listbox',{name:'Ambiance',exact:true}).waitFor();
  assert.equal(await page.getByRole('listbox').locator(':focus').count(),1,'Opening focuses the saved native option');
  await redraw({});
  assert.equal(await page.getByRole('listbox').count(),1,'Polling does not close the list');
  await page.keyboard.press('Escape');
  assert.equal(await page.getByRole('listbox').count(),0,'B cancels inline selection');
  assert.equal(await page.getByRole('combobox',{name:'Ambiance',exact:true}).evaluate(el=>el===document.activeElement),true,'B returns to trigger');
  assert.equal(await page.evaluate(()=>window.__gcaQaCalls.filter(c=>c.name==='set_setting').length),beforeCancel,'Cancel does not save');
  for(const [label,preset] of [['Personnalisé','custom'],['Modéré','moderate'],['Atmosphère','atmosphere'],['Signaux','signals'],['Immersif','immersive'],['Immersif+','immersive-plus'],['Festif','festive']]){
    await choose('Ambiance',label);
    assert.equal((await data()).status.display_preset,preset);
    await redraw({});
    assert.equal((await page.getByRole('combobox',{name:'Ambiance',exact:true}).textContent()).trim().replace(/▾$/,''),label,'Chosen ambience survives refresh');
    assert.equal((await data()).status.light_bar_day_brightness,brightness);
    assert((await page.locator('.gca-preset-summary').textContent()).length>10);
  }
  await page.getByRole('button',{name:'Faire taire',exact:true}).click();
  assert.equal((await data()).voice.config.enabled,true,'Silence keeps enabled');
  assert.equal((await data()).voice.config.wake_enabled,true,'Silence keeps wake enabled');
  await page.getByRole('checkbox',{name:'Micro de l’assistant'}).click();assert.equal((await data()).voice.config.enabled,false);
  await page.getByRole('checkbox',{name:'Micro de l’assistant'}).click();assert.equal((await data()).voice.config.enabled,true);
  await page.getByRole('button',{name:'Démarrer…',exact:true}).click();
  assert.equal(await page.locator('.gca-compact-editor').count(),1,'Timer configuration is in the actual panel');
  assert.equal(await page.getByRole('dialog').count(),0,'No floating modal is required');
  await page.getByRole('textbox',{name:'Durée en minutes'}).fill('0');
  assert.equal(await page.getByRole('button',{name:'Démarrer',exact:true}).isDisabled(),true);
  assert.equal(await page.locator('.gca-compact-editor').count(),1,'Invalid input keeps the editor available');
  await page.getByRole('button',{name:'1 h',exact:true}).click();
  assert.equal(await page.getByRole('textbox',{name:'Durée en minutes'}).inputValue(),'60');
  await choose('À la fin','Mettre la console en veille');
  await redraw({});
  assert.match(await page.getByRole('combobox',{name:'À la fin',exact:true}).textContent(),/Mettre la console en veille/,'Timer choice survives panel polling');
  await page.getByRole('button',{name:'Annuler',exact:true}).click();
  assert.equal((await page.evaluate(()=>window.__gcaQaCalls.filter(c=>c.name==='start_free_timer'))).length,0);
  await page.getByRole('button',{name:'Démarrer…',exact:true}).click();
  await choose('À la fin','Éteindre la console');
  await page.evaluate(()=>{const prior=window.__gcaQaRpc;window.__gcaFailTimer=true;window.__gcaQaRpc=async(name,args)=>{
    if(name==='start_free_timer'&&window.__gcaFailTimer){window.__gcaFailTimer=false;throw new Error('Simulated start failure');}
    return prior(name,args);
  };});
  await page.getByRole('button',{name:'Confirmer et démarrer',exact:true}).click();
  await page.getByRole('alert').waitFor();
  assert.equal(await page.locator('.gca-compact-editor').count(),1,'Failed RPC leaves the choices available');
  assert.equal((await data()).status.personal_timer.active,false);
  await page.screenshot({path:'/private/tmp/gca-lab170-timer-retry.png',fullPage:true});
  await page.getByRole('button',{name:'Confirmer et démarrer',exact:true}).click();
  await page.getByRole('button',{name:'+15 min',exact:true}).waitFor();
  assert.equal((await data()).status.timer_end_action.action,'shutdown');
  const before=(await data()).status.personal_timer.remaining_seconds;
  await page.getByRole('button',{name:'+15 min',exact:true}).click();assert.equal((await data()).status.personal_timer.remaining_seconds,before+900);
  await page.getByRole('button',{name:'Arrêter',exact:true}).click();assert.equal((await data()).status.timer_end_action.phase,'cancelled');
  await choose('Écran JSAUX','Éteint');assert.equal((await data()).status.faceplate.powered,false);
  await choose('Écran JSAUX','Météo');assert.equal((await data()).status.faceplate.routing.routes.game,'weather');assert.equal((await data()).status.faceplate.powered,true);
  const jsaux=page.getByRole('slider',{name:'Luminosité JSAUX',exact:true});
  const routes=JSON.stringify((await data()).status.faceplate.routing.routes),preset=(await data()).status.display_preset;
  const faceBefore=await page.evaluate(()=>window.__gcaQaCalls.filter(c=>c.name==='set_setting'&&c.args[0]==='faceplate_brightness').length);
  await jsaux.focus();for(let i=0;i<3;i++)await page.keyboard.press('ArrowLeft');
  await page.waitForTimeout(500);
  assert.equal((await data()).status.faceplate_brightness,85);
  assert.equal(await page.evaluate(()=>window.__gcaQaCalls.filter(c=>c.name==='set_setting'&&c.args[0]==='faceplate_brightness').length),faceBefore+1,'Slider changes are coalesced');
  assert.equal((await data()).status.light_bar_day_brightness,brightness);
  assert.equal(JSON.stringify((await data()).status.faceplate.routing.routes),routes);
  assert.equal((await data()).status.display_preset,preset);
  assert(await jsaux.evaluate(el=>el.closest('.gca-compact-slider').getBoundingClientRect().top>el.closest('section').querySelector('[role=combobox]').getBoundingClientRect().bottom),'JSAUX brightness sits below screen choice');
  assert.equal(await jsaux.evaluate(el=>getComputedStyle(el.closest('.gca-compact-slider')).boxShadow),'none','No underline in quick panel');
  for(const language of['fr','en']){
    await page.evaluate(language=>window.__gcaQuickLanguage(language),language);
    for(const width of[300,340,390,736]){
      await page.setViewportSize({width,height:900});
      const layout=await page.locator('#gca-compact-root').evaluate(root=>{
        const box=root.getBoundingClientRect();
        return [...root.querySelectorAll('.DialogButton,[role=slider],[role=checkbox],img')].filter(el=>{const b=el.getBoundingClientRect();return b.width>0&&(b.left<box.left-1||b.right>box.right+1);}).map(el=>({tag:el.tagName,text:el.textContent}));
      });assert.deepEqual(layout,[],`Contained at ${width}/${language}`);
      assert(await page.locator('.gca-compact-led').evaluate(el=>getComputedStyle(el).gridTemplateColumns.split(' ').length===17));
    }
  }
  await page.setViewportSize({width:1280,height:900});
  await page.screenshot({path:'/private/tmp/gca-lab167-quick-en.png',fullPage:true});
  await redraw({game:{appid:0,title:''}});assert.equal(await page.locator('#gca-compact-root img').count(),0);
  await choose('JSAUX screen','Artwork Dashboard');assert.equal((await data()).status.faceplate_dashboard_home_source,'artwork');
  await choose('JSAUX screen','Dashboard');assert.equal((await data()).status.faceplate_dashboard_home_source,'weather');
  await page.evaluate(()=>{window.__gcaQaData.status.faceplate.available=false;window.__gcaQaData.status.faceplate.recently_detected=false;window.__gcaQuickRefresh();});
  await page.waitForFunction(()=>!document.querySelector('.gca-compact-faceplate'));
  assert.equal(await page.getByRole('combobox',{name:'JSAUX screen'}).count(),0);
  assert.equal(await page.getByRole('slider',{name:'JSAUX brightness',exact:true}).count(),0,'No JSAUX brightness without detected/recent hardware');
  const markers=await page.evaluate(()=>window.__gcaQaCalls.filter(c=>c.name==='report_runtime_diagnostic'&&c.args[0]==='quick_panel_ui').map(c=>c.args[2]));
  assert.equal(await mounts(),initialMounts,'No menu selection remounts the panel or loses its timer draft');
  for(const expected of ['panel:mounted','ambience:opening','ambience:opened','ambience:selected:atmosphere','ambience:saved:atmosphere','timer:opened','timer:cancelled','timer:failed:shutdown','timer:saved:shutdown','faceplate:opened','faceplate:saved:weather'])assert(markers.includes(expected),expected);
  assert.deepEqual(errors,[]);console.log('PASS: actual compact React component + Valve CSS data; FR/EN, 8 sizes, read-only opening, bounded artwork, 17 LEDs, native controls, timer consent/cancel/extend/stop, mic/silence, JSAUX routing. No hardware or real power action.');
}finally{await browser.close();}
