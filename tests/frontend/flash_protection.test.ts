import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { translate } from "../../src/i18n";
import { flashProtectionFrench } from "../../src/i18n/flash_protection";
import vm from "node:vm";
import ts from "typescript";
import { createElement, Fragment } from "react";
import {FACEPLATE_HOME_OPTIONS,FACEPLATE_GAME_OPTIONS} from '../../src/faceplate_choices';

const source = readFileSync(new URL("../../src/index.tsx", import.meta.url), "utf8");
const panel = readFileSync(new URL("../../src/components/FlashProtectionPanel.tsx", import.meta.url), "utf8");

function protectionHarness() {
  let open = false;
  let settingWrites = 0;
  const context = vm.createContext({
    React: { createElement, Fragment },
    PanelSection: "section", PanelSectionRow: "row", ToggleField: "toggle", ButtonItem: "button", Localized:"localized", FaceplateDiagnostics:'diagnostics',
    useState: () => [open, (update: (old: boolean) => boolean) => { open = update(open); }],
  });
  const javascript = ts.transpileModule(panel.replace(/^import .*;\n/gm, "").replace(/export /g, ""), {
    compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInContext(javascript + "\nthis.render = FlashProtectionPanel;", context);
  const status: any = { faceplate: { flash_protection: { enabled: true, performance_unlimited: true,
    session: {}, total: {}, recent: [] }, delivery: {}, routing: {}, automation: {} } };
  const render = (collapsible = true, advanced = false): any => context.render({ status, collapsible,
    onChange: advanced ? async () => { settingWrites++; } : undefined });
  const nodes = (value: any): any[] => Array.isArray(value) ? value.flatMap(nodes)
    : value && typeof value === "object" ? [value, ...nodes(value.props?.children)] : [];
  return { render, nodes, status, writes: () => settingWrites };
}

test("Display protection details start closed, open reversibly and survive fresh status objects", () => {
  const h = protectionHarness();
  let tree = h.render();
  const button = () => h.nodes(tree).find(node => node.type === "button");
  assert.equal(button().props.children, "Show details");
  assert.equal(button().props.description, "Economy refresh on");
  assert.equal(h.nodes(tree).some(node => node.type === "details"), false);
  button().props.onClick();
  h.status.faceplate = { ...h.status.faceplate };
  tree = h.render();
  assert.equal(button().props.children, "Hide details");
  assert.equal(h.nodes(tree).some(node => node.type === "diagnostics"), true);
  button().props.onClick(); tree = h.render();
  assert.equal(button().props.children, "Show details");
  assert.equal(h.nodes(tree).some(node => node.type === "details"), false);
  assert.equal(h.writes(), 0);
});

test("Maintenance keeps its protection toggle and the closed summary hides all long counters", () => {
  const h = protectionHarness();
  const advanced = h.nodes(h.render(false, true));
  assert.equal(advanced.filter(node => node.type === "toggle").length, 1);
  assert.equal(advanced.some(node => node.type === "diagnostics"), true);
  assert.equal(advanced.some(node => node.type === "button"), false);
  const display = h.nodes(h.render());
  assert.equal(display.some(node => node.type === "toggle"), false);
  assert.equal(display.some(node => node.type === "p"), false);
  assert.match(source, /<SettingsPart slot="faceplate.protection"><FlashProtectionPanel status=\{status\} collapsible=\{!settingsView\}\s+onChange=/);
  assert.doesNotMatch(source, /Rotate Faceplate 180|setSetting\(\s*["']faceplate_rotate_180/);
});

test("the new Maintenance destination owns the single live protection toggle, without Lab wording", () => {
  assert.match(source, /slot="faceplate.protection"[\s\S]*?setSetting\('faceplate_flash_protection_enabled',enabled\)/);
  assert.match(source, /showPage\("advanced"\) && !settingsView \? <FlashProtectionPanel/);
  assert.equal((source.match(/setSetting\(['"]faceplate_flash_protection_enabled['"]/g) ?? []).length, 2);
  assert.doesNotMatch(panel, /<details|<summary/);
  assert.doesNotMatch(panel, /lab.?114|lab.?115/i);
  assert.match(panel, /onChange \? <PanelSectionRow><ToggleField/);
});

test("matrix CPU/GPU stays retired and Economy never imposes hourly or daily quotas", () => {
  assert(![...FACEPLATE_HOME_OPTIONS,...FACEPLATE_GAME_OPTIONS].some(o=>o.data==='performance'));
  assert.doesNotMatch(panel, /PERFORMANCE_ADVISORY|performance_unlimited|CPU\/GPU exempt|unrestricted update frequency/);
  assert.match(readFileSync(new URL('../../src/components/FaceplateDiagnostics.tsx',import.meta.url),'utf8'), /One animated GIF is one transfer/);
  assert.doesNotMatch(panel,/hour_limit|day_limit|capacity|refill_seconds/);
});

test("all new memory advisories and controls have nonempty French translations", () => {
  for (const [english, french] of Object.entries(flashProtectionFrench)) {
    if (english.includes("{0}")) continue;
    assert.equal(translate(english, "fr"), french);
    assert.notEqual(french, english);
  }
  assert.equal(translate("Protect faceplate memory", "en"), "Protect faceplate memory");
});

test("public recovery keeps the verified previous version and removes the private pinned baseline", () => {
  assert.match(source, /runUpdateAction\(preparePreviousVersion\)/);
  assert.doesNotMatch(source, /Return to Lab 114/);
  assert.match(source, /recovery_preserves_current_settings/);
});

test("Economy copy states exact battery and clock behaviour and leaves useful counters",()=>{
 const h=protectionHarness();const nodes=h.nodes(h.render(false,true));
 const help=nodes.find(node=>typeof node.props?.children==='string'&&node.props.children.includes('77% → 75%'));
 assert(help,'The explanation must be visible, not hidden in the settings help modal');
 assert.match(help.props.children,/5-minute.*14:03 → 14:00/);
 assert.match(help.props.children,/Off: exact percentages and one-minute/);
 assert.equal(nodes.filter(node=>node.type==='diagnostics').length,1);
 assert.doesNotMatch(panel,/Hardware endurance is unknown|Uncertain transactions:|Visible playback: unknown/);
});
