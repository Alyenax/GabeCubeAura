import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {existsSync,readFileSync} from 'node:fs';
import test from 'node:test';

// Frozen publication-time contract, generated from the two published commits.
// Tests use ordinary files, so the shipped source checkout need not contain Git.
const root=new URL('../../',import.meta.url);
const fixture=JSON.parse(readFileSync(new URL('tests/fixtures/lab157_port_contract.json',root),'utf8'));
const read=(path:string)=>readFileSync(new URL(path,root));
const sha=(path:string)=>createHash('sha256').update(read(path)).digest('hex');

test('the simple settings rebuild keeps all non-UI Lab153 modules and the Lab158 recovery',()=>{
  assert.equal(fixture.base,'75d3a6b0f29372234cc084076af38b4d712519f7');
  assert.equal(Object.keys(fixture.preserved).length,65);
  // Approved Lab159 settings-only replacement. Backend/API/hardware retain their frozen contract.
  // Audit GH-07 and GA-06 replace quantized RGB and stale runtime continuations; behavioral tests cover both.
  // Lab199 removes vocal steps; onboarding behavior and recovery have dedicated tests.
  const targeted=new Set(['src/faceplate_ux.ts','src/components/AnimatedScreensaverStudio.tsx','src/setupFlow.ts','src/components/PreciseColorEditor.tsx','src/runtime.ts','src/components/FirstRunOnboarding.tsx','src/onboardingApi.ts',
    'src/index.tsx','src/localized_ui.tsx','src/localized_nodes.tsx','src/i18n/fr.ts','src/i18n.ts','src/components/Disclosure.tsx',
    // Retired TV frontend and tests now live in the external DAS provenance bundle.
    'src/cinema_bridge.ts','src/cinema_types.ts','src/studio_types.ts','src/studio_workflow.ts','src/components/ScreensaverPanel.tsx',
    'src/gabe_glossary.ts','src/i18n/cinema.ts','src/i18n/studio.ts',
    'src/components/GabeAssistantPanel.tsx','src/components/GabeCommandGlossary.tsx','src/components/FlashProtectionPanel.tsx','src/i18n/flash_protection.ts',
    // Lab183 fixes the mixed-language profile help; backend/profile behavior is unchanged.
    'src/components/AmbienceProfilesPanel.tsx',
    // Lab195 intentionally changes the UI-only Faceplate visibility gate; runtime contracts remain frozen.
    'src/quick_panel.ts',
    // Lab196 restores Steam button paint and focus; no runtime/hardware change.
    'src/components/QuickAction.tsx',
    // Lab214 cancels queued slider saves when first-time setup locks the panel.
    'src/trailingSetting.ts',
    // Lab226 updates rain captions for the approved day/night LED palettes.
    'src/weather_variants.ts',
    // Lab227 reports the independently saved rain choices in the snapshot.
    'src/settings_snapshot.ts',
    // Lab229 adds a shared, visibility-controlled live colour stream.
    'src/components/PalettePreview.tsx',
    // Lab166 explicitly adds the optional personal-timer action RPC/status.
    'src/api.ts','src/types.ts',
    // Lab177 adds translated copy for the approved fourth assistant; native UI tests cover it.
    'src/i18n/assistant_setup.ts',
    // Lab164 adds a third identity; dedicated asset/voice/runtime tests replace these old byte locks.
    'src/components/GuidedVoiceSetup.tsx','src/gabe_api.ts','src/gabe_actions.ts','src/i18n/public_copy.ts','py_modules/signalbar/assistant/face.py',
    'py_modules/signalbar/assistant/companion_speech.py','py_modules/signalbar/assistant/service.py',
    'py_modules/signalbar/assistant/local_launch.py','py_modules/signalbar/assistant/wake_worker.py',
    // Lab183 adds the requested USB protection caption; behavioural locale tests cover it.
    'src/i18n/fr.ts','src/i18n/fr_patterns.ts','py_modules/signalbar/backend/engine.py']);
  for(const [path,expected] of Object.entries(fixture.preserved))if(!targeted.has(path)&&!path.startsWith('py_modules/signalbar/assistant/'))assert.equal(sha(path),expected,path);
});

test('retained historical voice modules keep byte locks; moved UI tests belong to DVA',()=>{
  assert.equal(fixture.voice,'1614413774b5e803e0125c0e5f56b97351d9f67c');
  assert.equal(Object.keys(fixture.ported).length,14);
  // main.py adds only recovery status/journal RPCs; the voice engine is unchanged.
  const changed=new Set(['tests/frontend/gabe_interruption.test.ts','main.py','py_modules/signalbar/assistant/service.py',
    'src/gabe_glossary.ts','src/gabe_actions.ts',
    'py_modules/signalbar/assistant/face.py','py_modules/signalbar/assistant/companion_speech.py','src/gabe_api.ts',
    'py_modules/signalbar/assistant/local_launch.py','py_modules/signalbar/assistant/wake_worker.py',
    'tests/backend/test_assistant_responsiveness.py',
    // Lab188 adapts this fixture to the shared capture/native detector options.
    // The assertions still require no dispatch after withdrawal and no stuck overlap.
    'tests/backend/test_gabe_natural_commands.py',
    // Lab173: absolute hush intent is forwarded to the prepared exit tail.
    // The dedicated interruption and exit tests retain cancellation/echo checks.
    'py_modules/signalbar/assistant/interruption.py','py_modules/signalbar/assistant/natural_commands.py']);
  for(const [path,expected] of Object.entries(fixture.ported))if(!changed.has(path)&&!path.startsWith('py_modules/signalbar/assistant/')&&!path.startsWith('tests/backend/test_assistant')&&!path.startsWith('tests/backend/test_gabe'))assert.equal(sha(path),expected,path);
});

test('historical shells stay excluded and GCA no longer renders a vocal settings shell',()=>{
  for(const path of ['src/components/UsagesSettings.tsx','src/usages_theme.ts',
    'src/usages_das_theme.ts','src/usages_navigation.ts','src/usages_presentation.tsx',
    'src/settingsScroll.ts','src/onboardingAmbiences.ts'])assert.equal(existsSync(new URL(path,root)),false,path);
  assert.equal(existsSync(new URL('src/components/GabeAssistantPanel.tsx',root)),false);
  assert.doesNotMatch(read('src/index.tsx').toString(),/GabeAssistantPanel|GabeSettingsSession/);
  const pkg=JSON.parse(read('package.json').toString());
  assert.equal(pkg.version,'1.5.0');
  assert.equal(pkg.gabecubeaura_test_build,undefined);
});
