import assert from 'node:assert/strict';
import test from 'node:test';
import {trailingSetting} from '../../src/trailingSetting';
test('leaving before debounce persists precisely the last slider value',async()=>{
  const saves:number[]=[];let callback=()=>{};let cancelled=0;
  const writer=trailingSetting(async(value:number)=>{saves.push(value);return value;},400,
    cb=>{callback=cb;return 1 as unknown as ReturnType<typeof setTimeout>;},()=>{cancelled++;});
  writer.push(10);writer.push(45);writer.push(80);
  await writer.flush();
  callback();await writer.flush();
  assert.deepEqual(saves,[80]);assert.equal(writer.pending(),false);assert.equal(cancelled,3);
});
test('an in-flight older save cannot overtake the latest save',async()=>{
  let release:()=>void=()=>{};const gate=new Promise<void>(r=>release=r);const saves:number[]=[];
  const writer=trailingSetting(async(value:number)=>{if(value===20)await gate;saves.push(value);return value;});
  writer.push(20);const first=writer.flush();await Promise.resolve();
  writer.push(85);const last=writer.flush();release();await first;await last;
  assert.deepEqual(saves,[20,85]);
});
test('a failed earlier save does not discard a more recent choice',async()=>{
  const saves:number[]=[];const writer=trailingSetting(async(value:number)=>{saves.push(value);if(value===20)throw Error('offline');return value;});
  writer.push(20);await writer.flush().catch(()=>undefined);
  writer.push(60);await writer.flush();assert.deepEqual(saves,[20,60]);
});
test('locking cancels debounce and queued saves while later unlocked choices remain usable',async()=>{
  const saves:number[]=[];let release!:()=>void;
  const blocked=new Promise<void>(resolve=>release=resolve);
  const writer=trailingSetting(async(value:number)=>{saves.push(value);if(value===10)await blocked;return value;});
  writer.push(10);const first=writer.flush();
  for(let i=0;i<5;i++)await Promise.resolve();
  writer.push(20);const queued=writer.flush();writer.push(30);writer.cancel();
  writer.push(40);const resumed=writer.flush();release();
  await first;await queued;await resumed;
  assert.deepEqual(saves,[10,40]);assert.equal(writer.pending(),false);
});
