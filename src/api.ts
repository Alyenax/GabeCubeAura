import { callable } from "@decky/api";
import type { ArtworkPayload, Status, UpdateLabResult, UpdateStatus, WeatherLocation, WeatherCondition } from "./types";
import type { ControllerTelemetry } from "./controller_monitor";
import type { MqttTier } from "./home_assistant_tiers";
import type { ConnectionStatus } from "./home_assistant_status";

export const getStatus = callable<[], Status>("get_status");
export const exportConfiguration = callable<[], ConfigurationExportResult>("export_configuration");
export const importConfiguration = callable<[path: string], Status>("import_configuration");
export const resetConfiguration = callable<[], Status>("reset_configuration");
export const setMode = callable<[mode: string], Status>("set_mode");
export const setGameDisplay = callable<[appid: number, mode: string], Status>("set_game_display");
export const setSetting = callable<[key: string, value: unknown], Status>("set_setting");
export const setArtworkSetting = callable<[appid: number, key: string, value: unknown], Status>("set_artwork_setting");
export const setLaunchArtworkSetting = callable<[appid: number, key: string, value: unknown], Status>("set_launch_artwork_setting");
export const gameChanged = callable<[
  appid: number, title: string, launch: boolean, source: string,
], Status>("game_changed");
export const getArtwork = callable<[appid: number, source: string, purpose: "artwork" | "launch"], ArtworkPayload>("get_artwork");
export const submitArtwork = callable<[
  appid: number,
  fingerprint: string,
  colors: number[][],
  sampleY: number,
  dominantPalettes: { "2": number[][]; "3": number[][] },
  filename: string,
  source: string,
  purpose: "artwork" | "launch",
], Status>("submit_artwork");
export const previewLaunchArtwork = callable<[], boolean>("preview_launch_artwork");
export const previewCustomization = callable<[], boolean>("preview_customization");
export const previewLightCalibration = callable<[], Status>("preview_light_calibration");
export const setLightBarBrightness = callable<[
  key: "light_bar_day_brightness" | "night_mode_brightness", value: number, mode: "day" | "night",
], Status>("set_light_bar_brightness");
export const previewDisplayPreset = callable<[preset: string], Status>("preview_display_preset");
export interface SteamActivityPolicy {
  ownership_policy: "cooperative" | "downloads" | "critical";
  suppress_download_animation: boolean;
  restore_download_animation: boolean;
}

export const setSteamActivity = callable<[
  active: boolean, reason: string,
], SteamActivityPolicy>("set_steam_activity");
export const setScreenSyncContext = callable<[
  context: "steam-screensaver",
  active: boolean,
  state: "waiting" | "available" | "unavailable" | "error",
  detail: string,
], boolean>("set_screen_sync_context");
export const previewScreenSync = callable<[], Status>("preview_screen_sync");
export const previewAudioSync = callable<[], Status>("preview_audio_sync");
export const reportRuntimeDiagnostic = callable<[
  event: string,
  appid: number,
  source: string,
  durationMs: number,
], boolean>("report_runtime_diagnostic");
export const reportParentalMinutes = callable<[minutes: number], Status>("report_parental_minutes");
export const startFreeTimer = callable<[minutes: number], Status>("start_free_timer");
export const stopFreeTimer = callable<[], Status>("stop_free_timer");
export const previewCountdown = callable<[], Status>("preview_countdown");
export const triggerEvent = callable<[kind: string, preview: boolean, variant: string], boolean>("trigger_event");
export const updateControllers = callable<[controllers: ControllerBatteryUpdate[], source: string], boolean>("update_controllers");
export const resetControllers = callable<[], boolean>("reset_controllers");
export const reportControllerTelemetry = callable<[state: ControllerTelemetry], boolean>("report_controller_telemetry");
export const previewController = callable<[
  kind: string,
  variant: string,
  count: number,
  target: number,
], boolean>("preview_controller");
export const searchWeatherCities = callable<[query: string], { results: WeatherLocation[]; error: string }>("search_weather_cities");
export const previewWeather = callable<[condition: WeatherCondition, variant: number], boolean>("preview_weather");
export const stopWeatherPreview = callable<[], boolean>("stop_weather_preview");
export const getUpdateStatus = callable<[], UpdateStatus>("get_update_status");
export const checkForUpdates = callable<[], UpdateStatus>("check_for_updates");
export const prepareUpdate = callable<[], UpdateStatus>("prepare_update");
export const installPreparedUpdate = callable<[confirmationToken: string], { accepted: boolean; version: string }>("install_prepared_update");
export const setUpdatePreferences = callable<[
  autoCheck: boolean,
  notifications: boolean,
  checkIntervalMinutes: number,
  channel: "stable" | "beta" | "private",
], UpdateStatus>("set_update_preferences");
export const startPrivateUpdateAuthorization = callable<[], UpdateStatus>("start_private_update_authorization");
export const pollPrivateUpdateAuthorization = callable<[], UpdateStatus>("poll_private_update_authorization");
export const disconnectPrivateUpdateAuthorization = callable<[], UpdateStatus>("disconnect_private_update_authorization");
export const acknowledgeUpdateNotification = callable<[version: string], UpdateStatus>("acknowledge_update_notification");
export const dismissUpdateError = callable<[], UpdateStatus>("dismiss_update_error");
export const runUpdateLabScenario = callable<[scenario: UpdateLabResult["scenario"]], UpdateLabResult>("run_update_lab_scenario");
export const exportUpdateTestReport = callable<[], { path: string }>("export_update_test_report");

export interface ConfigurationExportResult {
  path: string;
  exported_at: string;
}

export interface ControllerBatteryUpdate {
  id: string;
  name: string;
  percent: number | null;
  level: number | null;
  charging: boolean | null;
}

export interface MqttConfig {
  enabled: boolean;
  host: string;
  port: number;
  tls: boolean;
  username: string;
  discovery_prefix: string;
  base_topic: string;
  light_bar_tier: MqttTier;
  faceplate_tier: 1 | 2;
  // Tiers 3-5 drop to Help out while Home Assistant is unreachable.
  ha_fallback: boolean;
  turbo: boolean;
  has_password: boolean;
  load_error: string;
}

export interface MqttBridgeStatus extends ConnectionStatus {
  enabled: boolean;
  connected: boolean;
  connected_with_current_settings: boolean;
  last_error: string;
  messages_out: number;
  events_dropped: number;
  faceplate_controls: boolean;
  // Why Home Assistant's last command was refused or changed; "" once that command later applies.
  command_error: string;
  // The light bar's tier in effect: 2 while falling_back, 1 at Watch only or with the bridge off.
  tier: number;
  falling_back: boolean;
}

export interface MqttState {
  config: MqttConfig;
  status: MqttBridgeStatus;
  ha_alerts_enabled: boolean;
}

export const getMqttStatus = callable<[], MqttState>("get_mqtt_status");
// password: null keeps the saved one, "" clears it.
export const setMqttConfig = callable<[changes: Partial<MqttConfig>, password: string | null], MqttState>(
  "set_mqtt_config",
);
