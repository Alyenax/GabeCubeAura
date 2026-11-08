import assert from 'node:assert/strict';
import test from 'node:test';
import {faceplatePowerAction} from '../../src/faceplate_power_action';
import {translate} from '../../src/i18n';
import type {Status} from '../../src/types';
const status=(powered:boolean|null,recovery=false)=>({faceplate:{powered,restoration:{recovery_available:recovery}}} as Status);
test('failed dark restoration offers one explicit power action even when the power ACK was lost',()=>{
  for(const powered of [false,null]){
    const action=faceplatePowerAction(status(powered,true));
    assert.equal(action.enabled,true);assert.equal(action.button,'Resume stored picture');
    assert.match(action.description,/without uploading/);assert.match(action.description,/unconfirmed/);
  }
});
test('ordinary power on/off controls retain their existing intent',()=>{
  assert.equal(faceplatePowerAction(status(false)).enabled,true);
  assert.equal(faceplatePowerAction(status(true)).enabled,false);
});
test('recovery wording follows the selected GCA language',()=>{
  const action=faceplatePowerAction(status(false,true));
  assert.equal(translate(action.label,'en'),'Resume stored picture');
  assert.equal(translate(action.label,'fr'),'Reprendre l’image enregistrée');
  assert.match(translate(action.description,'fr'),/sans transférer/);
});
