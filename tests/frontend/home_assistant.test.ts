import assert from "node:assert/strict";
import test from "node:test";

import { connectionLine, type ConnectionStatus } from "../../src/home_assistant_status";
import {
  DRIVE_NOTE, FACEPLATE_LEVEL_OPTIONS, HOME_ASSISTANT_DISPLAY, LEVEL_OPTIONS, PRESET_NOTE, levelRows,
  withHomeAssistantDisplay,
} from "../../src/home_assistant_levels";

test("the levels match the backend's names and the faceplate stops at settings", () => {
  assert.deepEqual(LEVEL_OPTIONS.map((option) => option.data), ["report", "settings", "drive"]);
  assert.deepEqual(FACEPLATE_LEVEL_OPTIONS.map((option) => option.data), ["report", "settings"]);
  assert.match(DRIVE_NOTE, /turning it off puts your display back/);
});

test("only the drive level offers the display, and the note names the Custom preset", () => {
  assert.match(PRESET_NOTE, /Custom preset/);
  const options = [{ data: "steam", label: "GabeCubeAura Off" }];
  assert.deepEqual(withHomeAssistantDisplay(options, false, "steam"), options);
  assert.deepEqual(withHomeAssistantDisplay(options, true, "steam"), [...options, HOME_ASSISTANT_DISPLAY]);
  // Still listed while selected, so the dropdown never shows a blank choice.
  assert.deepEqual(withHomeAssistantDisplay(options, false, "home_assistant"), [...options, HOME_ASSISTANT_DISPLAY]);
  assert.deepEqual(levelRows({ connected: false, connected_with_current_settings: true, faceplate_controls: false }),
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
