import assert from 'node:assert/strict';
import test from 'node:test';
import {PlayerCityTransport} from '../../src/player_city_transport';
const lease={request_id:'a'.repeat(32),appid:367520};
test('Decky transport requests the official endpoint and reports exact bounded public fields',async()=>{
 const calls:any[]=[];
 const worker=new PlayerCityTransport({claim:async()=>lease,
  fetch:async(url,init)=>{calls.push([url,init.method,init.headers,init.signal,init.redirect]);return new Response(JSON.stringify({response:{result:1,player_count:5636},private:'discard'}));},
  complete:async(...args)=>{calls.push(args);return true;}});
 worker.start();await worker.poll();worker.stop();
 assert.equal(calls[0][0],'https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid=367520');
 assert.equal(calls[0][1],'GET');assert.equal(calls[0][4],'error');assert(calls[0][3] instanceof AbortSignal);
 assert.deepEqual(calls[1],[lease.request_id,367520,{response:{result:1,player_count:5636}},'']);
});
test('no lease, invalid AppID or stopped runtime never opens a Steam connection',async()=>{
 let count=0;
 for(const request of [null,{...lease,appid:0},{...lease,appid:4294967296}]){
  const worker=new PlayerCityTransport({claim:async()=>request,fetch:async()=>{count++;return new Response();},complete:async()=>true});
  worker.start();await worker.poll();worker.stop();await worker.poll();
 }
 assert.equal(count,0);
});
test('only one fetch runs and an old frontend response cannot publish after stop/start',async()=>{
 let finish!:(response:Response)=>void;let fetches=0,publishes=0;
 const worker=new PlayerCityTransport({claim:async()=>lease,fetch:async()=>{fetches++;return new Promise(done=>finish=done);},
  complete:async()=>{publishes++;return true;}});
 worker.start();const first=worker.poll();await Promise.resolve();await worker.poll();assert.equal(fetches,1);
 worker.stop();worker.start();await worker.poll();assert.equal(fetches,1);
 finish(new Response('{"response":{"result":1,"player_count":5636}}'));await first;
 assert.equal(publishes,0);worker.stop();
});
test('zero, invalid values, HTTP refusal, oversized body and connection failure remain distinct',async()=>{
 for(const [response,expected] of [
  ['{"response":{"result":1,"player_count":0}}',''],
  ['{"response":{"result":1,"player_count":true}}','response_invalid'],
  ['{"response":{"result":1,"player_count":"5636"}}','response_invalid'],
  ['{"response":{"result":1,"player_count":4294967296}}','response_invalid'],
  ['x'.repeat(8193),'response_too_large'],['{','response_invalid'],['http','http_403'],['network','connection'],
 ] as const){
  const results:any[]=[];
  const worker=new PlayerCityTransport({claim:async()=>lease,
   fetch:async()=>{if(response==='network')throw Error('private-url');return response==='http'?new Response('',{status:403}):new Response(response);},
   complete:async(...args)=>{results.push(args);return true;}});
  worker.start();await worker.poll();worker.stop();
  assert.equal(results[0][3],expected);assert(!JSON.stringify(results).includes('private-url'));
  if(expected)assert.equal(results[0][2],null);
 }
});
