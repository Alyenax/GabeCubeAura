import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";
import { createElement, type ReactElement } from "react";
import { getUILanguage, setUILanguage, subscribeUILanguage, translate, translateUIProperties } from "../../src/i18n";
import { french } from "../../src/i18n/fr";
import { translateNode } from "../../src/localized_nodes";
import { weatherTopBarReading } from "../../src/weather_topbar_model";
import type { Status } from "../../src/types";
import {backendFrench} from '../../src/i18n/backend_messages';

test('stock backend messages and nested UI labels follow the interface, not conversation language',()=>{
  for(const [en,fr] of Object.entries(backendFrench)){
    assert.equal(translate(en,'fr'),fr,en);
    assert.equal(translate(fr,'en'),en,fr);
  }
  assert.equal(translate('Affichage : Tableau de bord','en'),'Showing Dashboard');
  assert.equal(translate('Enregistré dans /home/deck/Météo.json','en'),'Saved to /home/deck/Météo.json');
  assert.equal(translate('Météo officielle de Weather City','en'),'Météo officielle de Weather City');
  assert.equal(translate('All assistants by voice','fr'),'Tous les assistants à la voix');
});

test("English remains the exact fallback; French preserves variable values and diagnostics", () => {
  assert.equal(translate("Advanced / debug", "en"), "Advanced / debug");
  assert.equal(translate("Advanced / debug", "fr"), "Avancé / débogage");
  assert.equal(translate("  Weather\n", "fr"), "  Météo\n");
  assert.equal(translate("USB EIO: /dev/ttyACM0", "fr"), "USB EIO: /dev/ttyACM0");
  assert.equal(translate("Saved for Weather", "fr"), "Enregistré pour Weather");
  assert.equal(translate("Saved to /home/deck/Weather.json", "fr"), "Enregistré dans /home/deck/Weather.json");
  assert.equal(translate("Showing dashboard", "fr"), "Affichage : Tableau de bord");
  assert.equal(translate("Back to Signals and automation", "fr"), "Retour à Signaux et automatisation");
  assert.equal(translate("Show screenshots", "fr"), "Afficher Captures d’écran");
  assert.equal(translate("1 controller", "fr"), "1 manette");
  assert.equal(translate("4 controllers", "fr"), "4 manettes");
  assert.equal(translate("Version 1.4.1-lab.59 is available.", "fr"), "La version 1.4.1-lab.59 est disponible.");
});

test("the language changes immediately, subscribers detach and unsupported values fall back to English", () => {
  setUILanguage("en");
  const observed: string[] = [];
  const stop = subscribeUILanguage(() => observed.push(getUILanguage()));
  setUILanguage("fr"); setUILanguage("fr");
  assert.equal(translate("Weather"), "Météo");
  setUILanguage("de");
  assert.equal(translate("Weather"), "Weather");
  stop(); setUILanguage("fr"); setUILanguage("en");
  assert.deepEqual(observed, ["fr", "en"]);
});

test("translated native props retain callbacks, refs, routes, user text and selected values", () => {
  const onChange = () => undefined;
  const content = { component: "Content" };
  const ref = { current: null };
  const source = {
    label: "Weather", selectedOption: "weather", onChange, ref,
    value: "Weather", src: "/Weather.gif", "data-artwork-focus": "choose-game",
    rgOptions: [{ data: "weather", label: "Weather" }],
    pages: [{ title: "Updates", route: "/gabecubeaura/settings/updates", content }, "separator"],
  };
  const result = translateUIProperties(source, "fr", (value) => typeof value === "string" ? translate(value, "fr") : value);
  assert.equal(result.label, "Météo");
  assert.deepEqual(result.rgOptions, [{ data: "weather", label: "Météo" }]);
  assert.equal(result.onChange, onChange); assert.equal(result.ref, ref);
  assert.equal(result.selectedOption, "weather"); assert.equal(result.value, "Weather");
  assert.equal(result.src, "/Weather.gif"); assert.equal(result["data-artwork-focus"], "choose-game");
  assert.deepEqual(result.pages, [{ title: "Mises à jour", route: "/gabecubeaura/settings/updates", content }, "separator"]);
  assert.equal(source.rgOptions[0].label, "Weather");
  const protectedResult = translateUIProperties({ ...source, untranslatedProps: ["label"], untranslatedOptions: true }, "fr", (value) => translate(String(value), "fr"));
  assert.equal(protectedResult.label, "Weather"); assert.equal(protectedResult.rgOptions, source.rgOptions);
  assert.ok(!("untranslatedProps" in protectedResult));
});

test("every template retains its parameters with explicit translation only for UI labels", () => {
  for (const [source, target] of Object.entries(french)) {
    const params = Array.from(source.matchAll(/\{(\d+)\}/g), (match) => match[1]);
    const translatedParams = Array.from(target.matchAll(/\{(\d+)(?::t)?\}/g), (match) => match[1]);
    assert.deepEqual(translatedParams.sort(), params.sort(), source);
    const sample = source.replace(/\{(\d+)\}/g, (_token, number) => `VALUE_${number}`);
    if (params.length) assert.equal(translate(sample, "fr"), target.replace(/\{(\d+)(?::t)?\}/g, (_token, number) => `VALUE_${number}`), source);
  }
});

test("localizing React text preserves focus identity and does not execute opaque components", () => {
  const ref = { current: null };
  const onClick = () => undefined;
  const protectedName = createElement("span", { translate: "no" }, "Weather");
  const opaque = createElement(() => { throw new Error("Must be rendered by React only"); }, { key: "opaque" });
  const source = createElement("div", { key: "focus", ref, onClick, "data-artwork-focus": "choose-game" }, "Weather", protectedName, opaque);
  const result = translateNode(source, "fr") as ReactElement<Record<string, unknown>>;
  assert.equal(result.type, source.type); assert.equal(result.key, "focus");
  assert.equal(result.props.ref, ref); assert.equal(result.props.onClick, onClick);
  assert.equal(result.props["data-artwork-focus"], "choose-game");
  const children = result.props.children as unknown[];
  assert.equal(children[0], "Météo"); assert.equal(children[1], protectedName); assert.equal(children[2], opaque);
  assert.equal((source.props.children as unknown[])[0], "Weather");
  assert.equal((translateNode(source, "en") as ReactElement<Record<string, unknown>>).props.children?.[0], "Weather");
});

test("the weather indicator localizes its condition while retaining the selected city and units", () => {
  const status = { ui_language: "fr", weather_topbar_enabled: true, weather_location: { name: "Weather" },
    weather_temperature_unit: "celsius", weather: { phase: "ready", condition: "rain", temperature_c: 12, age_s: 5 } } as Status;
  assert.equal(weatherTopBarReading(status)?.title, "Pluie · 12°C · Weather");
  assert.equal(weatherTopBarReading({ ...status, ui_language: "en" })?.title, "Rain · 12°C · Weather");
});

function jsxText(text: string): string {
  const lines = text.replace(/\t/g, " ").split(/\r\n|\n|\r/);
  const last = lines.findLastIndex((line) => line.trim());
  return lines.map((line, index) => {
    const value = (index ? line.trimStart() : line).trimEnd();
    return value ? value + (index < last ? " " : "") : "";
  }).join("").trim();
}

test("all static native labels, options and JSX copy have French coverage in both navigation modes", () => {
  const files = ["index.tsx", "weather_variants.ts", "controller_variants.ts", "event_variants.ts", "weather_icon_sets.ts", "customization_catalog.ts", "faceplate_visual_themes.ts"];
  const brand = /^(?:Decky Vocal Assistant|GabeCubeAura|JSAUX|Pixel Studio|Hi-Fi Crest|Steam|Open-Meteo|Material Rounded|Realistic V2|CPU|GPU|RGB|API|AppID|SHA256|Ctrl\+|\d|Celsius|Fahrenheit|Violet|Cyan|Hex|Legato|Nocturne|Crescendo|Supernova|Magma|Plasma|Beta|Stable|Palette|Style|Saturation|Constellation|Glacier|Impact|Aurora|Orchid|Copper|Silver|Ember|Thermal)/;
  const missing = new Set<string>();
  function check(value: string) {
    const text = value.trim();
    if (!/[a-zA-Z]/.test(text) || brand.test(text) || text === "Français / English") return;
    if (translate(text, "fr") === text && !(text in french)) missing.add(text);
  }
  for (const file of files) {
    const source = ts.createSourceFile(file, readFileSync(new URL(`../../src/${file}`, import.meta.url), "utf8"), ts.ScriptTarget.Latest, true, file.endsWith("tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    function visit(node: ts.Node) {
      if (ts.isJsxText(node)) check(jsxText(node.text));
      if (ts.isJsxAttribute(node) && ["label", "title", "description", "placeholder", "alt", "aria-label", "strTitle", "strDescription", "strOKButtonText", "strCancelButtonText"].includes(node.name.getText(source)) && node.initializer && ts.isStringLiteral(node.initializer)) check(node.initializer.text);
      if (ts.isPropertyAssignment(node) && ["label", "title", "detail"].includes(node.name.getText(source)) && ts.isStringLiteral(node.initializer)) check(node.initializer.text);
      ts.forEachChild(node, visit);
    }
    visit(source);
  }
  assert.deepEqual([...missing].sort(), [], "Untranslated UI copy");
});
