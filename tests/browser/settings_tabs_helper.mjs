// Browser-only shoulder input double. Never select a header using a click.
export async function showSettingsTab(page,index){
 const tabs=page.locator('[data-qa-tabs] [role=tab]');
 let current=await tabs.evaluateAll(items=>items.findIndex(el=>el.getAttribute('aria-selected')==='true'));
 for(let step=0;current!==index&&step<12;step++){
  await page.keyboard.press(current<index?'e':'q');
  current=await tabs.evaluateAll(items=>items.findIndex(el=>el.getAttribute('aria-selected')==='true'));
 }
 if(current!==index)throw Error(`Shoulder navigation did not reach tab ${index}`);
 // Valve keeps a 100ms colour transition on native tab headers. Geometry and
 // colour assertions must observe its completed paint, not the old grey frame.
 await page.waitForTimeout(140);
}
