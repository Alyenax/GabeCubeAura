import test from "node:test";
import assert from "node:assert/strict";

import {
  FACEPLATE_BASE_VISUAL_THEME_OPTIONS,
  FACEPLATE_DASHBOARD_VISUAL_THEME_OPTIONS,
  FACEPLATE_WEATHER_VISUAL_THEME_OPTIONS,
  weatherPreviewMeta,
} from "../../src/faceplate_visual_themes";

test("Weather and Dashboard expose only the current Realistic", () => {
  const base = FACEPLATE_BASE_VISUAL_THEME_OPTIONS.map((option) => option.data);
  const weather = FACEPLATE_WEATHER_VISUAL_THEME_OPTIONS.map((option) => option.data);
  const dashboard = FACEPLATE_DASHBOARD_VISUAL_THEME_OPTIONS.map((option) => option.data);

  assert.deepEqual(base, [
    "integrated", "night-paper-v3", "night-paper", "sun-cut", "winter-loom",
  ]);
  assert.deepEqual(weather, ["weather-artwork-v2"]);
  assert.deepEqual(dashboard, ["weather-artwork-v2"]);
  assert.equal(new Set(weather).size, weather.length);
});

test("weather preview metadata distinguishes live/sample and exact/fallback honestly", () => {
  assert.deepEqual(weatherPreviewMeta({
    data_uri: "", error: "", live_weather: true,
    visual_theme: "weather-artwork-v2",
    collection_revision: "weather-artwork-v2-runtime-4",
    selection_status: "exact", preset_id: "rain:0",
    variant_name: "Bluewater", source_scene: "Neon Harbor",
  }, true), [
    "live temperature", "Realistic",
    "weather-artwork-v2-runtime-4", "exact palette match",
    "Bluewater", "Neon Harbor",
  ]);
  assert.deepEqual(weatherPreviewMeta({
    data_uri: "", error: "", live_weather: false,
    selection_status: "fallback",
  }, true), ["sample temperature", "fallback renderer"]);
});
