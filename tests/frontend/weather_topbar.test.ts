import test from "node:test";
import assert from "node:assert/strict";
import { weatherTopBarReading } from "../../src/weather_topbar_model";
import type { Status } from "../../src/types";

const ready = {
  weather_topbar_enabled: true,
  weather_icon_style: "phosphor-duotone",
  weather_location: { name: "Lyon", country: "France", latitude: 45.75, longitude: 4.85 },
  weather: { phase: "ready", condition: "breaks_night", temperature_c: 8.6, age_s: 32 },
} as Status;

test("top bar formats the real temperature and current condition", () => {
  assert.deepEqual(weatherTopBarReading(ready), {
    condition: "breaks_night", icon_style: "phosphor-duotone",
    text: "9°C", title: "Partly cloudy night · 9°C · Lyon",
  });
  assert.equal(weatherTopBarReading({ ...ready, weather: { ...ready.weather, temperature_c: -2.4 } })?.text, "-2°C");
  assert.equal(weatherTopBarReading({ ...ready, weather_temperature_unit: "fahrenheit" })?.text, "47°F");
  assert.equal(weatherTopBarReading({ ...ready, weather_temperature_unit: "fahrenheit",
    weather: { ...ready.weather, temperature_c: -40 } })?.text, "-40°F");
});

test("top bar carries the selected icon family and migrates missing values", () => {
  assert.equal(weatherTopBarReading(ready)?.icon_style, "phosphor-duotone");
  assert.equal(weatherTopBarReading({ ...ready, weather_icon_style: "current" })?.icon_style, "current");
  assert.equal(weatherTopBarReading({ ...ready, weather_icon_style: undefined } as unknown as Status)?.icon_style, "phosphor-duotone");
});

test("top bar never shows disabled, stale or invented temperature", () => {
  assert.equal(weatherTopBarReading({ ...ready, weather_topbar_enabled: false }), null);
  assert.equal(weatherTopBarReading({ ...ready, weather_location: null }), null);
  for (const weather of [
    { ...ready.weather, phase: "loading" as const },
    { ...ready.weather, temperature_c: null },
    { ...ready.weather, temperature_c: NaN },
    { ...ready.weather, age_s: 3600 },
  ]) assert.equal(weatherTopBarReading({ ...ready, weather }), null);
});
