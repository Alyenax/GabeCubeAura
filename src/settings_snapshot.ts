import { CONTROLLER_VARIANTS } from "./controller_variants";
import { EVENT_VARIANTS } from "./event_variants";
import { WEATHER_VARIANTS } from "./weather_variants";
import type { Status } from "./types";

export interface SettingsSnapshotSection {
  title: string;
  lines: string[];
}

const onOff = (value: boolean) => value ? "On" : "Off";
const percent = (value: number) => `${Math.round(value * 100)}%`;
const rgbHex = (value: [number, number, number]) =>
  `#${value.map((channel) => channel.toString(16).padStart(2, "0")).join("").toUpperCase()}`;
const selectedLabel = (options: readonly { data: string; label: string }[], value: string) =>
  options.find((option) => option.data === value)?.label ?? value;

const artworkSource = { hero: "Library Hero", header: "Library Header", capsule: "Library Capsule" };
const artworkRow = { auto: "Auto", center: "Centre", lower: "Lower", manual: "Manual" };
const displayMode = {
  artwork: "Artwork", performance: "Performance", customization: "Customization+", screen_sync: "Screen Sync", audio_sync: "Audio Sync", steam: "GabeCubeAura Off", blackout: "Blackout",
  weather: "Weather", controller: "Controller status", events: "Signals only", disabled: "Disabled",
};
const response = { responsive: "Responsive", balanced: "Balanced", smooth: "Smooth" };
const palette = {
  thermal: "Cyan → amber → red", classic: "Green → yellow → red",
  icefire: "Blue → violet → pink", custom: "Custom colours",
};
const alertContext = { off: "Off", home: "Home", game: "In game", both: "Home + in game" };
const chargingMode = {
  off: "Off", brief: "Brief (~3 s)",
  "continuous-home": "Continuous on Home", "continuous-everywhere": "Continuous everywhere",
};

/** One concise, read-only view of the settings exposed across the Decky tabs. */
export function buildSettingsSnapshot(status: Status): SettingsSnapshotSection[] {
  const gameRunning = status.game.appid > 0 || Boolean(status.game.title);
  const source = (value: Status["artwork_source"]) => artworkSource[value];
  const row = (value: Status["artwork_mode"]) => artworkRow[value];
  const controller = (kind: keyof typeof CONTROLLER_VARIANTS, value: string) =>
    selectedLabel(CONTROLLER_VARIANTS[kind], value);
  const event = (kind: keyof typeof EVENT_VARIANTS, value: string) =>
    selectedLabel(EVENT_VARIANTS[kind], value);
  return [
    {
      title: "Display",
      lines: [
        `Home ${displayMode[status.home_display]} · In game ${displayMode[status.game_display]} · Current ${displayMode[status.current_display]} · Master ${onOff(status.signalbar_enabled)}`,
        `Light bar Day ${status.light_bar_day_brightness}/255 · Night ${status.night_mode_brightness}% · ${status.light_bar_brightness.control_mode}`,
        gameRunning
          ? `Game ${status.game.title || "Running game"} · Override ${status.display_override === "inherit" ? "Use in-game default" : displayMode[status.display_override]}`
          : "Home · Game override applies when a game runs",
      ],
    },
    {
      title: "Customization+",
      lines: [
        `Pattern ${status.customization_pattern} · Palette ${status.customization_colour_count} colour${status.customization_colour_count === 1 ? "" : "s"}`,
        `Colours ${[status.customization_colour_1, status.customization_colour_2, status.customization_colour_3].slice(0, status.customization_colour_count).map(rgbHex).join(" / ")} · Brightness ${status.customization_brightness}/255 · Speed ${status.customization_speed}/100 · ${status.customization_direction}`,
      ],
    },
    {
      title: "Artwork",
      lines: [
        `Default ${source(status.artwork_default_source)} · ${row(status.artwork_default_mode)} · saved manual ${percent(status.artwork_default_manual_y)} · colour intensity ${status.artwork_default_vibrance}%`,
        gameRunning
          ? `This game ${source(status.artwork_source)} · ${row(status.artwork_mode)} · manual ${percent(status.artwork_manual_y)} · colour intensity ${status.artwork_vibrance}% · profile ${status.artwork_custom ? "saved" : "default"}`
          : "This game: none; defaults shown above",
      ],
    },
    {
      title: "Performance",
      lines: [
        `Meter ${status.performance_metric === "mixed" ? "CPU + GPU" : status.performance_metric.toUpperCase()} · Response ${response[status.performance_smoothing]} · Home ${onOff(status.performance_always)}`,
        `Fill ${status.mixed_direction === "mirrored" ? "Mirrored" : "Both left to right"} (saved) · Palette ${palette[status.temperature_palette]}`,
        `Cool ${status.cool_temp_c}°C · Hot ${status.hot_temp_c}°C · saved custom ${rgbHex(status.temperature_custom_cool)} / ${rgbHex(status.temperature_custom_middle)} / ${rgbHex(status.temperature_custom_hot)}`,
      ],
    },
    {
      title: "Screen Sync",
      lines: [
        `Style ${status.screen_sync_style} · Reactivity ${status.screen_sync_reactivity} · Colours ${status.screen_sync_colour_intensity}`,
        `Brightness ${status.screen_sync_brightness}/255 · Black threshold ${status.screen_sync_black_threshold} · Ignore black bars ${onOff(status.screen_sync_ignore_black_bars)}`,
        `Steam screensaver ${onOff(status.screen_sync_screensaver_enabled)} · Activation ${status.screen_sync.activation.reason || "waiting"}`,
      ],
    },
    {
      title: "Audio Sync",
      lines: [
        `Home pattern ${status.audio_sync_home_style} · Palette ${status.audio_sync_home_palette}`,
        `In-game pattern ${status.audio_sync_game_style} · Palette ${status.audio_sync_game_palette}`,
        `Shared reactivity ${status.audio_sync_reactivity} · Brightness ${status.audio_sync_brightness}/255 · automatic level matching`,
        `Hi-Fi Crest Lab ${onOff(status.audio_sync_hifi_lab_enabled)} · strength ${status.audio_sync_lab_crest_strength}% · edge reach ${status.audio_sync_lab_edge_reach}% · background ${status.audio_sync_lab_background}%`,
        `Home custom colours ${rgbHex(status.audio_sync_home_colour_low)} / ${rgbHex(status.audio_sync_home_colour_middle)} / ${rgbHex(status.audio_sync_home_colour_high)}`,
        `In-game custom colours ${rgbHex(status.audio_sync_game_colour_low)} / ${rgbHex(status.audio_sync_game_colour_middle)} / ${rgbHex(status.audio_sync_game_colour_high)}`,
      ],
    },
    {
      title: "Game launches",
      lines: [
        `Master ${onOff(status.launch_artwork_animation_enabled)} · ${status.launch_artwork_pattern} · ${status.launch_artwork_duration_seconds} s`,
        `Source ${source(status.launch_artwork_source)} · Palette ${status.launch_artwork_colour_count} colours · ${status.launch_artwork_palette_mode}`,
      ],
    },
    {
      title: "Playtime",
      lines: [
        `Steam Families ${onOff(status.parental_countdown_enabled)} · Start ${status.countdown_colour} · Full bar ${status.countdown_full_bar_minutes === 0 ? "timer duration" : `${status.countdown_full_bar_minutes / 60} h`}`,
        `Personal timer preset ${status.free_timer_minutes} min`,
      ],
    },
    {
      title: "Light events",
      lines: [
        `Master ${onOff(status.events_enabled)} · Notifications ${onOff(status.event_notifications_enabled)}: ${event("notification", status.event_notification_variant)}`,
        `Achievements ${onOff(status.event_achievements_enabled)}: ${event("achievement", status.event_achievement_variant)}`,
        `Screenshots ${onOff(status.event_screenshots_enabled)}: ${event("screenshot", status.event_screenshot_variant)}`,
        `Recording ${onOff(status.event_recording_enabled)} · Red marker isolation ${onOff(status.recording_marker_isolation)}`,
      ],
    },
    {
      title: "Controllers",
      lines: [
        `Gauge ${status.controller_battery_display === "home" ? "On Home" : status.controller_battery_display === "game" ? "In game" : status.controller_battery_display === "everywhere" ? "Everywhere" : "Off"} · Brief alerts ${onOff(status.controller_alerts_enabled)} · Where ${alertContext[status.controller_alert_context]}`,
        `Charging ${chargingMode[status.controller_charging_mode]} · Low warning ≤${status.controller_low_threshold}%`,
        `Connect ${onOff(status.controller_connect_enabled)}: ${controller("connect", status.controller_connect_variant)} · Single ${controller("persistent", status.controller_persistent_variant)}`,
        `Low ${onOff(status.controller_low_enabled)}: ${controller("low", status.controller_low_variant)} · Charge style ${controller("charging", status.controller_charging_variant)}`,
        `Multiple controllers ${controller("duo", status.controller_duo_variant)} · Brightness ${status.controller_gauge_brightness}% · Colour preset ${status.controller_colour_preset === "automatic" ? "Automatic" : "Manual"}`,
        status.controller_colour_preset === "automatic"
          ? "Automatic rule 1 controller: battery level · 2 to 4 controllers: player seats"
          : `Manual colour meaning ${status.controller_colour_mode === "players" ? "Player seats" : "Battery level"}`,
        `Battery colours healthy ${rgbHex(status.controller_colour_normal)} · medium ${rgbHex(status.controller_colour_medium)} · low ${rgbHex(status.controller_colour_low)} · charge ${rgbHex(status.controller_colour_charging)}`,
        `Seats P1 ${rgbHex(status.controller_player_colour_1)} · P2 ${rgbHex(status.controller_player_colour_2)} · P3 ${rgbHex(status.controller_player_colour_3)} · P4 ${rgbHex(status.controller_player_colour_4)}`,
      ],
    },
    {
      title: "Weather",
      lines: [
        `City ${status.weather_location ? `${status.weather_location.name}, ${status.weather_location.country}` : "none"} · Display ${status.weather_display}`,
        `SteamOS top bar ${onOff(status.weather_topbar_enabled)} · Icons ${status.weather_icon_style} · ${status.weather_temperature_unit === "fahrenheit" ? "Fahrenheit" : "Celsius"}`,
        `Weather LED brightness ${status.weather_brightness}% · Faint LED cutoff ${status.weather_shadow_cutoff} (linear RGB)`,
        ...(["clear_day", "clear_night", "rain", "cloud", "cloud_night", "breaks", "breaks_night", "snow", "storm"] as const).map((condition) =>
          `${condition.replace("_", " ")}: ${WEATHER_VARIANTS[condition][status[`weather_${condition}_variant`]]?.label ?? "unknown"}`),
      ],
    },
    {
      title: "Advanced",
      lines: [
        `Reverse physical LEDs ${onOff(status.reverse_led_order)} · Extra dark LEDs ${status.countdown_dark_edge_compensation} (Countdown + Performance)`,
      ],
    },
  ];
}
