import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {setupSteps,setupNeeds} from '../../src/setupFlow';
import type {SetupDraft,SetupSnapshot} from '../../src/onboardingApi';
const draft:SetupDraft={step:'assistant',preset:'atmosphere',brightness:9,night:false,night_percentage:35,
  city:null,assistant_requested:false,faceplate_requested:false,home:'dashboard',game:'artwork'};
const noHardware:SetupSnapshot={draft:{},bar_detected:false,faceplate_detected:false,faceplate_busy:false};
test('GCA setup excludes voice steps even when resuming legacy consent',()=>{
  assert.deepEqual(setupSteps({...draft,assistant_requested:true},noHardware),['review']);
  assert.deepEqual(setupSteps(draft,noHardware),['review']);
});
test('hardware is current, not a saved faceplate preference',()=>{
  assert.deepEqual(setupSteps({...draft,faceplate_requested:true},noHardware),['review']);
  assert.ok(setupSteps(draft,{...noHardware,faceplate_detected:true}).includes('faceplate'));
  assert.ok(!setupSteps(draft,{...noHardware,faceplate_detected:true}).includes('services'));
});
test('native clock alone needs neither city nor SteamGridDB',()=>{
  const clock={...draft,faceplate_requested:true,home:'native-clock' as const,game:'keep' as const};
  assert.deepEqual(setupNeeds(clock,{...noHardware,faceplate_detected:true}),{weather:false,artwork:false});
  assert.ok(!setupSteps(clock,{...noHardware,faceplate_detected:true}).includes('services'));
});
test('weather in game needs a city even when Home is a native clock',()=>{
  assert.deepEqual(setupNeeds({...draft,faceplate_requested:true,home:'native-clock',game:'weather'},
    {...noHardware,faceplate_detected:true}),{weather:true,artwork:false});
});
test('Steam Players City in setup requests weather but no artwork API key',()=>{
 const value={...draft,faceplate_requested:true,home:'native-clock' as const,game:'player-city' as const};
 assert.deepEqual(setupNeeds(value,{...noHardware,faceplate_detected:true}),{weather:true,artwork:false});
 assert(setupSteps(value,{...noHardware,faceplate_detected:true}).includes('services'));
});
test('night-only gets a city, artwork-only gets optional SGDB, no voice key',()=>{
  assert.deepEqual(setupNeeds({...draft,night:true},{...noHardware,bar_detected:true}),{weather:true,artwork:false});
  assert.deepEqual(setupNeeds({...draft,home:'native-clock',faceplate_requested:true},{...noHardware,faceplate_detected:true}),
    {weather:false,artwork:true});
});
test('active wizard replaces old global hardware gate and cannot disconnect update access',()=>{
  const index=readFileSync(new URL('../../src/index.tsx',import.meta.url),'utf8');
  const route=index.slice(index.indexOf('function FirstRunSetupRoute('),index.indexOf('const FACEPLATE_ARTWORK_SEARCH_OPTIONS'));
  assert.match(route,/<FirstRunOnboarding/);
  assert.doesNotMatch(route,/if \(!status.available\)|if \(status.onboarding_completed\)/);
  const ui=readFileSync(new URL('../../src/components/FirstRunOnboarding.tsx',import.meta.url),'utf8');
  assert.doesNotMatch(ui,/disconnectPrivateUpdate|setUpdatePreferences/);
  assert.match(ui,/bIsPassword/);
  assert.match(ui,/window.clearInterval\(timer\)/);
  assert.match(ui,/finishSetupWithFaceplate\(selected/);
});

test('legacy assistant and voice drafts always resolve to current non-vocal steps',()=>{
  for(const step of ['assistant','voice'] as const){
    const saved={...draft,step,assistant_requested:true,assistant_confirmed:true};
    const steps=setupSteps(saved,{...noHardware,bar_detected:true,faceplate_detected:true});
    assert.deepEqual(steps,['ambiance','brightness','faceplate','services','review']);
    assert.ok(!steps.includes(saved.step));
  }
  const ui=readFileSync(new URL('../../src/components/FirstRunOnboarding.tsx',import.meta.url),'utf8');
  assert.doesNotMatch(ui,/GuidedVoiceSetup|configureGabe|gabeAction|voiceReady|voice_verified|startPrivateUpdateAuthorization|pollPrivateUpdateAuthorization/);
  assert.doesNotMatch(ui,/Decky Vocal Assistant|decky-vocal-assistant|Open Decky/);
  assert.match(ui,/if\(!steps.includes\(value.step\)\)value.step=steps\[0\]/);
});
