import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {SETTINGS_CATEGORIES,SETTINGS_ALIASES,settingsSources} from '../../src/settings_structure';

const index = readFileSync(new URL("../../src/index.tsx", import.meta.url), "utf8");
const profiles = readFileSync(new URL("../../src/components/AmbienceProfilesPanel.tsx", import.meta.url), "utf8");

test("profile editor is mounted only on its settings page, never in the quick tab", () => {
  const mounts = [...index.matchAll(/\{([^{}]+)\?\s*<AmbienceProfilesPanel\s*\/>\s*:\s*null\}/g)];
  assert.equal(mounts.length, 1);
  assert.equal(mounts[0][1].trim(), 'page === "profiles"');
  assert.match(index, /profiles: "Ambience profiles"/);
});

test("grouped navigation exposes profiles without adding another sidebar category", () => {
  assert.equal(SETTINGS_CATEGORIES.length,6);
  assert(SETTINGS_CATEGORIES.find(item=>item.id==='display')?.tabs.some(tab=>tab[0]==='profiles'));
  assert.deepEqual(SETTINGS_ALIASES.profiles,{category:'display',tab:'profiles'});
  assert.deepEqual(settingsSources(SETTINGS_ALIASES.profiles),['profiles']);
});

test("profiles remain reachable through native display settings without any vocal link", () => {
  assert.deepEqual(SETTINGS_ALIASES.profiles,{category:'display',tab:'profiles'});
  assert.doesNotMatch(index,/onOpenProfiles|GabeAssistantPanel|Voice Assistant/);
  assert.match(index,/page === "profiles" \? <AmbienceProfilesPanel/);
});

test("relocation preserves native editing, profile storage and mounted-only resource use", () => {
  assert.match(profiles, /callable.*get_ambience_profiles/);
  assert.match(profiles, /callable.*save_ambience_profile/);
  assert.match(profiles, /callable.*activate_ambience_profile/);
  assert.match(profiles, /callable.*delete_ambience_profile/);
  assert.match(profiles, /alive\.current = false/);
  assert.doesNotMatch(profiles, /setInterval|setTimeout|window\.open|iframe|focus\(|scrollTo\(/);
});
