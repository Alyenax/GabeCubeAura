import assert from 'node:assert/strict';
import test from 'node:test';
import type {Status} from '../../src/types';
import {playerCitySummary} from '../../src/player_city';
function status(language:string,state:string,players:number|null):Status{
 return {ui_language:language,game:{appid:620},faceplate:{player_city:{reason:'cadence',sample:{appid:620,state,players,sample_age_s:60},displayed:{appid:620,players:32000,sampled_at:Date.now()/1000-1200,at:Date.now()/1000-1200}}}} as Status;
}
test('measurement and last acknowledged City stay distinct with US commas in FR and EN',()=>{
 for(const language of ['en','fr']){
  const text=playerCitySummary(status(language,'ready',32809));
  assert.match(text,/32,809/);assert.match(text,/32,000/);assert.match(text,/20 min/);
  assert.doesNotMatch(text,/32K|temps réel|real.time/);
 }
});
test('zero, Steam API error and transport error are never presented as the same value',()=>{
 for(const language of ['en','fr']){
  const zero=playerCitySummary(status(language,'zero',0));assert.match(zero,/0/);
  const api=playerCitySummary(status(language,'unavailable',null));
  const connection=playerCitySummary(status(language,'network_error',null));
  assert.notEqual(zero,api);assert.notEqual(api,connection);
  assert(!api.startsWith('Steam: 0'));assert(!connection.startsWith('Steam: 0'));
 }
});
test('Steam certificate verification failure has a specific translated explanation',()=>{
 for(const language of ['en','fr']){
  const tls=playerCitySummary(status(language,'tls_error',null));
  assert.match(tls,/HTTPS/);assert.match(tls,/certificate|certificat/);
  assert.doesNotMatch(tls,/Waiting|attente d’une mesure/);
 }
});
test('only hourly scheduling is shown; an old protection delay is ignored',()=>{
 for(const language of ['en','fr']){
  const value=status(language,'ready',5636);
  value.faceplate.player_city!.last_attempt={outcome:'deferred'};
  value.faceplate.flash_protection={player_city:{retry_after_seconds:3599}} as Status['faceplate']['flash_protection'];
  value.faceplate.player_city!.next_refresh_s=3599;
  const text=playerCitySummary(value);assert.match(text,/60 min/);assert.doesNotMatch(text,/Screen protection|Protection de l’écran/);
 }
});

test('no game and non-Steam identities have explicit empty states without fake counts',()=>{
 for(const language of ['en','fr']){
  const value=status(language,'inactive',null);value.game={appid:0,title:''};
  const idle=playerCitySummary(value);assert.match(idle,/Start a Steam game|Lancez un jeu Steam/);
  value.game={appid:0x100000000,title:'Non-Steam shortcut'};
  const unsupported=playerCitySummary(value);assert.match(unsupported,/AppID/);assert.doesNotMatch(unsupported,/32,000|32,809/);
 }
});
