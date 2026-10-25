import assert from 'node:assert/strict';
import test from 'node:test';
import {ScreensaverContextQueue,type ScreensaverContext} from '../../src/screensaver_context_queue';
const sample=(active:boolean,detail='poll'):ScreensaverContext=>({active,detection:'available',detail});
const tick=()=>new Promise<void>(resolve=>setImmediate(resolve));

test('a delayed active poll cannot overtake the native close RPC',async()=>{
  const applied:boolean[]=[];let release!:()=>void;
  const blocked=new Promise<void>(resolve=>{release=resolve;});
  let calls=0;
  const queue=new ScreensaverContextQueue(async value=>{if(++calls===1)await blocked;applied.push(value.active);});
  const poll=queue.submit(sample(true));
  const close=queue.submit(sample(false,'notification'));
  await tick();assert.deepEqual(applied,[]);assert.equal(calls,1);
  release();await Promise.all([poll,close]);assert.deepEqual(applied,[true,false]);
});
test('bounded bursts retain the negative edge then only the latest positive',async()=>{
  const applied:string[]=[];let release!:()=>void;
  const block=new Promise<void>(resolve=>{release=resolve;});let calls=0;
  const queue=new ScreensaverContextQueue(async value=>{if(++calls===1)await block;applied.push(value.detail);});
  const results=[queue.submit(sample(true,'first')),queue.submit(sample(false,'exit'))];
  for(let i=0;i<1000;i++)results.push(queue.submit(sample(true,'latest-'+i)));
  release();await Promise.all(results);
  assert.deepEqual(applied,['first','exit','latest-999']);
});
test('a queued superseded poll is skipped and transport failures are not retried',async()=>{
  let release!:()=>void;let valid=true;const sent:boolean[]=[];
  const block=new Promise<void>(resolve=>{release=resolve;});let count=0;
  const queue=new ScreensaverContextQueue(async value=>{
    sent.push(value.active);if(++count===1)await block;if(count===2)throw Error('failed');
  });
  const first=queue.submit(sample(false));
  const stale=queue.submit(sample(true),()=>valid);valid=false;
  release();await Promise.all([first,stale]);assert.deepEqual(sent,[false]);
  await queue.submit(sample(false));await queue.submit(sample(true));
  assert.deepEqual(sent,[false,false,true]);
});
test('teardown removes queued active observations and delivers a final reset',async()=>{
  let release!:()=>void;const values:ScreensaverContext[]=[];
  const block=new Promise<void>(resolve=>{release=resolve;});
  const queue=new ScreensaverContextQueue(async value=>{if(!values.length)await block;values.push(value);});
  const initial=queue.submit(sample(true));
  const active=queue.submit(sample(true,'stale'));
  const end=queue.submit({active:false,detection:'waiting',detail:'stopped'});
  release();await Promise.all([initial,active,end]);
  assert.equal(values.length,2);assert.equal(values.at(-1)?.detail,'stopped');
});
