import assert from "node:assert/strict";
import test from "node:test";

import {
  isSteamLEDManagerTransport,
  isSteamLEDModeOverrideService,
  STEAM_LED_MODE_CUSTOMIZE,
  STEAM_LED_MODE_DOWNLOAD,
  STEAM_LED_MODE_IDLE,
  SteamDownloadLedOverride,
} from "../../src/steam_led_manager";

test("LED manager discovery requires only the exact private capabilities", () => {
  assert.equal(isSteamLEDModeOverrideService({ RequestModeOverride() {} }), true);
  assert.equal(isSteamLEDModeOverrideService({ SetManagerMode() {} }), false);
  assert.equal(isSteamLEDManagerTransport({ GetState() {}, SetManagerMode() {} }), true);
  assert.equal(isSteamLEDManagerTransport({ SetManagerMode() {} }), false);
});

test("protected download mode is reversible and reasserts Customize", async () => {
  const modes: number[] = [];
  let releases = 0;
  const controller = new SteamDownloadLedOverride(
    () => ({
      RequestModeOverride(mode) {
        modes.push(mode);
        return () => { releases += 1; };
      },
    }),
    () => ({
      GetState() {},
      SetManagerMode({ mode }) { modes.push(mode); },
    }),
  );

  assert.equal(await controller.update(true, false), "blocked");
  assert.equal(await controller.update(true, false), "blocked");
  assert.deepEqual(modes, [
    STEAM_LED_MODE_CUSTOMIZE,
    STEAM_LED_MODE_CUSTOMIZE,
    STEAM_LED_MODE_CUSTOMIZE,
  ]);
  assert.equal(releases, 0);
  assert.equal(await controller.update(false, false), "inactive");
  assert.equal(releases, 1);
  controller.stop();
  assert.equal(releases, 1);
});

test("unknown Steam builds are left untouched", async () => {
  let transportCalls = 0;
  const controller = new SteamDownloadLedOverride(
    () => undefined,
    () => ({
      GetState() {},
      SetManagerMode() { transportCalls += 1; },
    }),
  );
  assert.equal(await controller.update(true, false), "unavailable");
  assert.equal(transportCalls, 0);
});

test("a Steam transport failure releases the override", async () => {
  let releases = 0;
  const controller = new SteamDownloadLedOverride(
    () => ({
      RequestModeOverride() { return () => { releases += 1; }; },
    }),
    () => ({
      GetState() {},
      SetManagerMode() { throw new Error("transport closed"); },
    }),
  );
  assert.equal(await controller.update(true, false), "error");
  assert.equal(releases, 1);
});

test("a rejected Steam response releases the override", async () => {
  let releases = 0;
  const controller = new SteamDownloadLedOverride(
    () => ({
      RequestModeOverride() { return () => { releases += 1; }; },
    }),
    () => ({
      GetState() {},
      SetManagerMode() { return { BSuccess: () => false }; },
    }),
  );
  assert.equal(await controller.update(true, false), "error");
  assert.equal(releases, 1);
});

test("Downloads plus safety restores Download after releasing Customize", async () => {
  const events: string[] = [];
  const controller = new SteamDownloadLedOverride(
    () => ({
      RequestModeOverride(mode) {
        events.push(`override:${mode}`);
        return () => { events.push("release"); };
      },
    }),
    () => ({
      GetState() {},
      SetManagerMode({ mode }) { events.push(`mode:${mode}`); },
    }),
  );

  assert.equal(await controller.update(true, false), "blocked");
  assert.equal(await controller.update(false, true), "download");
  assert.equal(await controller.update(false, true), "download");
  assert.equal(await controller.update(false, false), "inactive");
  assert.deepEqual(events, [
    `override:${STEAM_LED_MODE_CUSTOMIZE}`,
    `mode:${STEAM_LED_MODE_CUSTOMIZE}`,
    "release",
    `mode:${STEAM_LED_MODE_DOWNLOAD}`,
    `mode:${STEAM_LED_MODE_IDLE}`,
  ]);
});

test("Downloads plus safety uses no crash-sensitive override", async () => {
  const modes: number[] = [];
  let overrideCalls = 0;
  const controller = new SteamDownloadLedOverride(
    () => ({
      RequestModeOverride() {
        overrideCalls += 1;
        return () => undefined;
      },
    }),
    () => ({
      GetState() {},
      SetManagerMode({ mode }) { modes.push(mode); },
    }),
  );
  assert.equal(await controller.update(false, true), "download");
  assert.equal(await controller.update(false, true), "download");
  assert.deepEqual(modes, [STEAM_LED_MODE_DOWNLOAD]);
  assert.equal(await controller.update(false, false), "inactive");
  assert.deepEqual(modes, [STEAM_LED_MODE_DOWNLOAD, STEAM_LED_MODE_IDLE]);
  assert.equal(overrideCalls, 0);
});

test("startup recovery releases a remembered Safety override and resets Idle", async () => {
  let releases = 0;
  const first = new SteamDownloadLedOverride(
    () => ({
      RequestModeOverride() {
        return () => { releases += 1; };
      },
    }),
    () => ({ GetState() {}, SetManagerMode() {} }),
  );
  assert.equal(await first.update(true, false), "blocked");

  const modes: number[] = [];
  const restarted = new SteamDownloadLedOverride(
    () => undefined,
    () => ({
      GetState() {},
      SetManagerMode({ mode }) { modes.push(mode); },
    }),
  );
  assert.equal(await restarted.recoverAfterRestart(), "inactive");
  assert.equal(releases, 1);
  assert.deepEqual(modes, [STEAM_LED_MODE_IDLE]);
  first.stop();
  assert.equal(releases, 1);
});
