import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import {createElement} from 'react';
import {translate} from '../../src/i18n';
const source=readFileSync(new URL('../../src/components/ArtworkLogoScale.tsx',import.meta.url),'utf8');
const context=vm.createContext({React:{createElement},PanelSectionRow:'row',SliderField:'slider'});
vm.runInContext(ts.transpileModule(source.replace(/^import .*;\n/gm,'').replace(/export function/g,'function'),{compilerOptions:{jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2022}}).outputText+';this.render=ArtworkLogoScale;',context);
test('native size slider starts at normal size, forwards edits and respects a running job',()=>{
 const edits:number[]=[];
 for(const disabled of [false,true]){
  const tree=context.render({value:100,disabled,onChange:(value:number)=>edits.push(value)}),slider=tree.props.children;
  assert.equal(tree.type,'row');assert.equal(slider.type,'slider');
  assert.equal(slider.props.min,50);assert.equal(slider.props.max,100);assert.equal(slider.props.step,5);
  assert.equal(slider.props.value,100);assert.equal(slider.props.disabled,disabled);
  if(!disabled)slider.props.onChange(65);
  assert.match(translate(slider.props.label,'fr'),/Taille du logo/);
  assert.match(translate(slider.props.description,'fr'),/nouvel aperçu/);
 }
 assert.deepEqual(edits,[65]);
});
test('logo edits invalidate the prepared preview and are part of preparation identity',()=>{
 const index=readFileSync(new URL('../../src/index.tsx',import.meta.url),'utf8');
 assert.match(index,/cropX, cropY, saturation, brightness, logoScale, loopCleanup/);
 assert.match(index,/effectiveArtStyle !== "art" \? <ArtworkLogoScale/);
 const change=index.slice(index.indexOf('<ArtworkLogoScale'),index.indexOf('<ArtworkLogoScale')+300);
 assert.match(change,/setLogoScale\(value\); setDraftPreviewKey\(""\)/);
 assert.doesNotMatch(change,/setSetting|setStatus|activateFaceplate|setFaceplatePower/);
 assert.match(index,/Boolean\(STUDIO_UX\), logoScale/);
 assert.match(index,/logoScaleEdited.current = false; setLogoScale\(100\)/);
});
