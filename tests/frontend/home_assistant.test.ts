import assert from "node:assert/strict";
import test from "node:test";

import { connectionLine, type ConnectionStatus } from "../../src/home_assistant_status";
import { LEVEL_OPTIONS, PRESET_NOTE, levelRows } from "../../src/home_assistant_levels";

test("the levels match the backend's names, Report only first", () => {
  assert.deepEqual(LEVEL_OPTIONS.map((option) => option.data), ["report", "settings"]);
});

test("the level rows grey out while reconnecting and the note names the Custom preset", () => {
  assert.match(PRESET_NOTE, /Custom preset/);
  assert.equal(levelRows({ connected: true, connected_with_current_settings: false, faceplate_controls: false }).visible,
    false);
  assert.deepEqual(levelRows({ connected: false, connected_with_current_settings: true, faceplate_controls: false }),
    { visible: true, disabled: true, note: "Reconnecting...", faceplate: false });
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
