import assert from "node:assert/strict";
import test from "node:test";

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
