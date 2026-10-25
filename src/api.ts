import { callable } from "@decky/api";
import type {LedPreviewChannel, LedPreviewFrames} from './led_preview';
import type { ArtworkPayload, DiagnosticStatus, FaceplateDashboardVisualTheme, FaceplateSceneThemeKind, FaceplateVisualTheme, FaceplateWeatherVisualTheme, PixelStudioStatus, Status, UpdateLabResult, UpdateStatus, WeatherLocation, WeatherCondition, WeatherPreviewCondition } from "./types";
import type { ControllerTelemetry } from "./controller_monitor";
export const getStatus = callable<[], Status>("get_status");
export const getLedPreview = callable<[channels: LedPreviewChannel[]], LedPreviewFrames>('get_led_preview');
export const getQuickArtwork = callable<[appid: number, source: string], ArtworkPayload>("get_quick_artwork");
export const exportConfiguration = callable<[], ConfigurationExportResult>("export_configuration");
export const saveConfigurationToGithub = callable<[], ConfigurationBackupResult>('save_configuration_to_github');
export const importConfiguration = callable<[path: string], Status>("import_configuration");
export const resetSettingsOnly = callable<[], Status>("reset_settings_only");
export const factoryResetConfiguration = callable<[confirmation: string], Status>("factory_reset_configuration");
export const resetConfiguration = callable<[], Status>("reset_configuration");
export const setMode = callable<[mode: string], Status>("set_mode");
export const setGameDisplay = callable<[appid: number, mode: string], Status>("set_game_display");
export const setSetting = callable<[key: string, value: unknown], Status>("set_setting");
export const setSteamControl = callable<[enabled: boolean], Status>("set_steam_control");
export const setArtworkSetting = callable<[appid: number, key: string, value: unknown], Status>("set_artwork_setting");
export const setLaunchArtworkSetting = callable<[appid: number, key: string, value: unknown], Status>("set_launch_artwork_setting");
export const reportDashboardStats = callable<[appid: number, stats: Record<string, number>], boolean>("report_dashboard_stats");
export const claimPlayerCityPoll = callable<[], {request_id:string;appid:number}|null>('claim_player_city_poll');
export const completePlayerCityPoll = callable<[request_id:string,appid:number,payload:unknown,error_code:string],boolean>('complete_player_city_poll');
export const gameChanged = callable<[
  appid: number, title: string, launch: boolean, source: string,
], Status>("game_changed");
export const getArtwork = callable<[
  appid: number,
  source: string,
  purpose: "artwork" | "launch",
  includeData: boolean,
], ArtworkPayload>("get_artwork");
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
export const previewDisplayPreset = callable<[preset: string, owner?: string], Status>("preview_display_preset");
export const stopDisplayPresetPreview = callable<[owner: string], boolean>("stop_display_preset_preview");
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
export const startFreeTimer = callable<[minutes: number, endAction?: 'none'|'sleep'|'shutdown'], Status>("start_free_timer");
export const stopFreeTimer = callable<[], Status>("stop_free_timer");
export const extendFreeTimer = callable<[minutes: number], Status>("extend_free_timer");
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
export const previewWeather = callable<[
  condition: WeatherPreviewCondition, variant: number, visualTheme: FaceplateWeatherVisualTheme,
], boolean>("preview_weather");
export const getFaceplateWeatherPreview = callable<[
  condition: WeatherPreviewCondition, variant: number, visualTheme: FaceplateWeatherVisualTheme,
], FaceplateWeatherPreview>("get_faceplate_weather_preview");
export const getFaceplateDashboardPreview = callable<[
  condition: WeatherPreviewCondition, variant: number, visualTheme: FaceplateDashboardVisualTheme,
], FaceplateWeatherPreview>("get_faceplate_dashboard_preview");
export const stopWeatherPreview = callable<[], boolean>("stop_weather_preview");
export const getPixelStudioStatus = callable<[], PixelStudioStatus>("get_pixel_studio_status");
export const repairPixelStudio = callable<[], PixelStudioStatus>("repair_pixel_studio");
export const startPixelStudio = callable<[], PixelStudioStatus>("start_pixel_studio");
export const setPixelStudioBrightness = callable<[value: number], PixelStudioStatus>("set_pixel_studio_brightness");
export const getDiagnosticStatus = callable<[], DiagnosticStatus>("get_diagnostic_status");
export const exportDiagnosticReport = callable<[], { path: string }>("export_diagnostic_report");
export const setDiagnosticUpload = callable<[enabled: boolean], DiagnosticStatus>("set_diagnostic_upload");
export const sendDiagnosticReport = callable<[], DiagnosticStatus>("send_diagnostic_report");
export const setFaceplatePower = callable<[enabled: boolean], Status>("set_faceplate_power");
export const resumeFaceplate = callable<[], Status>("resume_faceplate");
export const setFaceplateRouting = callable<[
  homeScene: "weather" | "dashboard" | "artwork" | "artwork-dashboard" | "native-clock",
  gameScene: "dashboard" | "artwork" | "artwork-dashboard" | "weather" | "player-city",
  expectedRevision: number,
], Status>("set_faceplate_routing");
export const setFaceplateVisualTheme = callable<[
  visualTheme: FaceplateVisualTheme,
  expectedRevision: number,
], Status>("set_faceplate_visual_theme");
export const setFaceplateSceneTheme = callable<[
  sceneKind: FaceplateSceneThemeKind,
  sceneTheme: FaceplateVisualTheme | FaceplateWeatherVisualTheme | FaceplateDashboardVisualTheme,
  expectedRevision: number,
], Status>("set_faceplate_scene_theme");
export const setSteamGridDBApiKey = callable<[apiKey: string], Status>("set_steamgriddb_api_key");
export const validateSteamGridDBApiKey = callable<[], Status>("validate_steamgriddb_api_key");
export const clearSteamGridDBApiKey = callable<[], Status>("clear_steamgriddb_api_key");
export const getFaceplateInstalledGames = callable<[], FaceplateGamesResult>("get_faceplate_installed_games");
export const searchFaceplateArtwork = callable<[
  appid: number, preference: "static" | "animated_any" | "hero_pan",
], FaceplateArtworkSearchResult>("search_faceplate_artwork");
export const getFaceplateArtworkJob = callable<[
  appid: number,
], FaceplateArtworkState>("get_faceplate_artwork_job");
export const getFaceplateDashboardBackgroundStatus = callable<[], {appid: number; ready: boolean}>("get_faceplate_dashboard_background_status");
export const saveCreationToGithub = callable<[appid:number,mode:string,expectedSHA:string],ConfigurationBackupResult>('save_creation_to_github');
export const getFaceplateArtworkLibrary = callable<[], FaceplateArtworkLibraryResult>("get_faceplate_artwork_library");
export const getFaceplateDeliveryStatus = callable<[], Status["faceplate"] & {
  apply_deferred_reason?: string;
}>("get_faceplate_delivery_status");
export const deleteFaceplateArtwork = callable<[
  appid: number, mode: "static" | "animated" | "pan",
], FaceplateArtworkLibraryResult>("delete_faceplate_artwork");
export const getFaceplateArtworkPreview = callable<[
  appid: number,
], { data_uri: string; source: string; error: string }>("get_faceplate_artwork_preview");
export const getFaceplateArtworkDashboardPreview = callable<[
  appid: number, mode?: string, draft?: boolean, home?: boolean,
], FaceplateArtworkDashboardPreview>("get_faceplate_artwork_dashboard_preview");
export const getPreparedFaceplateArtworkPreview = callable<[
  appid: number, mode: "static" | "animated" | "pan",
], { data_uri: string }>("get_prepared_faceplate_artwork_preview");
export const prepareFaceplateArtwork = callable<[
  appid: number, assetId: number, assetKind: "grid" | "hero",
  mode: "static" | "animated" | "pan", cropY: number,
  saturation: number, brightness: number, cropX: number,
  dashboardTreatment: "none" | "cinema" | "hero-cut" | "palette-echo",
  dashboardShowClock: boolean, dashboardClockSize: "compact" | "large",
  dashboardShowSession: boolean,
  dashboardShowBattery: boolean,
  dashboardCompression: "compatible" | "balanced" | "fine",
  loopCleanup: "no" | "soft" | "medium" | "aggressive",
  draft?: boolean, logoScale?: number,
], FaceplateArtworkJob>("prepare_faceplate_artwork");
export const cancelFaceplateArtwork = callable<[], FaceplateArtworkJob>("cancel_faceplate_artwork");
export const activateFaceplateArtwork = callable<[
  appid: number, mode: "static" | "animated" | "pan", draft?: boolean, expectedSHA?: string,
  presentation?: "artwork" | "artwork-dashboard",
], FaceplateArtworkManifest>("activate_faceplate_artwork");
export const assignFaceplateDashboardArtwork = callable<[
  appid: number, mode: "static" | "animated" | "pan", draft?: boolean, homeOnly?: boolean, expectedSHA?: string,
], Status>("assign_faceplate_dashboard_artwork");
/** Commit Home/game artwork independently of the full telemetry refresh. */
export const commitFaceplateDashboardArtwork = callable<[
  appid: number, mode: "static" | "animated" | "pan", draft: boolean, homeOnly: boolean, expectedSHA: string | undefined, includeStatus: false,
], FaceplateArtworkManifest>("assign_faceplate_dashboard_artwork");
export const setSteamGridDBPreference = callable<[preference: "animated" | "animated_any" | "static" | "both"], Status>("set_steamgriddb_preference");
export const getUpdateStatus = callable<[], UpdateStatus>("get_update_status");
export const checkForUpdates = callable<[], UpdateStatus>("check_for_updates");
export const prepareUpdate = callable<[], UpdateStatus>("prepare_update");
export const cancelUpdatePreparation = callable<[], UpdateStatus>("cancel_update_preparation");
export const preparePreviousVersion = callable<[], UpdateStatus>("prepare_previous_version");
export const prepareLab114Rollback = callable<[], UpdateStatus>("prepare_lab114_rollback");
export const installPreparedUpdate = callable<[confirmationToken: string], { accepted: boolean; version: string }>("install_prepared_update");
export const setUpdatePreferences = callable<[
  autoCheck: boolean,
  notifications: boolean,
  checkIntervalMinutes: number,
  channel: "stable" | "beta" | "private",
  autoInstall?: boolean,
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

export interface ConfigurationBackupResult extends ConfigurationExportResult {
  url: string;
  remote: string;
  digest: string;
  commit: string;
}

export interface ControllerBatteryUpdate {
  id: string;
  name: string;
  percent: number | null;
  level: number | null;
  charging: boolean | null;
}

export interface FaceplateInstalledGame { appid: number; name: string }
export interface FaceplateWeatherPreview {
  data_uri: string;
  condition?: WeatherCondition;
  variant?: number;
  temperature_c?: number;
  unit?: "celsius" | "fahrenheit";
  phase?: "dawn" | "day" | "dusk" | "night";
  size_bytes?: number;
  signature?: string;
  live_weather?: boolean;
  visual_theme?: FaceplateWeatherVisualTheme;
  preset_id?: string;
  variant_name?: string;
  source_scene?: string;
  selection_status?: "exact" | "fallback" | "";
  collection_revision?: string;
  fallback_reason?: string;
  error: string;
}
export interface FaceplateGamesResult { games: FaceplateInstalledGame[]; count: number }
export interface FaceplateArtworkAsset {
  id: number;
  kind: "grid" | "hero";
  score: number;
  style: string;
  thumb: string;
  animated: boolean;
  author: string;
  width: number;
  height: number;
}
export interface FaceplateArtworkSearchResult { results: FaceplateArtworkAsset[]; count: number }
export interface FaceplateArtworkManifest {
  sha256?: string;
  appid?: number;
  asset_id?: number;
  mode?: "static" | "animated" | "pan";
  ready?: boolean;
  thumb?: string;
  animated?: boolean;
  author?: string;
  asset_kind?: "grid" | "hero";
  source_width?: number;
  source_height?: number;
  crop_axis?: "horizontal" | "vertical";
  crop_y?: number;
  crop_x?: number;
  saturation?: number;
  brightness?: number;
  logo_scale?: number;
  frames?: number;
  peak_load?: number;
  size?: number;
  dashboard_pack_frames?: number;
  dashboard_pack_revision?: string;
  dashboard_treatment?: "none" | "cinema" | "hero-cut" | "palette-echo";
  dashboard_compression?: "compatible" | "balanced" | "fine";
  dashboard_show_clock?: boolean;
  dashboard_clock_size?: "compact" | "large";
  dashboard_show_status_rail?: boolean;
  dashboard_show_session?: boolean;
  dashboard_show_battery?: boolean;
  loop_cleanup?: "no" | "soft" | "medium" | "aggressive";
  loop_original_frames?: number;
  loop_trimmed_frames?: number;
  loop_trimmed_ms?: number;
  prepared_at?: number;
}
export interface FaceplateArtworkLibraryEntry extends FaceplateArtworkManifest {
  appid: number;
  mode: "static" | "animated" | "pan";
  active: boolean;
  dashboard_ready: boolean;
  name: string;
  size: number;
}
export interface FaceplateArtworkLibraryResult {
  entries: FaceplateArtworkLibraryEntry[];
  count: number;
}
export interface FaceplateArtworkDashboardPreview {
  data_uri: string;
  frames: number;
  delay_cs: number;
  size_bytes: number;
  signature: string;
  treatment: "none" | "cinema" | "hero-cut" | "palette-echo";
  compression: "compatible" | "balanced" | "fine";
}
export interface FaceplateArtworkJob {
  state: "idle" | "queued" | "running" | "cancelling" | "cancelled" | "failed" | "ready";
  percent: number;
  stage: string;
  detail: string;
  appid?: number;
  mode?: "static" | "animated" | "pan";
  prepared?: FaceplateArtworkManifest;
}
export interface FaceplateArtworkState {
  job: FaceplateArtworkJob;
  selected: FaceplateArtworkManifest;
  prepared: Partial<Record<"static" | "animated" | "pan", FaceplateArtworkManifest>>;
}

export const enableCaptureDiagnostic = callable<[], {seconds:number}>("enable_capture_diagnostic");
export const exportCreation = callable<[number,string,string], ConfigurationBackupResult>("export_creation");
