import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import ts from 'typescript';
import vm from 'node:vm';

const read=(file:string)=>readFileSync(new URL('../../'+file,import.meta.url),'utf8');
test('slider focus skin supports Steam/DOM focus, excludes disabled and never changes geometry',()=>{
 const src=read('src/slider_focus_style.ts').replace(/^import.*\n/,'');
 const context=vm.createContext({exports:{},gamepadSliderClasses:{Disabled:'new_disabled build_two'}});
 vm.runInContext(ts.transpileModule(src,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,context);
 const css=context.exports.sliderFocusCSS('#scope .slider','#8fc9f2','#202c3a');
 assert.match(css,/:focus-within/);assert.match(css,/:has\(\.gpfocus,\.gpfocuswithin,:focus-visible\)/);
 assert.match(css,/\[class~="new_disabled"\]\[class~="build_two"\]/);
 assert.match(css,/aria-disabled="true"/);assert.match(css,/:disabled/);
 assert.match(css,/box-shadow:inset 0 -2px 0 #8fc9f2/);
 assert.doesNotMatch(css,/width:|height:|padding:|margin:|transform:|border:/);
 const quick=context.exports.sliderFocusCSS('#quick .slider','#8fc9f2','#202c3a',false);
 assert.match(quick,/background:#202c3a!important;box-shadow:none!important/);
 assert.doesNotMatch(quick,/inset 0 -2px/);
});
test('both active surfaces now retain Steam slider focus and native sizing',()=>{
 const full=read('src/settings_theme.ts'),quick=read('src/components/compact_quick_style.ts');
 for(const css of [full,quick])assert.doesNotMatch(css,/sliderFocusCSS|SliderHandle|box-sizing:content-box|ToggleRail|ToggleSwitch/);
 assert.doesNotMatch(full,/#gca-settings-root \*/,'No blanket sizing reset of Steam internals');
});
