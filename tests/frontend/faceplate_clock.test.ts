import assert from 'node:assert/strict';
import test from 'node:test';
import {clockCountdown} from '../../src/faceplate_clock';
import {FACEPLATE_HOME_OPTIONS,FACEPLATE_GAME_OPTIONS} from '../../src/faceplate_choices';
import {translate} from '../../src/i18n';

test('clock can be selected in both contexts and labels are localized',()=>{
  for(const options of [FACEPLATE_HOME_OPTIONS,FACEPLATE_GAME_OPTIONS])assert(options.some(x=>x.data==='clock'));
  assert.equal(translate('Clock','fr'),'Horloge');
  assert.equal(translate('Choose a clock','fr'),'Choisir une horloge');
});
test('absolute countdowns cannot accumulate interval drift or go negative',()=>{
  assert.equal(clockCountdown(1000,760),'04:00');
  assert.equal(clockCountdown(1000,999.1),'00:01');
  assert.equal(clockCountdown(1000,1001),'00:00');
  assert.equal(clockCountdown(null,1001),'-');
  assert.equal(clockCountdown(2000,1001),'16:39');
});
