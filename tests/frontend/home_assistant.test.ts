import assert from "node:assert/strict";
import test from "node:test";

import { connectionLine, type ConnectionStatus } from "../../src/home_assistant_status";
import {
  FACEPLATE_TIER_OPTIONS, FALLBACK_LABEL, FULL_CONTROL_CONFIRM, HOME_ASSISTANT_DISPLAY, TIER_EXPLAINERS, TIER_OPTIONS,
  fallbackLine, lightBarTierChange, lightNote, showsFallback, tierDescription, tierRows, withHomeAssistantDisplay,
} from "../../src/home_assistant_tiers";

test("the five tiers match the backend's names and the faceplate stops at Help out", () => {
  assert.deepEqual(TIER_OPTIONS.map((option) => [option.data, option.label]), [
    [1, "Watch only"], [2, "Help out"], [3, "Take the lead"], [4, "In control"], [5, "Full control"]]);
  assert.deepEqual(FACEPLATE_TIER_OPTIONS.map((option) => option.data), [1, 2]);
  assert.match(TIER_EXPLAINERS[4], /urgent warnings/);
  assert.match(TIER_EXPLAINERS[5], /Steam still shows its own animations, like downloads/);
});

test("the fallback switch shows from Take the lead up, and the page says when it has taken over", () => {
  assert.deepEqual(([1, 2, 3, 4, 5] as const).map(showsFallback), [false, false, true, true, true]);
  assert.equal(FALLBACK_LABEL, "When Home Assistant is unreachable, let GabeCubeAura take over");
  const taken = fallbackLine({ falling_back: true });
  assert.match(taken, /unreachable/);
  assert.equal(tierDescription("Reconnecting…", taken, 3), `Reconnecting… ${taken}`);
  assert.equal(tierDescription("", fallbackLine({ falling_back: false }), 3), TIER_EXPLAINERS[3]);
});

test("Full control asks first and turns the fallback off in the same save", () => {
  assert.equal(FULL_CONTROL_CONFIRM,
    "Home Assistant takes over everything, including overheating and playtime warnings. Continue?");
  assert.deepEqual(lightBarTierChange(5, true),
    { changes: { light_bar_tier: 5, ha_fallback: false }, confirm: FULL_CONTROL_CONFIRM });
  assert.deepEqual(lightBarTierChange(4, true), { changes: { light_bar_tier: 4 }, confirm: "" });
});

test("only Help out offers the display and says the light changes it", () => {
  assert.match(lightNote(2), /Custom preset/);
  assert.match(lightNote(4), /never changes your Home or game display/);
  const options = [{ data: "steam", label: "GabeCubeAura Off" }];
  assert.deepEqual(withHomeAssistantDisplay(options, false, "steam"), options);
  // Still listed while selected, so the dropdown never shows a blank choice.
  assert.deepEqual(withHomeAssistantDisplay(options, false, "home_assistant"), [...options, HOME_ASSISTANT_DISPLAY]);
  assert.deepEqual(tierRows({ connected: false, connected_with_current_settings: true, faceplate_controls: false }),
    { visible: true, disabled: true, note: "Reconnecting…", faceplate: false });
});

test("the status line names the broker, the user and the last failure", () => {
  const base: ConnectionStatus = {
    phase: "connecting", reason: "Broker name not found", retry_in_s: null, broker: "192.0.2.10:1883", username: "",
    topic_root: "gabecubeaura/steammachine",
  };
  assert.equal(connectionLine(false, base), "Off");
  assert.equal(connectionLine(true, base), "Connecting to 192.0.2.10:1883… Last attempt: Broker name not found.");
  assert.equal(connectionLine(true, { ...base, phase: "connected" }),
    "Connected as anonymous, publishing under gabecubeaura/steammachine");
  const waiting = { ...base, phase: "waiting_retry" as const, reason: "Wrong username or password", retry_in_s: 12.3 };
  assert.equal(connectionLine(true, waiting), "Wrong username or password, retrying in 13 s");
  assert.equal(connectionLine(true, waiting, 5), "Wrong username or password, retrying in 8 s");
  assert.equal(connectionLine(true, waiting, 20), "Wrong username or password, retrying now…");
});
