import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { supportsPrivateTools } from "../../src/distribution";
import { weatherPreviewMeta } from "../../src/faceplate_visual_themes";
import { translate } from "../../src/i18n";
import {SETTINGS_CATEGORIES} from '../../src/settings_structure';

const index = readFileSync(new URL("../../src/index.tsx", import.meta.url), "utf8");
test("public sidebar has six native pages after Studio separation and no separators or UX switch", () => {
  const sidebar = index.slice(index.indexOf("function GabeCubeAuraSettings("), index.indexOf("export default definePlugin"));
  assert.equal(SETTINGS_CATEGORIES.length,6);
  assert.doesNotMatch(sidebar, /separator|setInterval|uxEnabled/);
  assert.doesNotMatch(index, /Try the Lab 58 UX|Lab 58 interface|Lab57SettingsNavigation/);
  assert(SETTINGS_CATEGORIES.some(item=>item.title==='Updates'));
  assert(SETTINGS_CATEGORIES.some(item=>item.title==='Advanced'));
  assert.match(sidebar, /<SimpleSettings/);
});
test("support capacity is explicit and public channels do not expose private authorization", () => {
  assert.equal(supportsPrivateTools("1.4.1"), false);
  assert.equal(supportsPrivateTools("1.4.1-beta.1"), false);
  assert.equal(supportsPrivateTools("1.4.1-lab.84"), true);
  assert.match(index, /option\.data !== "private" \|\| update\.private_tools/);
  assert.match(index, /Capture diagnostics · 5 minutes/);
  assert.doesNotMatch(index, /slot="updates.github"/);
  assert.match(index, /exportDiagnosticReport\(\)/);
});
test("normal weather metadata omits raw internal revisions without hiding diagnostic data", () => {
  const value = { data_uri: "", error: "", live_weather: true, visual_theme: "weather-artwork-v2" as const,
    collection_revision: "weather-artwork-v2-runtime-4", selection_status: "exact", variant_name: "Bluewater" };
  assert.deepEqual(weatherPreviewMeta(value), ["live temperature", "Realistic", "Bluewater"]);
  assert.ok(weatherPreviewMeta(value, true).includes("weather-artwork-v2-runtime-4"));
});
test("new product copy is translated in both locales", () => {
  assert.equal(translate("Advanced", "fr"), "Avancé");
  assert.equal(translate("Testing support", "fr"), "Support des tests");
  assert.equal(translate("Realistic", "fr"), "Réaliste");
  assert.equal(translate("Realistic", "en"), "Realistic");
});
