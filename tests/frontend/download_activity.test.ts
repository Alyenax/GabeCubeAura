import assert from "node:assert/strict";
import test from "node:test";

import {
  downloadItemsActive,
  downloadOverviewActive,
  resolveDownloadActivity,
} from "../../src/download_activity";

test("download overview recognizes only a real active Steam state", () => {
  assert.equal(downloadOverviewActive({ update_state: "Downloading" }), true);
  assert.equal(downloadOverviewActive({ update_state: "None" }), false);
  assert.equal(downloadOverviewActive({}), false);
  assert.equal(downloadOverviewActive(null), false);
});

test("download item replay distinguishes active transfers from scheduled work", () => {
  assert.equal(downloadItemsActive([{
    remote_client_id: "local",
    item_data: [{ active: true, completed: false, deferred_time: 0 }],
  }]), true);
  assert.equal(downloadItemsActive([{
    remote_client_id: "local",
    item_data: [{ active: false, completed: false, deferred_time: 1790000000 }],
  }]), false);
  assert.equal(downloadItemsActive([{
    remote_client_id: "local",
    item_data: [{ active: true, completed: true, deferred_time: 0 }],
  }]), false);
  // Steam's first callback argument means the list changed. It is not a
  // download state and must never suspend GabeCubeAura by itself.
  assert.equal(downloadItemsActive(true), false);
  assert.equal(downloadItemsActive(undefined), false);
});

test("the detailed item replay remains authoritative regardless of callback order", () => {
  assert.deepEqual(
    resolveDownloadActivity(true, false, false),
    { active: true, source: "overview" },
  );
  assert.deepEqual(
    resolveDownloadActivity(true, false, true),
    { active: false, source: "items" },
  );
  assert.deepEqual(
    resolveDownloadActivity(false, true, true),
    { active: true, source: "items" },
  );
  assert.deepEqual(
    resolveDownloadActivity(true, true, true),
    { active: true, source: "items" },
  );
});
