import assert from 'node:assert/strict';
import test from 'node:test';
import {faceplateTransferNotice} from '../../src/faceplate_transfer';
import {translate} from '../../src/i18n';
import type {Status} from '../../src/types';

function fixture():Status{return {signalbar_enabled:true,faceplate_lab_enabled:true,current_display:'artwork',faceplate:{
  available:true,busy:false,powered:true,phase:'artwork',delivery:{state:'confirmed'},
  routing:{desired_content_key:'new',effective_content_key:'new',preparation:{state:'ready',error:''}},
  automation:{busy:false,queued:false,last_error:''},
}} as Status;}

test('a new image shows preparation, actual USB sending and confirmation in order',()=>{
  const s=fixture(),p=s.faceplate;
  p.automation.queued=true;p.routing.preparation.state='pending';
  // A previous successful receipt must never hide the next request.
  p.routing.effective_content_key='old';
  assert.equal(faceplateTransferNotice(s)?.label,'Preparing image…');
  p.automation.queued=false;p.automation.busy=true;p.routing.preparation.state='preparing';
  assert.equal(faceplateTransferNotice(s)?.label,'Preparing image…');
  p.phase='uploading';p.delivery!.state='sending';
  assert.equal(faceplateTransferNotice(s)?.label,'Transferring to Faceplate…');
  p.automation.busy=false;p.phase='artwork';p.delivery!.state='confirmed';p.routing.preparation.state='ready';
  assert.equal(faceplateTransferNotice(s),null,'An old content key is not proof of the new transfer');
  p.routing.effective_content_key='new';
  assert.equal(faceplateTransferNotice(s)?.label,'Transfer confirmed by Faceplate.');
  assert.equal(faceplateTransferNotice(s)?.active,false);
});

test('missing final confirmation settles without a failed or endless waiting claim',()=>{
  const s=fixture(),p=s.faceplate;
  p.phase='sent-unconfirmed';p.delivery!.state='unconfirmed';p.routing.preparation.state='unconfirmed';
  assert.equal(faceplateTransferNotice(s)?.label,'Faceplate confirmation not received.');
  assert.equal(faceplateTransferNotice(s)?.active,false);
  p.powered=false;assert.equal(faceplateTransferNotice(s)?.label,'Faceplate confirmation not received.','A missing receipt remains visible while automatic power-on waits');
  p.powered=true;
  assert.doesNotMatch(faceplateTransferNotice(s)!.detail,/Please wait|failed|displayed/i);
  // A new request supersedes this historical receipt and previous error.
  p.automation.queued=true;p.routing.preparation.state='pending';p.automation.last_error='old failure';
  assert.equal(faceplateTransferNotice(s)?.label,'Preparing image…');
});

test('known failure and protection waits are distinct from active transfers',()=>{
  const s=fixture(),p=s.faceplate;
  p.phase='error';p.delivery!.state='sending';p.routing.preparation.state='error';
  assert.equal(faceplateTransferNotice(s)?.active,false,'An old sending receipt must not hide the current failure');
  p.delivery!.state='failed';
  assert.equal(faceplateTransferNotice(s)?.label,'Transfer to Faceplate failed.');
  assert.equal(faceplateTransferNotice(s)?.active,false);
  p.phase='deferred';p.delivery!.state='deferred';
  p.automation.queued=true;p.routing.preparation.error='Flash protection: refresh deferred';
  assert.equal(faceplateTransferNotice(s)?.label,'Refresh delayed to protect the Faceplate.');
  assert.equal(faceplateTransferNotice(s)?.active,false);
});

test('off, disconnected and external ownership suppress stale progress; waking USB is still visible',()=>{
  const s=fixture(),p=s.faceplate;
  p.automation.busy=true;p.phase='uploading';p.delivery!.state='sending';p.powered=false;
  assert.equal(faceplateTransferNotice(s)?.active,true,'Power can remain off until the current scene is acknowledged');
  s.signalbar_enabled=false;assert.equal(faceplateTransferNotice(s),null);
  s.signalbar_enabled=true;s.current_display='displays_off';assert.equal(faceplateTransferNotice(s),null);
  s.current_display='artwork';p.available=false;assert.equal(faceplateTransferNotice(s),null);
  p.available=true;p.busy=true;assert.equal(faceplateTransferNotice(s),null);
  p.busy=false;s.faceplate_lab_enabled=false;assert.equal(faceplateTransferNotice(s),null);
  s.faceplate_lab_enabled=true;p.power_recovery={suspended:true} as Status['faceplate']['power_recovery'];
  assert.equal(faceplateTransferNotice(s),null,'Explicit Off wins even over a stale sending snapshot');
  p.power_recovery.suspended=false;p.automation.busy=false;p.phase='powered-off';p.delivery!.state='idle';
  assert.equal(faceplateTransferNotice(s),null);
});

test('native clock commands and incomplete snapshots do not invent image confirmation',()=>{
  const s=fixture(),p=s.faceplate;
  p.automation.busy=true;p.delivery!.state='sending';
  assert.equal(faceplateTransferNotice(s)?.label,'Transferring to Faceplate…');
  assert.equal(faceplateTransferNotice({...s,faceplate:{available:true} as Status['faceplate']}),null);
});

test('the linguist reviewed French copy distinguishes transfer and receipt',()=>{
  assert.equal(translate('Transferring to Faceplate…','fr'),'Transfert vers la Faceplate en cours…');
  assert.equal(translate('Please wait.','fr'),'Veuillez patienter.');
  for(const label of ['Preparing image…','Saving display choice…','Faceplate confirmation not received.',
    'Transfer confirmed by Faceplate.','Transfer to Faceplate failed.','Refresh delayed to protect the Faceplate.',
    'See Faceplate diagnostics for details.'])assert.notEqual(translate(label,'fr'),label,label);
});


test('one scheduled retry remains visibly unconfirmed and stops after its final failure',()=>{
 const s=fixture();s.faceplate.powered=false;s.faceplate.phase='sent-unconfirmed';
 s.faceplate.delivery.state='unconfirmed';s.faceplate.routing.preparation.state='unconfirmed';
 s.faceplate.power_recovery={route_state:'retry-waiting'} as any;
 let notice=faceplateTransferNotice(s);
 assert.equal(notice?.label,'Faceplate confirmation not received.');
 assert.equal(notice?.active,true);assert.match(notice?.detail??'',/One automatic retry/);
 s.faceplate.power_recovery.route_state='unconfirmed';notice=faceplateTransferNotice(s);
 assert.equal(notice?.active,false);assert.doesNotMatch(notice?.detail??'',/Please wait/);
 assert.notEqual(translate('One automatic retry is scheduled. Please wait.','fr'),
   'One automatic retry is scheduled. Please wait.');
});
