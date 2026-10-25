import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
const source=readFileSync(new URL('../../src/index.tsx',import.meta.url),'utf8');
test('public update controls omit automatic installation and short check intervals',()=>{
 assert.doesNotMatch(source,/label="Download and install updates automatically"/);
 const intervals=source.slice(source.indexOf('const UPDATE_INTERVAL_OPTIONS'),source.indexOf('const UPDATE_CHANNEL_OPTIONS'));
 for(const n of [60,180,360,720,1440])assert(intervals.includes(`{ data: ${n}, label:`));
 assert.doesNotMatch(intervals,/data: (5|15),/);
 assert.match(source,/disabled=\{!update.auto_check \|\| updateBusy\}/);
 assert.match(source,/label="Automatically check for updates"/);
});
