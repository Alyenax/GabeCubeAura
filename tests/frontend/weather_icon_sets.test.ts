import test from "node:test";
import assert from "node:assert/strict";
import { WEATHER_ICON_STYLE_OPTIONS, weatherIconSvg } from "../../src/weather_icon_sets";
import type { WeatherCondition } from "../../src/types";

const conditions: WeatherCondition[] = [
  "clear_day", "clear_night", "rain", "cloud", "cloud_night",
  "breaks", "breaks_night", "snow", "storm",
];

test("all three local icon families cover every weather condition", () => {
  assert.deepEqual(
    WEATHER_ICON_STYLE_OPTIONS.map((option) => option.data),
    ["current", "material-rounded", "phosphor-duotone"],
  );
  for (const style of WEATHER_ICON_STYLE_OPTIONS) {
    for (const condition of conditions) {
      const svg = weatherIconSvg(style.data, condition);
      assert.match(svg, /^<svg\b/);
      assert.match(svg, /aria-hidden="true"/);
      assert.doesNotMatch(svg, /<script\b|(?:href|src)="https?:\/\//i);
    }
  }
});

test("embedded SVG identifiers are unique and every local reference resolves", () => {
  const seen = new Set<string>();
  for (const style of WEATHER_ICON_STYLE_OPTIONS) {
    for (const condition of conditions) {
      const svg = weatherIconSvg(style.data, condition);
      const ids = [...svg.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
      for (const id of ids) {
        assert.equal(seen.has(id), false, id);
        seen.add(id);
      }
      for (const reference of svg.matchAll(/(?:url\(#|href="#)([^)"]+)/g)) {
        assert.ok(ids.includes(reference[1]), `${style.data}:${condition}:${reference[1]}`);
      }
    }
  }
});
