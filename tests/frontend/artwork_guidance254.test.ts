import assert from 'node:assert/strict';
import test from 'node:test';
import {showArtworkPreparationHint} from '../../src/faceplate_choices';
import {translate} from '../../src/i18n';
import type {Status} from '../../src/types';
const fixture=():Status=>({game:{appid:0},faceplate_dashboard_home_source:'artwork',faceplate_dashboard_home_appid:0,
 faceplate:{available:true,powered:true,routing:{routes:{home:'dashboard',game:'artwork'},
 desired_scene:'dashboard',effective_scene:'dashboard',desired_content_key:'fallback-weather',effective_content_key:'fallback-weather',preparation:{state:'ready'}}}} as Status);
test('an acknowledged Home weather fallback is not a prepared Home artwork',()=>{
 const s=fixture();assert.equal(showArtworkPreparationHint(s),true);
 s.faceplate_dashboard_home_appid=42;assert.equal(showArtworkPreparationHint(s),true,'A stale appid is not a prepared creation');
 s.faceplate.home_artwork_prepared=true;assert.equal(showArtworkPreparationHint(s),false);
 s.faceplate.routing.effective_content_key='previous';assert.equal(showArtworkPreparationHint(s),true);
});
test('both artwork choices guide Home and games until their current scene is ready',()=>{
 for(const game of [false,true])for(const choice of ['artwork','artwork-dashboard'] as const){
  const s=fixture();s.game.appid=game?42:0;s.faceplate.routing.routes[game?'game':'home']=choice;
  assert.equal(showArtworkPreparationHint(s),true);
  s.faceplate_dashboard_home_appid=42;s.faceplate.home_artwork_prepared=true;s.faceplate.routing.desired_scene=choice;s.faceplate.routing.effective_scene=choice;
  assert.equal(showArtworkPreparationHint(s),false);
  s.faceplate.routing.preparation.state='pending';assert.equal(showArtworkPreparationHint(s),true);
 }
});
test('weather, clock, disconnected and Off never show artwork guidance',()=>{
 const incomplete=fixture();incomplete.faceplate.routing=undefined as any;assert.equal(showArtworkPreparationHint(incomplete),false);
 const s=fixture();s.faceplate_dashboard_home_source='weather';assert.equal(showArtworkPreparationHint(s),false);
 s.faceplate.routing.routes.home='native-clock';assert.equal(showArtworkPreparationHint(s),false);
 s.faceplate.routing.routes.home='artwork';s.faceplate.available=false;assert.equal(showArtworkPreparationHint(s),false);
 s.faceplate.available=true;s.faceplate.powered=false;assert.equal(showArtworkPreparationHint(s),false);
});
test('the guidance and creation action have French copy',()=>{
 for(const text of ['If no artwork is ready for this display, the Faceplate keeps its current image. Create and apply artwork in the Artwork tab.','Create artwork'])assert.notEqual(translate(text,'fr'),text);
});
