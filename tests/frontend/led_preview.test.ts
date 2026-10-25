import assert from 'node:assert/strict';
import test from 'node:test';
import {LedPreviewStream, LED_PREVIEW_INTERVAL_MS} from '../../src/led_preview';
import type {RGB} from '../../src/types';

const frame = (value: number): RGB[] => Array.from({length: 17}, () => [0, value, 0]);
const flush = async () => { for (let n = 0; n < 8; n++) await Promise.resolve(); };
function clock() {
  let id = 0;
  const tasks = new Map<number, {task: () => void; delay: number}>();
  return {tasks, schedule: ((task: () => void, delay: number) => {
    tasks.set(++id, {task, delay}); return id;
  }) as any, cancel: ((id: number) => tasks.delete(id)) as any,
  async tick() {const [id, entry] = tasks.entries().next().value!; tasks.delete(id); entry.task(); await flush(); return entry.delay;}};
}
test('settings and Decky share one colour read at 50 ms, including short impacts', async () => {
  const timer = clock(), calls: string[][] = [], weather: number[] = [], output: number[] = [];
  let n = 0;
  const stream = new LedPreviewStream(async channels => {
    calls.push(channels); const value = n++ % 4 < 2 ? 250 : 45;
    return {weather: frame(value), output: frame(value)};
  }, timer.schedule, timer.cancel);
  const stopWeather = stream.subscribe('weather', next => weather.push(next![0][1]));
  const stopOutput = stream.subscribe('output', next => output.push(next![0][1]));
  for (let n = 0; n < 12; n++) {
    const delay = await timer.tick(); if (n) assert.equal(delay, LED_PREVIEW_INTERVAL_MS);
  }
  assert.equal(calls.length, 12); assert(calls.every(call => call.join(',') === 'weather,output'));
  assert.deepEqual(weather, output); assert.deepEqual(weather.slice(0, 4), [250, 250, 45, 45]);
  stopWeather(); stopOutput(); assert.equal(timer.tasks.size, 0);
});
test('slow reads never overlap and late replies cannot repaint a closed or replaced panel', async () => {
  const timer = clock(); let resolve: (value: any) => void = () => {};
  let requests = 0; const received: any[] = [];
  const stream = new LedPreviewStream(() => {requests++; return new Promise(done => {resolve = done;});}, timer.schedule, timer.cancel);
  const stop = stream.subscribe('weather', next => received.push(next));
  await timer.tick(); assert.equal(timer.tasks.size, 0);
  const stopSecond = stream.subscribe('output', next => received.push(next));
  assert.equal(requests, 1); stop(); stopSecond();
  const stopNew = stream.subscribe('weather', next => received.push(next));
  resolve({weather: frame(250)}); await flush(); assert.deepEqual(received, []);
  assert.equal(timer.tasks.size, 1); await timer.tick(); assert.equal(requests, 2);
  stopNew(); resolve({weather: frame(250)}); await flush();
  assert.deepEqual(received, []); assert.equal(timer.tasks.size, 0);
});
test('hidden documents pause reads and invalidate pending colour replies', async () => {
  const timer = clock(); let resolve: (value: any) => void = () => {}; const received: any[] = [];
  const stream = new LedPreviewStream(() => new Promise(done => {resolve = done;}), timer.schedule, timer.cancel);
  const stop = stream.subscribe('output', next => received.push(next));
  await timer.tick(); stream.setVisible(false);
  resolve({output: frame(250)}); await flush(); assert.deepEqual(received, [undefined]);
  assert.equal(timer.tasks.size, 0); stream.setVisible(true); assert.equal(timer.tasks.size, 1);
  stop(); assert.equal(timer.tasks.size, 0);
});
test('failed or invalid frames fall back and recover without a growing request queue', async () => {
  const timer = clock(), received: any[] = []; let n = 0;
  const stream = new LedPreviewStream(async () => {
    n++; if (n === 1) throw Error('offline');
    return {weather: n === 2 ? [[NaN, 0, 0]] as RGB[] : frame(250)};
  }, timer.schedule, timer.cancel);
  const stop = stream.subscribe('weather', next => received.push(next));
  await timer.tick(); assert.equal([...timer.tasks.values()][0].delay, 100);
  await timer.tick(); await timer.tick();
  assert.deepEqual(received.slice(0, 2), [undefined, undefined]); assert.deepEqual(received[2], frame(250));
  stop();
});
