import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const ui = fs.readFileSync("src/index.tsx", "utf8");
const backend = fs.readFileSync("main.py", "utf8");
test("installation failures remain visible even if status stays ready", () => {
  assert.match(ui, /setUpdateInstallError\("Installation did not start/);
  assert.match(ui, /updateInstallError && !update.error/);
  assert.match(ui, /update.phase === "error" && update.confirmation_token/);
});
test("ready packages do not lock manual refresh or channel forever", () => {
  const check = ui.slice(ui.indexOf('label="Check for updates"'), ui.indexOf('onClick={() => void runUpdateAction(checkForUpdates)}'));
  assert.ok(check.includes('"preparing_install"'));
  assert.ok(!check.includes('"ready"'));
  const channel = ui.slice(ui.indexOf('label="Update channel"'), ui.indexOf('rgOptions={UPDATE_CHANNEL_OPTIONS'));
  assert.ok(!channel.includes('"ready"'));
});
test("backup leaves Decky event loop and diagnostics exclude credentials", () => {
  const rpc = backend.slice(backend.indexOf('async def install_prepared_update'), backend.indexOf('async def set_update_preferences'));
  assert.match(rpc, /run_in_executor/);
  const snapshot = backend.slice(backend.indexOf('def _update_diagnostic_snapshot'), backend.indexOf('async def _upload_diagnostic_report'));
  assert.match(snapshot, /"error_category"/);
  assert.ok(!snapshot.includes('confirmation_token'));
  assert.ok(!snapshot.includes('private_auth'));
});
