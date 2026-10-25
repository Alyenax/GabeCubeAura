import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { faceplateUXState, installedGameChoices } from "../../src/faceplate_ux";
import type { Status } from "../../src/types";

function fixture(overrides: Record<string, unknown> = {}): Pick<Status, "faceplate" | "faceplate_lab_enabled"> {
  return {
    faceplate_lab_enabled: true,
    faceplate: {
      available: true, busy: false, powered: true,
      routing: { desired_scene: "dashboard", effective_scene: "dashboard",
        desired_content_key: "new", effective_content_key: "new",
        preparation: { state: "ready", error: "" } },
      automation: { busy: false, queued: false, last_error: "", last_result: {} },
      ...overrides,
    },
  } as Pick<Status, "faceplate" | "faceplate_lab_enabled">;
}

test("only a confirmed content key can be described as showing", () => {
  assert.equal(faceplateUXState(fixture()).tone, "good");
  const pending = fixture();
  pending.faceplate.routing.effective_content_key = "previous";
  assert.equal(faceplateUXState(pending).label, "Waiting for display confirmation");
  pending.faceplate.routing.effective_content_key = "";
  pending.faceplate.routing.desired_content_key = "";
  assert.equal(faceplateUXState(pending).tone, "waiting");
});

test("disconnected, busy, powered-off and automation-off states retain the saved choice", () => {
  assert.equal(faceplateUXState(fixture({ available: false })).label, "Faceplate not detected");
  assert.equal(faceplateUXState(fixture({ busy: true })).label, "Faceplate in use");
  assert.equal(faceplateUXState(fixture({ powered: false })).label, "Faceplate powered off");
  assert.equal(faceplateUXState({ ...fixture(), faceplate_lab_enabled: false }).label, "Automation off");
});

test("transfer errors and preparation never claim that the requested display is active", () => {
  const value = fixture();
  value.faceplate.automation.queued = true;
  assert.equal(faceplateUXState(value).label, "Applying display…");
  value.faceplate.automation.queued = false;
  value.faceplate.routing.preparation.error = "USB transfer failed";
  assert.equal(faceplateUXState(value).tone, "error");
  assert.equal(faceplateUXState(value).detail, "USB transfer failed");
});

test("installed games are browsable with no search text and filter with one character", () => {
  const games = [{ name: "Portal" }, { name: "Hades" }, { name: "Half-Life" }];
  assert.deepEqual(installedGameChoices(games, ""), games);
  assert.deepEqual(installedGameChoices(games, "p"), [games[0]]);
  assert.deepEqual(installedGameChoices(games, "  HALF  "), [games[2]]);
  assert.equal(installedGameChoices(Array.from({ length: 50 }, (_, i) => ({ name: `Game ${i}` })), "").length, 12);
});

test('a new pending transfer is not mislabeled by the previous worker error',()=>{
  const value=fixture();
  value.faceplate.routing.preparation.state='pending';
  value.faceplate.automation.queued=true;
  value.faceplate.automation.last_error='previous renderer failed';
  assert.equal(faceplateUXState(value).label,'Applying display…');
  value.faceplate.automation.busy=true;
  value.faceplate.automation.active_scene='gabe:companion';
  assert.equal(faceplateUXState(value).label,'Temporary display active');
  value.faceplate.automation.active_scene='external:presentation';
  assert.equal(faceplateUXState(value).label,'Temporary display active');
  assert.doesNotMatch(faceplateUXState(value).detail,/Gabe|assistant|voice/i);
});

test('current and historical USB errors share the same transfer classification',()=>{
  const value=fixture();
  value.faceplate.automation.last_error='no reply to type=0x01 cmd=0x0b';
  assert.equal(faceplateUXState(value).label,'Transfer not confirmed');
  value.faceplate.automation.last_error='';
  value.faceplate.routing.preparation.state='error';
  value.faceplate.routing.preparation.error='no reply to type=0x01 cmd=0x0b';
  assert.equal(faceplateUXState(value).label,'Transfer not confirmed');
});

test('fully sent data without final acknowledgement is neither confirmed nor a failed preparation',()=>{
  const value=fixture();
  value.faceplate.routing.preparation.state='unconfirmed';
  value.faceplate.routing.preparation.error='no reply to type=0x01 cmd=0x0b';
  value.faceplate.automation.busy=false; value.faceplate.automation.queued=false;
  const state=faceplateUXState(value);
  assert.equal(state.label,'Sent · confirmation unavailable');
  assert.equal(state.tone,'waiting');
  assert.ok(!state.detail.includes('Last transfer confirmed'));
});

test('stored reuse never claims a fresh payload and stored refusal is a transfer error',()=>{
  const value=fixture();
  value.faceplate.routing.preparation.state='unconfirmed';
  value.faceplate.last_transfer={already_stored:true,stored_activation_required:true};
  assert.match(faceplateUXState(value).detail,/No new GIF body was sent/);
  assert.doesNotMatch(faceplateUXState(value).detail,/All GIF data was acknowledged/);
  value.faceplate.routing.preparation.state='error';
  value.faceplate.routing.preparation.error='faceplate refused stored GIF display';
  assert.equal(faceplateUXState(value).label,'Transfer not confirmed');
});

test("private diagnostics render and load only in Advanced, never Faceplate settings", () => {
  const source = readFileSync(new URL("../../src/index.tsx", import.meta.url), "utf8");
  assert.match(source,/Capture diagnostics · 5 minutes/);
  assert.ok(source.includes('showPage("advanced") ? <SettingsPart slot="advanced.support">'));
  const fetch = source.indexOf("void getDiagnosticStatus()");
  assert.ok(fetch > 0);
  const effect = source.slice(source.lastIndexOf("useEffect(() => {", fetch), source.indexOf("}, [page]);", fetch));
  assert.ok(effect.includes('if (page !== "advanced") return;'));
  assert.ok(!effect.includes("setInterval"));
  assert.ok(!effect.includes("sendDiagnosticReport"));
  const panel = source.slice(source.indexOf('showPage("advanced") ? <SettingsPart slot="advanced.support">'), source.indexOf('{showPage("advanced") ? <SettingsPart slot={[\'advanced.general\''));
  for (const control of ["enableCaptureDiagnostic()"]) {
    assert.ok(panel.includes(control));
  }
});


test('native clock has explicit confirmed and unconfirmed copy without a GIF receipt', () => {
  const value = fixture();
  value.faceplate.routing.desired_scene = 'native-clock';
  value.faceplate.routing.effective_scene = 'native-clock';
  assert.equal(faceplateUXState(value).label, 'Native clock synchronized');
  assert.match(faceplateUXState(value).detail, /hardware check/);
  value.faceplate.routing.preparation.state = 'unconfirmed';
  assert.equal(faceplateUXState(value).tone, 'waiting');
  assert.match(faceplateUXState(value).detail, /No automatic repeat or GIF fallback/);
  assert.doesNotMatch(faceplateUXState(value).detail, /All GIF data/);
});
