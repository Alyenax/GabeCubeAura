// Production SimpleSettings + installed CSS. Browser navigation doubles and a
// lost-transition-completion fault, not a physical CEF/controller acceptance.
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import assert from 'node:assert/strict';
const root=process.cwd(),require=createRequire(path.join(root,'../gabecubeaura-interface-preview/interface-preview/package.json'));
const {build}=require('esbuild'),{chromium}=require('playwright');
const reference=JSON.parse(readFileSync(process.env.GCA_QA_NATIVE_MAPS||'/private/tmp/decky-native-audit-20261022/native-maps.json','utf8'));
const m=reference.modules,native={field:m.dialog,sidebar:m.sidebar,tabs:m.tabs,slider:m.slider};
const css=readFileSync(path.join(reference.steamRoot,'css/library.css'),'utf8')+'\n'+readFileSync(path.join(reference.steamRoot,'css/sp.css'),'utf8');
const input=path.join(root,'tests/browser/settings_shoulders_fixture.tsx'),shim=path.join(root,'tests/browser/settings_shoulders_shim.tsx');
async function bundle(legacy){return(await build({entryPoints:[input],bundle:true,write:false,jsx:'automatic',define:{'process.env.NODE_ENV':'"production"'},plugins:[{name:'isolated-native-scope',setup(b){
 b.onResolve({filter:/^react(?:\/.*)?$|^react-dom(?:\/.*)?$/},a=>({path:require.resolve(a.path)}));
 b.onResolve({filter:/^@decky\/ui$/},()=>({path:shim}));
 b.onResolve({filter:/^\.\/GabeAssistantPanel$/},()=>({path:'voice',namespace:'fixture'}));
 b.onLoad({filter:/.*/,namespace:'fixture'},()=>({contents:'export const GabeSettingsSession=({children})=>children;',loader:'tsx'}));
 if(legacy)b.onLoad({filter:/\/src\/components\/SimpleSettings\.tsx$/},a=>({contents:execFileSync('git',['show','v1.4.1-lab.197:src/components/SimpleSettings.tsx'],{encoding:'utf8'}),loader:'tsx',resolveDir:path.dirname(a.path)}));
 }}]})).outputFiles[0].text;}
const bundles={legacy:await bundle(true),fixed:await bundle(false)};
const server=http.createServer((req,res)=>{if(req.url.endsWith('.js')){res.setHeader('Content-Type','text/javascript');res.end(bundles[req.url.includes('legacy')?'legacy':'fixed']);return;}
 res.setHeader('Content-Type','text/html');res.end(`<!doctype html><html class="GamepadMode GamepadUI"><meta charset="utf-8"><style>${css}</style><style>html,body,#app{height:100%;margin:0}body{background:#1a1c21;color:#dcdedf;font:16px Arial}button{font:inherit;padding:12px 24px}h2,p{margin:16px}</style><div id="app"></div><div id="modals"></div><script>window.__gcaQaNative=${JSON.stringify(native)};</script><script src="/${req.url.includes('legacy')?'legacy':'fixed'}.js"></script></html>`);});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const out=path.join(root,'out/ui/shoulders198');mkdirSync(out,{recursive:true});
try{
 const page=await browser.newPage({viewport:{width:1280,height:800}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 const start=async mode=>{await page.goto(`http://127.0.0.1:${server.address().port}/${mode}`);await page.locator('[data-qa-category="display"]').focus();};
 await start('legacy');await page.keyboard.press('e');await page.waitForTimeout(30);await page.keyboard.press('e');await page.waitForTimeout(30);
 const baseline=await page.locator('[data-qa-tab-pane]').count();assert(baseline>1,'Legacy must reproduce retained outgoing panels under completion loss');
 await page.screenshot({path:path.join(out,'before-lost-completion.png')});
 await start('fixed');let expected='daily';const ids=['daily','effects','sync','profiles'];
 const check=async()=>{
  assert.equal(await page.locator('[data-qa-native-scope]').count(),1);assert.equal(await page.locator('[data-qa-tab-pane]').count(),1);
  assert.equal(await page.locator('[data-qa-outgoing]').count(),0);assert.equal(await page.evaluate(()=>window.__qa.live.size),1);
  assert.equal(await page.locator('[data-qa-tab-pane]').getAttribute('data-qa-tab-pane'),expected);
  const box=await page.locator('[data-qa-tab-pane]').boundingBox(),owner=await page.locator('.gca-category-page').boundingBox();assert(box.width>800&&Math.abs(box.x-owner.x)<1&&Math.abs(box.width-owner.width)<1,JSON.stringify({box,owner}));
 };
 for(let i=0;i<120;i++){
  const direction=i%8<4?1:-1;expected=ids[Math.max(0,Math.min(3,ids.indexOf(expected)+direction))];
  await page.keyboard.press(direction>0?'e':'q');await page.waitForTimeout(20);await check();
 }
 assert(await page.locator('[data-qa-category="display"]').evaluate(el=>el===document.activeElement),'Sidebar shoulders must not steal focus');
 await page.locator('[data-qa-tab-pane] button').first().focus();
 const retired=await page.evaluate(()=>{window.__qa.retired=window.__qa.current.onShowTab;return window.__qa.current.active;});
 expected=ids[Math.min(3,ids.indexOf(expected)+1)];await page.keyboard.press('e');await page.waitForTimeout(120);await check();
 await page.evaluate(()=>window.__qa.retired('profiles'));await page.waitForTimeout(80);await check();
 assert(await page.locator('[data-qa-tab-pane]').evaluate(el=>el.contains(document.activeElement)),'Content entry stays in the current native lifetime');
 await page.locator('[data-qa-category="weather"]').focus();await page.keyboard.press('e');await page.waitForTimeout(300);
 assert.equal(await page.locator('[data-qa-tab-pane]').getAttribute('data-qa-tab-pane'),'animations');
 assert(await page.locator('[data-qa-category="weather"]').evaluate(el=>el===document.activeElement),'Actual hashed sidebar has no PageListColumn shortcut');
 await page.screenshot({path:path.join(out,'after-rapid-shoulders.png')});
 assert.deepEqual(errors,[]);
 const report={baselineRetainedPanels:baseline,rapidShoulderInputs:120,currentNativeScopes:1,retiredCallbacksIgnored:true,sidebarFocusPreserved:true,contentFocusPreserved:true,errors,nativeCEFExecuted:false,fault:'Lost transition completion / native 10s outgoing lifetime',cssSHA256:reference.sha256};
 writeFileSync(path.join(out,'validation.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
}finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
