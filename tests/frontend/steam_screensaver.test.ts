import assert from "node:assert/strict";
import test from "node:test";

import {
  isSteamScreensaverService,
  registerForScreensaverState,
  screensaverActiveFromResponse,
} from "../../src/steam_screensaver";

test("screensaver service discovery only requires the read capability", () => {
  assert.equal(isSteamScreensaverService({ GetActiveState() {}, ForceScreensaver() {} }), true);
  assert.equal(isSteamScreensaverService({ GetActiveState() {} }), true);
  assert.equal(isSteamScreensaverService({ ForceScreensaver() {} }), false);
  assert.equal(isSteamScreensaverService(null), false);
});

test("screensaver active state unwraps current Steam response shapes", () => {
  assert.equal(screensaverActiveFromResponse({ Body: () => ({ active: true }) }), true);
  assert.equal(screensaverActiveFromResponse({ body: { bActive: false } }), false);
  assert.equal(screensaverActiveFromResponse({ is_active: true }), true);
  assert.equal(screensaverActiveFromResponse({ Body: () => ({ active: () => 1 }) }), true);
  assert.equal(screensaverActiveFromResponse(true), true);
  assert.equal(screensaverActiveFromResponse(0), false);
  assert.equal(screensaverActiveFromResponse({ state: "active" }), null);
});

test("screensaver notifications are used when the Steam service exposes them", () => {
  let received: unknown;
  let unregistered = false;
  const service = {
    GetActiveState() {},
    RegisterForActiveStateChanged(callback: (value: unknown) => void) {
      callback({ active: true });
      return { unregister: () => { unregistered = true; } };
    },
  };
  const registration = registerForScreensaverState(service, (value) => { received = value; });
  assert.deepEqual(received, { active: true });
  registration?.unregister?.();
  assert.equal(unregistered, true);
});

test('Valve protobuf notification name is supported with polling as fallback',()=>{
  let received=false;
  const service={GetActiveState(){},RegisterForNotifyActiveStateChanged(callback:(value:unknown)=>void){callback({Body:()=>({active:()=>true})});return {unregister(){}};}};
  assert(registerForScreensaverState(service,value=>{received=screensaverActiveFromResponse(value)===true;}));
  assert(received);
});
