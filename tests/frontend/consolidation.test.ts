import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync,readFileSync} from 'node:fs';
import {faceplateUXState} from '../../src/faceplate_ux';
import {translate} from '../../src/i18n';
const read=(path:string)=>readFileSync(new URL('../../'+path,import.meta.url),'utf8');

test('receipt is not a claim of visible playback and protection delay is not a communication error',()=>{
  const input:any={faceplate_lab_enabled:true,faceplate:{available:true,powered:true,busy:false,
    delivery:{state:'confirmed'},automation:{busy:false,queued:false,last_error:'',last_result:{}},
    routing:{desired_scene:'dashboard',effective_scene:'dashboard',desired_content_key:'1',effective_content_key:'1',
      preparation:{state:'ready',error:''}}}};
  assert.equal(faceplateUXState(input).label,'Acknowledged dashboard');
  assert.match(faceplateUXState(input).detail,/cannot be confirmed/);
  input.faceplate.delivery.state='deferred';
  input.faceplate.routing.preparation.error='Flash protection: latest route pending';
  assert.equal(faceplateUXState(input).tone,'waiting');
  assert.match(faceplateUXState(input).detail,/out of date/);
  assert.equal(translate('Acknowledged dashboard','fr'),'Acquitté : Tableau de bord');
});

test('GCA has no vocal settings component, launcher or event listener',()=>{
  assert.equal(existsSync(new URL('../../src/components/GabeAssistantPanel.tsx',import.meta.url)),false);
  for(const path of ['src/index.tsx','src/components/CompactQuickPanel.tsx','src/components/FirstRunOnboarding.tsx','src/components/AmbienceProfilesPanel.tsx']){
    assert.doesNotMatch(read(path),/Decky Vocal Assistant|GabeAssistantPanel|startGabeActions|decky-vocal-assistant|Voice assistant|Voice Assistant|voice activation/);
  }
});

test('download cancellation remains usable while preparation is busy',()=>{
  const view=read('src/index.tsx');
  const button=view.slice(view.lastIndexOf('label="Cancel preparation"'),view.indexOf('Cancel download</ButtonItem>'));
  assert.match(button,/cancelUpdatePreparation/);
  assert.doesNotMatch(button,/disabled=\{updateBusy\}/);
  assert.match(read('src/components/FlashProtectionPanel.tsx'),/<FaceplateDiagnostics status=\{status\}/);
});
