import assert from 'node:assert/strict';
import test from 'node:test';
import {FACEPLATE_HOME_OPTIONS,FACEPLATE_GAME_OPTIONS,quickFaceOptions} from '../../src/faceplate_choices';

test('quick selector exposes every Settings route and Off with Home/game parity',()=>{
 for(const french of [false,true]){
  const game=quickFaceOptions(true,french),home=quickFaceOptions(false,french);
  assert.deepEqual(game.map(o=>o.data),[...FACEPLATE_GAME_OPTIONS.map(o=>o.data),'off']);
  assert.deepEqual(home.map(o=>o.data),[...FACEPLATE_HOME_OPTIONS.map(o=>o.data),'off']);
  assert(!home.some(o=>o.data==='player-city'));
  assert.deepEqual(game.slice(1,-1).map(o=>o.data),home.slice(0,-2).map(o=>o.data));
  assert.equal(new Set(game.map(o=>o.data)).size,game.length);
  assert.equal(new Set(home.map(o=>o.data)).size,home.length);
  assert.equal(game.at(-1)?.label,french?'Éteint':'Off');
 }
});
