import test from "node:test";
import assert from "node:assert/strict";
import { buildSettingsSnapshot } from "../../src/settings_snapshot";
import type { Status } from "../../src/types";

const sampleStatus = {
    version: "0.5.0-beta.9",
    default_mode: "artwork", mode: "performance", display_override: "performance",
    signalbar_enabled: true, home_display: "controller", game_display: "performance",
    current_display: "performance",
    led_output_calibration_mode: "consistent",
    led_output_calibration: { reference_brightness: 9, detected_brightness: 9 },
    game: { appid: 42, title: "Example Game" },
    artwork_default_source: "hero", artwork_default_mode: "auto", artwork_default_manual_y: .5, artwork_default_vibrance: 100,
    artwork_source: "header", artwork_mode: "manual", artwork_manual_y: .83, artwork_vibrance: 145, artwork_custom: true,
    launch_artwork_animation_enabled: true, launch_artwork_pattern: "crescendo",
    launch_artwork_colour_count: 2, launch_artwork_duration_seconds: 20,
    launch_artwork_source: "hero", launch_artwork_palette_mode: "custom",
    launch_artwork_custom_palettes: { "2": [[255, 220, 0], [0, 220, 255]], "3": [[255, 220, 0], [0, 220, 255], [255, 0, 90]] },
    customization_pattern: "steady", customization_colour_count: 2,
    customization_colour_1: [255, 200, 0], customization_colour_2: [0, 180, 255], customization_colour_3: [255, 0, 120],
    customization_brightness: 128, customization_speed: 50, customization_direction: "forward",
    screen_sync_style: "panorama", screen_sync_brightness: 160,
    screen_sync_reactivity: "balanced", screen_sync_colour_intensity: "natural",
    screen_sync_black_threshold: 8, screen_sync_ignore_black_bars: true,
    screen_sync_screensaver_enabled: true,
    screen_sync: { activation: { reason: "game-route" } },
    audio_sync_style: "spectrum", audio_sync_brightness: 160,
    audio_sync_reactivity: "balanced", audio_sync_palette: "aurora",
    audio_sync_home_style: "hifi-crest", audio_sync_home_palette: "pearl",
    audio_sync_game_style: "stereo-lanterns", audio_sync_game_palette: "artwork",
    audio_sync_hifi_lab_enabled: true,
    audio_sync_lab_crest_strength: 125, audio_sync_lab_edge_reach: 140, audio_sync_lab_background: 70,
    audio_sync_home_colour_low: [99, 135, 233], audio_sync_home_colour_middle: [78, 118, 228], audio_sync_home_colour_high: [78, 118, 228],
    audio_sync_game_colour_low: [11, 94, 142], audio_sync_game_colour_middle: [8, 127, 191], audio_sync_game_colour_high: [26, 159, 255],
    performance_metric: "mixed", performance_smoothing: "balanced", performance_always: true,
    mixed_direction: "mirrored", temperature_palette: "custom",
    cool_temp_c: 45, hot_temp_c: 80,
    temperature_custom_cool: [12, 34, 56], temperature_custom_middle: [120, 130, 140], temperature_custom_hot: [255, 0, 9],
    parental_countdown_enabled: true, countdown_colour: "cyan", countdown_full_bar_minutes: 120, free_timer_minutes: 45,
    events_enabled: true, event_notifications_enabled: true, event_achievements_enabled: false,
    event_screenshots_enabled: true, event_recording_enabled: true, recording_marker_isolation: true,
    event_notification_variant: "notification-echo", event_achievement_variant: "achievement-confetti",
    event_screenshot_variant: "screenshot-bloom",
    controller_battery_display: "everywhere", controller_alerts_enabled: true, controller_alert_context: "both",
    controller_charging_mode: "continuous-home", controller_low_threshold: 20,
    controller_connect_enabled: true, controller_low_enabled: true,
    controller_connect_variant: "orbit", controller_persistent_variant: "tip",
    controller_low_variant: "drain", controller_charging_variant: "current", controller_duo_variant: "twin",
    controller_colour_preset: "automatic", controller_colour_mode: "battery",
    controller_gauge_brightness: 65,
    controller_colour_normal: [0, 200, 25], controller_colour_medium: [240, 120, 0],
    controller_colour_low: [220, 12, 24], controller_colour_charging: [0, 80, 180],
    controller_player_colour_1: [36, 199, 245], controller_player_colour_2: [255, 167, 26],
    controller_player_colour_3: [106, 26, 255], controller_player_colour_4: [70, 210, 136],
    weather_display: "off", weather_location: null, weather_topbar_enabled: false,
    weather_icon_style: "current",
    weather_brightness: 65, weather_shadow_cutoff: 25,
    weather_clear_day_variant: 0, weather_clear_night_variant: 0, weather_rain_variant: 0,
    weather_cloud_variant: 0, weather_cloud_night_variant: 0, weather_breaks_variant: 0, weather_breaks_night_variant: 0, weather_snow_variant: 0, weather_storm_variant: 0,
    reverse_led_order: true, countdown_dark_edge_compensation: 2,
    debug: { led_path: "/private/device/path" },
} as unknown as Status;

test("debug snapshot includes every settings group and distinguishes defaults from the running game's choices", () => {
  const snapshot = buildSettingsSnapshot(sampleStatus);
  assert.deepEqual(snapshot.map((section) => section.title),
    ["Display", "Customization+", "Artwork", "Performance", "Screen Sync", "Audio Sync", "Game launches", "Playtime", "Light events", "Controllers", "Weather", "Advanced"]);
  const text = snapshot.flatMap((section) => section.lines).join("\n");
  for (const expected of ["Example Game", "Library Hero", "Library Header", "83%", "CPU + GPU",
    "Balanced", "Mirrored", "#0C2238", "2 h", "Centre echo", "Return + confetti",
    "Expanding echoes", "Continuous on Home", "Bright tip", "#00C819", "Pattern steady", "Brightness 128/255",
    "Style panorama", "Black threshold 8", "Home pattern hifi-crest", "Palette pearl",
    "In-game pattern stereo-lanterns", "Palette artwork", "automatic level matching", "strength 125%", "edge reach 140%",
    "#6387E9", "#0B5E8E",
    "background 70%", "colour intensity 145%", "Weather LED brightness 65%", "Extra dark LEDs 2",
    "Consistent output 9/255"]) {
    assert.ok(text.includes(expected), expected);
  }
  assert.ok(!text.includes("/private/device/path"));
  assert.ok(!text.includes("42"));
});

test("snapshot shows Home defaults without inventing a game-specific profile", () => {
  const status = { ...sampleStatus,
    game: { appid: 0, title: "" },
    default_mode: "artwork", mode: "artwork", display_override: "inherit",
    home_display: "steam", game_display: "artwork", current_display: "steam",
    artwork_default_source: "hero", artwork_default_mode: "auto", artwork_default_manual_y: .5, artwork_default_vibrance: 100,
    artwork_source: "hero", artwork_mode: "auto", artwork_manual_y: .5, artwork_vibrance: 100, artwork_custom: false,
  } as Status;
  const snapshot = buildSettingsSnapshot(status);
  assert.match(snapshot[0].lines[2], /^Home/);
  assert.match(snapshot[2].lines[1], /^This game: none/);
});

test("snapshot names the GabeCubeAura Off display route", () => {
  const status = { ...sampleStatus,
    game: { appid: 42, title: "StripMine" },
    game_display: "steam", current_display: "steam", mode: "events", display_override: "inherit",
  } as Status;
  const snapshot = buildSettingsSnapshot(status);
  assert.ok(snapshot[0].lines[0].includes("GabeCubeAura Off"));
});

test("weather snapshot lists retained loops without removed temperature controls", () => {
  const snapshot = buildSettingsSnapshot({ ...sampleStatus, weather_rain_variant: 1 });
  const weather = snapshot.find((section) => section.title === "Weather");
  assert.ok(weather?.lines.some((line) => line.includes("rain: Pearl rain")));
  assert.ok(!weather?.lines.some((line) => /Temperature|halos/i.test(line)));
});
