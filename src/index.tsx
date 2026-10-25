import {ArtworkLogoScale} from './components/ArtworkLogoScale';
import {faceplateBrightnessNotice} from './faceplate_power';
import {
  DialogBody,
  DialogHeader,
  DialogControlsSection,
  getFocusNavController,
  getGamepadNavigationTrees,
  NavEntryPositionPreferences,
  Navigation,
  showModal,
  staticClasses,
  useParams,
  useQuickAccessVisible,
} from "@decky/ui";
import { ButtonItem, ConfirmModal, DialogButton, DropdownItem, Focusable, PanelSection,
  PanelSectionRow, ScrollPanel, SliderField, TextField, ToggleField, Localized } from "./localized_ui";
import { setUILanguage, translate } from "./i18n";
import { ScreensaverLightBarChoice } from './components/ScreensaverLightBarChoice';
import {FaceplateSetupNotice} from './components/FaceplateSetupNotice';
import { FirstRunOnboarding } from "./components/FirstRunOnboarding";
import { trailingSetting } from "./trailingSetting";
import {FaceplateDiagnostics} from './components/FaceplateDiagnostics';
import { FlashProtectionPanel } from "./components/FlashProtectionPanel";
import { Disclosure } from "./components/Disclosure";
import { QuickAction, QUICK_CONTROL_CSS } from "./components/QuickAction";
import { CompactQuickPanel } from './components/CompactQuickPanel';
import {playerCitySummary} from './player_city';
import {PlayerCityRowSettings} from './components/PlayerCityRowSettings';
import {CreationBackupSettings} from './components/CreationBackupSettings';
import {ConfigurationExportSettings} from './components/ConfigurationExportSettings';
import {gameDisplayOptions} from './game_display_options';
import {FACEPLATE_HOME_OPTIONS,FACEPLATE_GAME_OPTIONS,homeFaceChoice,isDashboardChoice} from './faceplate_choices';
import { UpdateAvailableButton } from './components/UpdateAvailableButton';
import { statusRefreshGate } from './status_refresh_gate';
import {publishQuickSetupStatus,quickSetupCompleted,subscribeQuickSetup} from './quick_setup_access';
import {QUICK_AMBIENCES,LEGACY_AMBIENCES,presetSummary} from './lighting_presets';
import {EFFECTS_HELP,initialSettingsEffect} from './settings_navigation';
import {SimpleSettings} from './components/SimpleSettings';
import {FaceplateDashboardSettings} from './components/FaceplateDashboardSettings';
import {SettingsDetails} from './components/SettingsDetails';
import {SettingsPart,SettingsHelpText,useSettingsPresentation} from './settings_presentation';
import {SETTINGS_ALIASES,SETTINGS_ROUTE_PATTERN,settingsSources,type SettingsSelection,type SettingsSourcePage} from './settings_structure';
import { OpaqueColorPickerModal, ColorChoice, PreciseColorEditor } from "./components/PreciseColorEditor";
import { AmbienceProfilesPanel } from "./components/AmbienceProfilesPanel";
import { definePlugin, openFilePicker, routerHook } from "@decky/api";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { TbCubeSpark, TbSettings } from "react-icons/tb";

import {
  exportDiagnosticReport,
  enableCaptureDiagnostic,
  checkForUpdates,
  clearSteamGridDBApiKey,
  cancelFaceplateArtwork,
  activateFaceplateArtwork,
  assignFaceplateDashboardArtwork, commitFaceplateDashboardArtwork,
  deleteFaceplateArtwork,
  dismissUpdateError,
  importConfiguration,
  getArtwork,
  setSteamControl,
  getDiagnosticStatus,
  getFaceplateArtworkJob,
  getFaceplateArtworkLibrary,
  getFaceplateDeliveryStatus,
  getFaceplateArtworkDashboardPreview,
  getFaceplateArtworkPreview,
  getPreparedFaceplateArtworkPreview,
  getFaceplateInstalledGames,
  getFaceplateDashboardPreview,
  getFaceplateWeatherPreview,
  getStatus,
  getUpdateStatus,
  installPreparedUpdate,
  previewCountdown,
  previewCustomization,
  previewLaunchArtwork,
  previewAudioSync,
  previewScreenSync,
  previewController,
  previewWeather,
  prepareFaceplateArtwork,
  prepareUpdate,
  cancelUpdatePreparation,
  preparePreviousVersion,
  reportRuntimeDiagnostic,
  resetSettingsOnly,
  factoryResetConfiguration,
  searchWeatherCities,
  searchFaceplateArtwork,
  setArtworkSetting,
  setLaunchArtworkSetting,
  setLightBarBrightness,
  setFaceplatePower,
  setFaceplateRouting,
  setSteamGridDBApiKey,
  validateSteamGridDBApiKey,
  setGameDisplay,
  setSetting,
  setUpdatePreferences,
  startFreeTimer,
  stopFreeTimer,
  submitArtwork,
  triggerEvent,
} from "./api";
import { sampleArtwork } from "./artwork";
import {
  artworkNeedsIdleGame,
  LIGHT_BAR_ARTWORK_ROUTE,
  artworkPreviewMedia,
  artworkResultLabel,
  takeArtworkNativeFocus,
  type ArtworkNativeNavigationTree,
} from "./faceplate_artwork_gallery";
import { PalettePreview } from "./components/PalettePreview";
import {LedPreviewActivity} from "./components/LiveLedPreview";
import { ArtworkCropPreview } from "./components/ArtworkCropPreview";
import { faceplateUXState, installedGameChoices } from "./faceplate_ux";
import { CUSTOMIZATION_PATTERN_OPTIONS, LAUNCH_ARTWORK_PATTERN_OPTIONS } from "./customization_catalog";
import { CONTROLLER_VARIANTS } from "./controller_variants";
import { EVENT_VARIANTS } from "./event_variants";
import { performancePreview } from "./performance";
import { startGabeCubeAuraRuntime } from "./runtime";
import { startTimerActions } from "./timer_actions";
import { startUpdateNotifications } from "./update_notifications";
import { buildSettingsSnapshot } from "./settings_snapshot";
import { WEATHER_CONDITIONS, WEATHER_CONFIGURATION_CONDITIONS, WEATHER_CONFIGURATION_VARIANTS, weatherConfigurationCondition, weatherVariantKey } from "./weather_variants";
import { WEATHER_ICON_STYLE_OPTIONS, weatherIconSvg } from "./weather_icon_sets";
import { startWeatherTopBar } from "./weather_topbar";
import { weatherPreviewMeta } from "./faceplate_visual_themes";
import type { ArtworkPayload, ArtworkSource, DiagnosticStatus, FaceplateDashboardVisualTheme, FaceplateWeatherVisualTheme, GameDisplay, HomeDisplay, RGB, Status, UpdateStatus, WeatherCondition, WeatherConfigurationCondition, WeatherPreviewCondition, WeatherIconStyle, WeatherLocation } from "./types";
import type { FaceplateArtworkAsset, FaceplateArtworkLibraryEntry, FaceplateArtworkManifest, FaceplateArtworkState, FaceplateInstalledGame, FaceplateWeatherPreview } from "./api";

declare const SteamClient: any;
// Independent of the historical renderer/layout preference, kept for compatibility.
const STUDIO_UX = true;

const HOME_DISPLAY_OPTIONS: { data: HomeDisplay; label: string }[] = [
  { data: "faceplate_extension", label: "Faceplate image extension" },
  { data: "blackout", label: "Blackout (held off)" },
  { data: "customization", label: "Customization+" },
  { data: "performance", label: "Performance" },
  { data: "audio_sync", label: "Audio Sync" },
  { data: "weather", label: "Weather" },
  { data: "controller", label: "Controller status" },
];

const FACEPLATE_DASHBOARD_SOURCE_OPTIONS = [
  { data: "weather", label: "Weather Dashboard · Realistic" },
  { data: "artwork", label: "Artwork Dashboard · saved game artwork" },
];

const GAME_DISPLAY_OPTIONS = gameDisplayOptions(true);

const legacyGameDisplayLabel = (display: string, value: ReactNode) => display === 'steam'
  ? translate('Steam control') : display === 'blackout' ? translate('Blackout') : value;

const DISPLAY_PRESET_OPTIONS = [
  ...QUICK_AMBIENCES,...LEGACY_AMBIENCES,
];

const FACEPLATE_POWER_OPTIONS = [
  { data: "auto", label: "Auto · off during sleep and shutdown" },
  { data: "manual", label: "Manual · use the power button" },
];

const DISPLAY_PRESET_DESCRIPTIONS: Record<string, string> = {
  custom: "Your detailed routing and animation settings.",
  "lights-out": "All LEDs stay off except Steam Families. Even Valve download animations are excluded.",
  focus: "Use only Customization+ with the Steam Families limit. Sensor-based thermal protection always remains active.",
  essential: "Stay black except for Steam Families and confirmed downloads. Sensor-based thermal protection always remains active.",
  moderate: "Customization+ at Home, Artwork in games, Game launches, Light Events, brief controller alerts and Screen Sync during the Steam screensaver.",
  atmosphere: "Weather at Home, falling back to Slow Prism; Artwork in games, plus alerts and launches.",
  signals: "Controller status and continuous charging at Home, CPU/GPU in games, brief controller alerts, Game launches, Light Events and Screen Sync during the Steam screensaver.",
  immersive: "Slow Prism with the Sapphire palette at Home, Screen Sync in games, Game launches, Light Events, brief controller alerts and Screen Sync during the Steam screensaver.",
  "immersive-plus": "Slow Prism with the Screen Sync palette at Home and in games, plus Game launches, Light Events, brief controller alerts and Screen Sync during the Steam screensaver.",
  festive: "Slow Prism with the Screen Sync palette at Home and Aurora in games, plus Game launches, Light Events, brief controller alerts and Screen Sync during the Steam screensaver.",
};

const VALVE_OWNERSHIP_OPTIONS = [
  { data: "cooperative", label: "Compatible" },
  { data: "downloads", label: "Downloads + safety" },
  { data: "critical", label: "Safety only" },
];

const VALVE_OWNERSHIP_DESCRIPTIONS: Record<string, string> = {
  cooperative: "Yield to detected Steam or external LED activity. This is the compatibility-first behaviour.",
  downloads: "Keep GabeCubeAura in control except for confirmed Steam downloads. A reversible Steam LED manager request holds the native Download mode until each transfer ends. Sensor-based thermal protection is always active.",
  critical: "Keep GabeCubeAura in control during ordinary Steam LED activity. During confirmed downloads, a reversible Steam LED manager override prevents Download mode from starting when this Steam build exposes the required private service. Sensor-based thermal protection is always active.",
};

const UPDATE_INTERVAL_OPTIONS = [
  { data: 60, label: "1 hour" },
  { data: 180, label: "3 hours" },
  { data: 360, label: "6 hours" },
  { data: 720, label: "12 hours" },
  { data: 1440, label: "24 hours" },
];

const UPDATE_CHANNEL_OPTIONS = [
  { data: "stable", label: "Stable" },
  { data: "beta", label: "Beta" },
  { data: "private", label: "Private Lab" },
];

const STEAMGRIDDB_API_KEY_URL = "https://www.steamgriddb.com/profile/preferences/api";
// SteamGridDB's own Login control opens this Steam OpenID request in a popup.
// Steam's embedded browser can suppress that popup, so offer the same standard
// OpenID flow as an ordinary navigation instead.
const STEAMGRIDDB_DIRECT_LOGIN_URL = "https://steamcommunity.com/openid/login?openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0&openid.mode=checkid_setup&openid.realm=https%3A%2F%2Fwww.steamgriddb.com&openid.return_to=https%3A%2F%2Fwww.steamgriddb.com%2Flogin%2Fsteam&mobileminimal=1";

const steamGridDBValidationLabel = (state: Status["faceplate"]["steamgriddb"]["validation_state"]) => ({
  absent: "Key missing",
  detected_unverified: "Key detected locally · not verified",
  validated: "Key validated by SteamGridDB",
  rejected: "Key rejected by SteamGridDB",
  offline: "Validation unavailable · offline",
}[state]);

const openSystemBrowser = (url: string) => {
  try {
    const open = SteamClient?.System?.OpenInSystemBrowser;
    if (typeof open === "function") {
      open.call(SteamClient.System, url);
      return true;
    }
  } catch (error) {
    console.warn("[GabeCubeAura] system browser unavailable", error);
  }
  return false;
};

const openCopyCapableBrowser = (url: string) => {
  if (openSystemBrowser(url)) return;
  Navigation.NavigateToExternalWeb(url);
};

const displayLabel = (display: HomeDisplay | GameDisplay) => (
  [...HOME_DISPLAY_OPTIONS, ...GAME_DISPLAY_OPTIONS].find((item) => item.data === display)?.label ?? display
);

const ARTWORK_OPTIONS = [
  { data: "auto", label: "Auto (best row)" },
  { data: "center", label: "Centre" },
  { data: "lower", label: "Lower" },
  { data: "manual", label: "Manual" },
];

const ARTWORK_SOURCE_OPTIONS = [
  { data: "hero", label: "Library Hero (wide artwork)" },
  { data: "header", label: "Library Header" },
  { data: "capsule", label: "Library Capsule (vertical)" },
];

const LAUNCH_ARTWORK_COLOUR_OPTIONS = [
  { data: 2, label: "2 dominant colours" },
  { data: 3, label: "3 dominant colours" },
];

const LAUNCH_PALETTE_MODE_OPTIONS = [
  { data: "artwork", label: "From artwork" },
  { data: "custom", label: "Custom for this game" },
];

const CUSTOMIZATION_COLOUR_OPTIONS = [
  { data: 1, label: "1 colour" },
  { data: 2, label: "2 colours" },
  { data: 3, label: "3 colours" },
];

const CUSTOMIZATION_DIRECTION_OPTIONS = [
  { data: "forward", label: "Left to right" },
  { data: "reverse", label: "Right to left" },
];

const PERFORMANCE_OPTIONS = [
  { data: "gpu", label: "GPU" },
  { data: "cpu", label: "CPU" },
  { data: "mixed", label: "CPU + GPU" },
];
const SMOOTHING_OPTIONS = [
  { data: "responsive", label: "Responsive" },
  { data: "balanced", label: "Balanced" },
  { data: "smooth", label: "Smooth" },
];
const SCREEN_SYNC_STYLE_OPTIONS = [
  { data: "panorama", label: "Panorama (17 screen zones)" },
  { data: "ambient", label: "Ambient (one screen colour)" },
];
const SCREEN_SYNC_REACTIVITY_OPTIONS = [
  { data: "calm", label: "Calm" },
  { data: "balanced", label: "Balanced" },
  { data: "fast", label: "Fast" },
];
const SCREEN_SYNC_COLOUR_OPTIONS = [
  { data: "natural", label: "Natural" },
  { data: "vivid", label: "Vivid" },
];

const AUDIO_SYNC_STYLE_OPTIONS = [
  { data: "spectrum", label: "17-band spectrum" },
  { data: "audio-pulse", label: "Audio pulse" },
  { data: "bass", label: "Bass pulse" },
  { data: "constellation", label: "Constellation" },
  { data: "hifi-crest", label: "Hi-Fi Crest" },
  { data: "negative-bloom", label: "Negative Bloom" },
  { data: "slow-prism", label: "Slow Prism" },
  { data: "spatial", label: "Stereo field" },
  { data: "stereo-lanterns", label: "Stereo Lanterns" },
  { data: "velvet-relay", label: "Velvet Relay" },
];
const ADAPTIVE_AUDIO_STYLES = AUDIO_SYNC_STYLE_OPTIONS.map((option) => option.data);
const AUDIO_SYNC_STYLE_TUNING: Record<string, {
  brightness: number;
  reactivity: string;
  note: string;
}> = {
  "hifi-crest": { brightness: 160, reactivity: "balanced", note: "Reference balance for a visible bed and restrained travelling crest." },
  "velvet-relay": { brightness: 184, reactivity: "fast", note: "Extra drive and fast attacks keep the centre-to-edge relay readable." },
  "negative-bloom": { brightness: 192, reactivity: "fast", note: "A brighter safe base makes the moving true-black gap clearly visible." },
  "stereo-lanterns": { brightness: 172, reactivity: "balanced", note: "Moderate light preserves two broad stereo lobes without diffuser glare." },
  constellation: { brightness: 205, reactivity: "fast", note: "Sparse points receive more headroom so attacks stay visible between black gaps." },
  "slow-prism": { brightness: 180, reactivity: "fast", note: "Fast response offsets the deliberately slow colour drift while audio controls its width." },
  spectrum: { brightness: 190, reactivity: "fast", note: "Fast response and extra headroom produce a legible classic analyser." },
  spatial: { brightness: 170, reactivity: "balanced", note: "Balanced motion keeps stereo placement clear without constant full-bar glare." },
  bass: { brightness: 185, reactivity: "fast", note: "Fast low-frequency response gives the mirrored centre pulse a clean release." },
  "audio-pulse": { brightness: 168, reactivity: "balanced", note: "Lower output keeps the mirrored palette readable while retaining a visible global pulse." },
};
const EXPERIMENTAL_AUDIO_DESCRIPTIONS: Record<string, string> = {
  "velvet-relay": "Velvet Relay sends a bass impact from the centre to the shoulders and then the edges. Overlapping broad zones let the diffuser create motion between only 17 physical points.",
  "negative-bloom": "Negative Bloom draws impact with a truly black gap moving from the centre to the edges. It avoids unreliable dark brown and grey RGB values by using either a safe active colour or complete extinction.",
  "stereo-lanterns": "Stereo Lanterns uses two broad fixed lobes for left and right energy plus a restrained mono centre. No important detail depends on one LED or one perfectly timed write.",
  constellation: "Constellation assigns at most five tinted cores to bass, mid attack and high texture. Dim neighbours let the diffuser connect them without turning the full strip into white glare.",
  "slow-prism": "Slow Prism changes palette hue no more than once every eight 60 ms blocks. Audio mainly changes the illuminated width, keeping chromatic movement smooth and unobtrusive.",
};
const AUDIO_SYNC_REACTIVITY_OPTIONS = [
  { data: "calm", label: "Calm" },
  { data: "balanced", label: "Balanced" },
  { data: "fast", label: "Fast" },
  { data: "punchy", label: "Punchy" },
];
const AUDIO_SYNC_PALETTE_OPTIONS = [
  { data: "artwork", label: "Artwork" },
  { data: "aurora", label: "Aurora" },
  { data: "candy", label: "Candy" },
  { data: "coastline", label: "Coastline" },
  { data: "copper", label: "Copper" },
  { data: "custom", label: "Custom colours" },
  { data: "deep-sea", label: "Deep Sea" },
  { data: "ember", label: "Ember" },
  { data: "forest", label: "Forest" },
  { data: "glacier", label: "Glacier" },
  { data: "ice", label: "Ice" },
  { data: "lagoon", label: "Lagoon" },
  { data: "lime", label: "Lime" },
  { data: "magma", label: "Magma" },
  { data: "orchid", label: "Orchid" },
  { data: "pearl", label: "Pearl" },
  { data: "plasma", label: "Plasma" },
  { data: "sapphire", label: "Sapphire" },
  { data: "screen-sync", label: "Screen Sync" },
  { data: "silver", label: "Silver" },
  { data: "solar", label: "Solar" },
  { data: "sunset", label: "Sunset" },
];

const PALETTE_OPTIONS = [
  { data: "thermal", label: "Cyan → amber → red" },
  { data: "classic", label: "Green → yellow → red" },
  { data: "icefire", label: "Blue → violet → pink" },
  { data: "custom", label: "Custom colours" },
];

const DIRECTION_OPTIONS = [
  { data: "same", label: "Both left → right" },
  { data: "mirrored", label: "Mirrored toward centre" },
];

const COUNTDOWN_COLOUR_OPTIONS = [
  { data: "cyan", label: "Cyan" },
  { data: "green", label: "Green" },
  { data: "amber", label: "Amber" },
  { data: "violet", label: "Violet" },
  { data: "white", label: "White" },
];

const COUNTDOWN_SCALE_OPTIONS = [
  { data: 0, label: "Timer duration (starts full)" },
  { data: 60, label: "Full bar = 1 hour" },
  { data: 120, label: "Full bar = 2 hours" },
  { data: 180, label: "Full bar = 3 hours" },
  { data: 240, label: "Full bar = 4 hours" },
];

const WEATHER_TEMPERATURE_UNITS = [
  { data: "celsius", label: "Celsius (°C)" },
  { data: "fahrenheit", label: "Fahrenheit (°F)" },
];
const CONTROLLER_ALERT_OPTIONS = [
  { data: "off", label: "Off" },
  { data: "home", label: "On Home" },
  { data: "game", label: "In game" },
  { data: "both", label: "Home + in game" },
];
const CONTROLLER_CHARGING_OPTIONS = [
  { data: "off", label: "Off" },
  { data: "brief", label: "Brief, about 3 seconds" },
  { data: "continuous-home", label: "Continuous on Home" },
  { data: "continuous-everywhere", label: "Continuous everywhere" },
];
const CONTROLLER_COLOUR_MODE_OPTIONS = [
  { data: "battery", label: "Battery level" },
  { data: "players", label: "Player seats" },
];
const CONTROLLER_COLOUR_PRESET_OPTIONS = [
  { data: "automatic", label: "Automatic" },
  { data: "manual", label: "Manual" },
];
const CONTROLLER_PREVIEW_COUNT_OPTIONS = [1, 2, 3, 4].map((count) => ({
  data: count,
  label: `${count} controller${count === 1 ? "" : "s"}`,
}));
function formatRemaining(seconds: number): string {
  const safe = Math.max(0, Math.ceil(seconds));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const remainder = safe % 60;
  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, "0")}m`;
  return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

function formatAge(seconds: number | null): string {
  if (seconds == null) return "never";
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms ago`;
  return `${seconds.toFixed(1)} s ago`;
}

function formatSolarTime(value: string): string {
  const match = String(value || "").match(/T(\d{2}:\d{2})/);
  return match?.[1] ?? "waiting for solar times";
}

function formatUpdateDate(timestamp: number): string {
  if (!timestamp) return "Never";
  try {
    return new Date(timestamp * 1000).toLocaleString();
  } catch {
    return "Unavailable";
  }
}

function updatePhaseLabel(update: UpdateStatus): string {
  switch (update.phase) {
    case "checking": return "Checking for updates...";
    case "up_to_date": return "GabeCubeAura is up to date.";
    case "available": return `Version ${update.available_version} is available.`;
    case "downloading": return `Downloading ${update.available_version}...`;
    case "verifying": return "Checking the downloaded package...";
    case "ready": return `Ready to ${update.recovery_prepared ? "restore" : "install"} ${update.available_version}.`;
    case "preparing_install": return "Backing up settings and artwork before installation…";
    case "installing":
    case "restart_pending": return "Restarting Decky to finish the update...";
    case "updated": return `Updated successfully to ${update.installed_version}.`;
    case "rolled_back": return `The new version did not start correctly. GabeCubeAura restored ${update.rollback_version || update.installed_version}.`;
    case "error": return update.error || "Could not check for updates. Try again later.";
    case "authorization_required": return "Connect GitHub to access Private Lab releases.";
    case "managed_by_decky": return "Updates are managed by Decky.";
    default: return "Ready to check for updates.";
  }
}

function controllerChargeLabel(controller: Status["controllers"]["controllers"][number]): string {
  if (controller.percent != null) return `${controller.percent}%`;
  if (controller.level != null) return `${controller.level}/4 level`;
  return "battery unavailable";
}

function ArtworkImage({ artwork, title, compact = false, sampleLine }: {
  artwork: ArtworkPayload;
  title: string;
  compact?: boolean;
  sampleLine?: number;
}) {
  if (!artwork.data_uri) return null;
  return <Localized><div style={{ width: "100%", display: "flex", justifyContent: "center" }}>
    <div style={{ position: "relative", display: "inline-flex", maxWidth: "100%" }}>
      <img
        src={artwork.data_uri}
        alt={`Artwork for ${title}`}
        style={{ display: "block", width: "auto", height: "auto", maxWidth: "100%", maxHeight: compact ? 160 : 360, objectFit: "contain", borderRadius: 4 }}
      />
      {sampleLine == null ? null : <div
        aria-label={`Selected sample row at ${Math.round(sampleLine * 100)} percent`}
        style={{
          position: "absolute",
          top: `${Math.max(0, Math.min(1, sampleLine)) * 100}%`,
          left: 0,
          right: 0,
          height: 2,
          transform: "translateY(-1px)",
          background: "#ff3b45",
          boxShadow: "0 0 4px rgba(255, 40, 50, .95)",
          pointerEvents: "none",
        }}
      />}
    </div>
  </div></Localized>;
}

function PerformanceReadout({ status }: { status: Status }) {
  return <Localized><div style={{ width: "100%", fontSize: ".84em" }}>
    CPU {status.performance.cpu_load == null ? "Unavailable" : `${Math.round(status.performance.cpu_load)}%`}
    {" · "}{status.performance.cpu_temperature == null ? "Unavailable" : `${Math.round(status.performance.cpu_temperature)}°C`}
    <br />
    GPU {status.performance.gpu_load == null ? "Unavailable" : `${Math.round(status.performance.gpu_load)}%`}
    {" · "}{status.performance.gpu_temperature == null ? "Unavailable" : `${Math.round(status.performance.gpu_temperature)}°C`}
    <div style={{ opacity: .65, marginTop: 4 }}>
      {status.performance.error ? `Sensor read failed: ${status.performance.error}`
        : status.performance.sample_age_s == null ? "Waiting for a fresh sensor reading…"
        : `Live sensors · updated ${formatAge(status.performance.sample_age_s)}`}
    </div>
  </div></Localized>;
}



function chooseSettingColor(key: string, label: string, color: [number, number, number], setStatus: (value: Status) => void) {
  let modal: ReturnType<typeof showModal> | undefined;
  modal = showModal(<OpaqueColorPickerModal title={label} color={color}
    closeModal={() => modal?.Close()}
    onConfirm={(nextColor) => void setSetting(key, nextColor).then(setStatus).catch(actionFailed)} />);
}


function addRecordingMarker(status: Status, colors: Status["events"]["colors"] | undefined) {
  if (!status.events.recording || !colors || colors.length !== 17) return colors ?? [];
  const marked = colors.map((color) => [...color] as [number, number, number]);
  if (status.recording_marker_isolation) {
    marked[7] = [0, 0, 0];
    marked[9] = [0, 0, 0];
  }
  marked[8] = [229, 54, 70];
  return marked;
}

function EventPreviewStrip({ status, kinds }: { status: Status; kinds: string[] }) {
  const visible = status.events.active && kinds.includes(status.events.kind);
  const recordingPreview = kinds.includes("record-start") && status.events.recording;
  const recordingFrame = addRecordingMarker(status, Array.from({ length: 17 }, () => [0, 0, 0]));
  return <Localized><div style={{ width: "100%", fontSize: ".78em", opacity: .84 }}>
    <div>{visible ? `Playing: ${status.events.variant}` : recordingPreview ? "Recording marker active" : "Preview appears here"}</div>
    <PalettePreview source={visible ? "events" : undefined} colors={visible ? status.events.colors : recordingPreview ? recordingFrame : []} />
  </div></Localized>;
}

function CountdownPanel({
  status,
  setStatus,
}: {
  status: Status;
  setStatus: (next: Status) => void;
}) {
  const starting = useRef(false);
  const [timerError,setTimerError] = useState('');
  const startTimer = () => {
    if(starting.current)return;
    starting.current=true;
    const action=status.free_timer_end_action??'none',minutes=status.free_timer_minutes;
    const run=async()=>{
      try{setTimerError('');setStatus(await startFreeTimer(minutes,action));}
      catch{setTimerError('The timer could not be started. Try again.');}
      finally{starting.current=false;}
    };
    if(action==='none'){void run();return;}
    let modal:ReturnType<typeof showModal>|undefined,settled=false;
    try{modal=showModal(<ConfirmModal
      strTitle={action==='shutdown'?'Start timer with console shutdown?':'Start timer with console sleep?'}
      strOKButtonText="Start timer" strCancelButtonText="Cancel"
      onOK={()=>{if(settled)return;settled=true;modal?.Close();void run();}}
      onCancel={()=>{if(settled)return;settled=true;starting.current=false;modal?.Close();}}>
      <div>{minutes} min</div>
      <div>{action==='shutdown'
        ?'The console will shut down when this personal timer ends. Save your game before the deadline.'
        :'The console will sleep when this personal timer ends. Save your game before the deadline.'}</div>
    </ConfirmModal>);}catch{starting.current=false;setTimerError('The timer could not be started. Try again.');}
  };
  return (
    <>
      {status.countdown.active ? <PanelSection title="Active countdown">
        <PanelSectionRow>
          <div style={{ width: "100%", fontSize: ".84em" }}>
            <b>{status.countdown.label}</b>
            {" · "}{formatRemaining(status.countdown.remaining_seconds)} remaining
            {status.countdown.alerting ? " · triple white alert" : status.countdown_full_bar_minutes > 0
              ? ` · full bar = ${status.countdown_full_bar_minutes / 60}h`
              : " · starts full"}
            <PalettePreview source="countdown" colors={status.countdown.colors} />
            <div style={{ opacity: .7 }}>Live 17-LED countdown preview</div>
          </div>
        </PanelSectionRow>
      </PanelSection> : null}
      <PanelSection title="Playtime countdown">
      <PanelSectionRow>
        <ToggleField
          label="Remaining time on Faceplate"
          description="Shows the remaining time on Weather and Dashboard, or beside Players City counts. Red from five minutes; TIME'S UP appears at expiry, then the saved row returns."
          checked={status.faceplate_playtime_enabled}
          onChange={async (value) => setStatus(await setSetting("faceplate_playtime_enabled", value))}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label="Steam Families limit"
          description="Always takes priority over Artwork, Performance and a personal timer while a game is running."
          checked={status.parental_countdown_enabled}
          onChange={async (value) => setStatus(await setSetting("parental_countdown_enabled", value))}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <DropdownItem
          label="Starting colour"
          rgOptions={COUNTDOWN_COLOUR_OPTIONS}
          selectedOption={status.countdown_colour}
          onChange={async (option) => setStatus(await setSetting("countdown_colour", String(option.data)))}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <DropdownItem
          label="Full bar scale"
          description="Timer duration starts at 17 LEDs. A fixed scale means 17 LEDs represent that much remaining time; longer limits stay full until they enter the selected window."
          rgOptions={COUNTDOWN_SCALE_OPTIONS}
          selectedOption={status.countdown_full_bar_minutes}
          onChange={async (option) => setStatus(await setSetting("countdown_full_bar_minutes", Number(option.data)))}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <SliderField
          label="Free timer"
          description="Duration used the next time you start the personal countdown."
          value={status.free_timer_minutes}
          min={1}
          max={240}
          step={1}
          showValue
          valueSuffix=" min"
          onChange={async (value) => setStatus(await setSetting("free_timer_minutes", value))}
        />
      </PanelSectionRow>
      <PanelSectionRow><DropdownItem label="When the next personal timer ends"
        description="Applies when you start or restart the personal timer."
        rgOptions={[{data:'none',label:'Do nothing'},{data:'sleep',label:'Put console to sleep'},{data:'shutdown',label:'Shut down console'}]}
        selectedOption={status.free_timer_end_action??'none'}
        onChange={async option=>setStatus(await setSetting('free_timer_end_action',String(option.data)))}/></PanelSectionRow>
      {['armed','ready','executing'].includes(status.timer_end_action?.phase) ? <PanelSectionRow><Localized><div>
        At the end of this timer: {status.timer_end_action.action==='shutdown'?'Shut down console':'Put console to sleep'}
      </div></Localized></PanelSectionRow>:null}
      {status.timer_end_action?.phase==='failed'?<PanelSectionRow><Localized><div>
        The timer ended, but Steam did not confirm the power action. No automatic retry.
      </div></Localized></PanelSectionRow>:null}
      {status.timer_end_action?.phase==='skipped'?<PanelSectionRow><Localized><div>
        The timer expired too long ago. No delayed power action.
      </div></Localized></PanelSectionRow>:null}
      {status.timer_end_action?.phase==='cancelled'&&['system-suspended','system-resumed','system-unavailable'].includes(status.timer_end_action.reason)?<PanelSectionRow><Localized><div>
        Automatic power action cancelled after sleep. Restart the timer to enable it again.
      </div></Localized></PanelSectionRow>:null}
      {timerError?<PanelSectionRow><Localized><div>{timerError}</div></Localized></PanelSectionRow>:null}
      <PanelSectionRow>
        <ButtonItem
          label="Personal limit"
          description="The timer keeps running when this Decky panel is closed."
          onClick={startTimer}
        >
          Start / restart
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          label="Stop personal limit"
          onClick={() => void stopFreeTimer().then(setStatus).catch(actionFailed)}
        >
          Stop
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <div style={{ width: "100%", fontSize: ".8em", opacity: 0.86 }}>
          {status.countdown.active ? "The active timer and its live bar are shown at the top of this page." : "No countdown is active."}
          <div style={{ marginTop: 5, opacity: 0.75 }}>
            The bar empties from right to left. A configurable physical compensation counters diffuser bloom while this preview keeps the logical LED count. It turns amber below 15 minutes, then pure red below 5 minutes while the right-to-left circulation continues. During the final 8 seconds, three short white flashes repeat until zero.
          </div>
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          label="Test countdown and final alert"
          description="Runs a 15-second countdown whose final 8 seconds demonstrate the white alert without cancelling a real timer."
          onClick={() => void previewCountdown().then(setStatus).catch(actionFailed)}
        >
          Preview
        </ButtonItem>
      </PanelSectionRow>
      </PanelSection>
    </>
  );
}

function EventsPanel({ status, setStatus, kind: selectedKind }: { status: Status; setStatus: (next: Status) => void; kind?:string }) {
  const preview = async (kind: string, variant = "") => {
    await triggerEvent(kind, true, variant);
    setStatus(await getStatus());
  };
  const categories = ([
    ["notification", "Notifications", "event_notifications_enabled", "event_notification_variant"],
    ["achievement", "Achievements", "event_achievements_enabled", "event_achievement_variant"],
    ["screenshot", "Screenshots", "event_screenshots_enabled", "event_screenshot_variant"],
  ] as const);
  return (
    <>
      <PanelSection title="Light events">
        <PanelSectionRow>
          <ToggleField
            label="Steam event animations"
            description="Enabled by default. Short signals play even outside games, briefly replacing the current display. Previews work while off."
            checked={status.events_enabled}
            onChange={async (value) => setStatus(await setSetting("events_enabled", value))}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={{ width: "100%", fontSize: ".8em", opacity: .82 }}>
            {status.events.active ? `Playing: ${status.events.variant}` : "No event animation active"}
            {status.events.recording ? " · recording marker on" : ""}
            <div style={{ marginTop: 5 }}>The final five minutes of a countdown are protected. New native LED writes interrupt animations.</div>
          </div>
        </PanelSectionRow>
      </PanelSection>
      {categories.filter(([kind])=>!selectedKind||kind===selectedKind).map(([kind, label, enabledKey, variantKey]) => {
        const options = EVENT_VARIANTS[kind];
        const selected = status[variantKey];
        const detail = options.find((option) => option.data === selected)?.detail ?? "";
        return (
          <PanelSection key={kind} title={label}>
            <PanelSectionRow>
              <ToggleField label={`Show ${label.toLowerCase()}`} checked={status[enabledKey]}
                onChange={async (value) => setStatus(await setSetting(enabledKey, value))} />
            </PanelSectionRow>
            <PanelSectionRow>
              <DropdownItem label="Animation" rgOptions={[...options]} selectedOption={selected}
                onChange={async (option) => setStatus(await setSetting(variantKey, String(option.data)))} />
            </PanelSectionRow>
            <PanelSectionRow>
              <div style={{ fontSize: ".8em", opacity: .78 }}>{detail}</div>
            </PanelSectionRow>
            <PanelSectionRow>
              <EventPreviewStrip status={status} kinds={[kind]} />
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem label={`Preview ${label.toLowerCase()}`}
                description="Works with live events off, but not with Display disabled or in the final five countdown minutes."
                onClick={() => void preview(kind, selected).catch(actionFailed)}>Play selected</ButtonItem>
            </PanelSectionRow>
          </PanelSection>
        );
      })}
      {!selectedKind||selectedKind==='recording'?<PanelSection title="Recording">
        <PanelSectionRow>
          <ToggleField label="Recording · red start/stop" description="The centre LED stays red over Artwork or Performance while recording. Countdowns retain all 17 LEDs."
            checked={status.event_recording_enabled}
            onChange={async (value) => setStatus(await setSetting("event_recording_enabled", value))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="Isolate recording marker"
            description="Turns the LED immediately to each side of the red centre marker black, reducing colour bleed from Artwork or Performance."
            checked={status.recording_marker_isolation}
            disabled={!status.event_recording_enabled}
            onChange={async (value) => setStatus(await setSetting("recording_marker_isolation", value))}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <EventPreviewStrip status={status} kinds={["record-start", "record-stop"]} />
        </PanelSectionRow>
      {([
        ["record-start", "Recording starts"], ["record-stop", "Recording ends"],
      ] as const).map(([kind, label]) => (
        <PanelSectionRow key={kind}>
          <ButtonItem label={`Preview ${label}`} onClick={() => void preview(kind).catch(actionFailed)}>Play</ButtonItem>
        </PanelSectionRow>
      ))}
      </PanelSection>:null}
    </>
  );
}

function ControllersPanel({ status, setStatus }: { status: Status; setStatus: (next: Status) => void }) {
  const compact=useSettingsPresentation();
  const [kindFilter,setKindFilter]=useState('connect');
  const [previewMessage, setPreviewMessage] = useState("");
  const [previewCount, setPreviewCount] = useState(Math.max(1, Math.min(4, status.controllers.controllers.length || 2)));
  const [previewTarget, setPreviewTarget] = useState(0);
  const telemetry = status.debug.controller_telemetry;
  const stale = (status.debug.controller_last_update_age_s ?? 0) > 10;
  const automaticColours = status.controller_colour_preset === "automatic";
  const detectedControllerCount = status.controllers.controllers.length;
  const batteryColourChoices = [
    ["controller_colour_normal", `Healthy battery · above ${Math.max(35, status.controller_low_threshold + 5)}%`],
    ["controller_colour_medium", "Medium battery"],
    ["controller_colour_low", `Low battery · ${status.controller_low_threshold}% or less`],
  ] as const;
  const playerColourChoices = [
    ["controller_player_colour_1", "Player 1"],
    ["controller_player_colour_2", "Player 2"],
    ["controller_player_colour_3", "Player 3"],
    ["controller_player_colour_4", "Player 4"],
  ] as const;
  const preview = async (kind: keyof typeof CONTROLLER_VARIANTS, variant: string) => {
    try {
      const count = kind === "duo" ? Math.max(2, previewCount) : previewCount;
      const played = await previewController(kind, variant, count, Math.min(previewTarget, count - 1));
      setPreviewMessage(played ? "Preview requested. It does not test controller detection; LED output still follows GabeCubeAura priorities."
        : "Preview unavailable in Disabled mode or during the final five minutes of a countdown.");
      setStatus(await getStatus());
    } catch { setPreviewMessage("Preview could not reach GabeCubeAura. Check the Decky backend."); }
  };
  const groups = [
    ["connect", "Connection", "controller_connect_enabled", "controller_connect_variant"],
    ["persistent", "Permanent gauge", null, "controller_persistent_variant"],
    ["low", "Low battery", "controller_low_enabled", "controller_low_variant"],
    ["charging", "Charging style", null, "controller_charging_variant"],
    ["duo", "Multiple controllers", null, "controller_duo_variant"],
  ] as const;
  return <>
    <PanelSection title="Controller battery">
      <PanelSectionRow><div style={{ fontSize: ".8em", opacity: .8 }}>
        {status.controllers.controllers.length ? status.controllers.controllers.map((controller) =>
          `${controller.name}: ${controllerChargeLabel(controller)}${controller.charging ? " · charging" : ""}`).join(" · ")
          : telemetry?.phase === "ready" && !stale ? "Steam responded: no controllers connected."
          : telemetry?.phase === "starting" || !telemetry ? "Connecting to Steam controller service…"
          : "Controller detection unavailable. See the connection details below."}
        <div style={{ marginTop: 8 }}>
          Steam connection: {stale ? "stale (last reading over 10 seconds ago)" : telemetry?.phase ?? "starting"}
          {telemetry?.phase === "ready" ? ` · ${telemetry.hooks}/3 live hooks · checked every 2 s` : ""}
        </div>
        {telemetry?.error ? <div style={{ color: "#ffca86", marginTop: 6 }}>{telemetry.error}</div> : null}
        {previewMessage ? <div style={{ marginTop: 6 }}>{previewMessage}</div> : null}
      </div></PanelSectionRow>
      <SettingsHelpText><PanelSectionRow><div style={{ fontSize: ".78em", opacity: .75 }}>
        Select <b>Controller status</b> for Home or In game on the Display routing page to use the permanent gauge. Brief alerts remain independent.
      </div></PanelSectionRow></SettingsHelpText>
      <PanelSectionRow><ToggleField label="Brief controller alerts"
        description="Master switch for connection, low-battery and brief charging signals. It does not turn off the permanent gauge or continuous charging."
        checked={status.controller_alerts_enabled}
        onChange={async (value) => setStatus(await setSetting("controller_alerts_enabled", value))} /></PanelSectionRow>
      <PanelSectionRow><DropdownItem label="Where brief alerts play"
        description="Applies to connection, low-battery and brief charging signals, not continuous charging."
        rgOptions={CONTROLLER_ALERT_OPTIONS}
        selectedOption={status.controller_alert_context}
        onChange={async (option) => setStatus(await setSetting("controller_alert_context", String(option.data)))} /></PanelSectionRow>
      <PanelSectionRow><DropdownItem label="Charging behavior"
        description="Choose one: a brief signal when charging starts, or movement while Steam reports charging below 100%. Continuous charging is independent of Brief controller alerts."
        rgOptions={CONTROLLER_CHARGING_OPTIONS} selectedOption={status.controller_charging_mode}
        onChange={async (option) => setStatus(await setSetting("controller_charging_mode", String(option.data)))} /></PanelSectionRow>
      <PanelSectionRow><div style={{ fontSize: ".78em", opacity: .78 }}>
        {status.controller_charging_mode === "brief"
          ? "Brief charging needs Brief controller alerts enabled and a reported battery level. It follows Where brief alerts play and ends after about 3 seconds. A controller already charging at startup does not trigger it."
          : status.controller_charging_mode.startsWith("continuous")
            ? "Continuous charging needs a reported battery level. It ends if Steam stops reporting charging, or at 100% after a short completion cue. It can yield to higher-priority signals."
            : "No charging signal. Connection and low-battery alerts can still play if enabled."}
      </div></PanelSectionRow>
      <PanelSectionRow><SliderField label="Low battery warning" value={status.controller_low_threshold}
        min={5} max={30} step={5} showValue valueSuffix="%"
        onChange={async (value) => setStatus(await setSetting("controller_low_threshold", value))} /></PanelSectionRow>
      <PanelSectionRow><div style={{ width: "100%", fontSize: ".78em", opacity: .8 }}>
        {status.controllers.active ? `Playing: ${status.controllers.kind} · ${status.controllers.variant}`
          : status.controllers.charging_active ? "Charging animation active" : "No controller animation active"}
        <div>Battery and charging readings depend on what Steam exposes for this controller and connection. Unknown is not treated as empty. An already-connected controller does not replay the connection signal at startup. Disabled mode and Steam LED ownership can prevent output.</div>
      </div></PanelSectionRow>
      <SettingsHelpText><PanelSectionRow><div style={{ fontSize: ".78em", opacity: .75 }}>
        Each detected controller keeps a fixed seat. Two and four controllers use mirrored seats. Three controllers use three left-to-right zones. Separators remain dark and fixed white endpoints appear after the introduction.
      </div></PanelSectionRow></SettingsHelpText>
    </PanelSection>
    <SettingsDetails title="Controller colours and brightness"><PanelSection title="Controller colours">
      <SettingsHelpText><PanelSectionRow><div style={{ fontSize: ".8em", opacity: .8 }}>
        Automatic uses battery status colours with one controller, then fixed P1 to P4 colours from two controllers. Battery level still controls the length of every gauge. Low-battery and charging signals keep their warning colours, and white highlights stay white.
      </div></PanelSectionRow></SettingsHelpText>
      <PanelSectionRow><DropdownItem label="Colour preset"
        description="Automatic follows the connected controller count. Manual keeps one colour meaning at every count."
        rgOptions={CONTROLLER_COLOUR_PRESET_OPTIONS}
        selectedOption={status.controller_colour_preset}
        onChange={async (option) => setStatus(await setSetting("controller_colour_preset", String(option.data)))} /></PanelSectionRow>
      <PanelSectionRow><DropdownItem label="Colour meaning"
        description={automaticColours
          ? "Managed by Automatic: battery level for one controller, player seats for two to four controllers."
          : "Choose battery status colours or fixed player-seat colours for permanent gauges and multiplayer patterns."}
        rgOptions={CONTROLLER_COLOUR_MODE_OPTIONS}
        selectedOption={status.controller_colour_mode}
        disabled={automaticColours}
        onChange={async (option) => setStatus(await setSetting("controller_colour_mode", String(option.data)))} /></PanelSectionRow>
      {automaticColours ? <PanelSectionRow><div style={{ fontSize: ".78em", opacity: .78 }}>
        {detectedControllerCount === 1
          ? "Current rule: one detected controller, so the gauge uses battery colours."
          : detectedControllerCount >= 2
            ? `Current rule: ${detectedControllerCount} detected controllers, so the gauges use player colours.`
            : "Current rule: the next single controller will use battery colours. Two or more will use player colours."}
        <div>Previews apply the same rule to the selected preview count.</div>
      </div></PanelSectionRow> : null}
      <PanelSectionRow><SliderField label="Controller brightness" min={10} max={100} step={5}
        showValue valueSuffix="%" value={status.controller_gauge_brightness}
        onChange={async (value) => setStatus(await setSetting("controller_gauge_brightness", value))} /></PanelSectionRow>
      {automaticColours ? <PanelSectionRow><div style={{ fontSize: ".78em", opacity: .72 }}>One controller</div></PanelSectionRow> : null}
      {(automaticColours || status.controller_colour_mode === "battery" ? batteryColourChoices : []).map(([key, label]) => <PanelSectionRow key={key}>
        <ColorChoice label={label} color={status[key]}
          onClick={() => chooseSettingColor(key, label, status[key], setStatus)} />
      </PanelSectionRow>)}
      {automaticColours ? <PanelSectionRow><div style={{ fontSize: ".78em", opacity: .72 }}>Two to four controllers</div></PanelSectionRow> : null}
      {(automaticColours || status.controller_colour_mode === "players" ? playerColourChoices : []).map(([key, label]) => <PanelSectionRow key={key}>
        <ColorChoice label={label} color={status[key]}
          onClick={() => chooseSettingColor(key, label, status[key], setStatus)} />
      </PanelSectionRow>)}
      <PanelSectionRow>
        <ColorChoice label="Connection / charging colour" color={status.controller_colour_charging}
          onClick={() => chooseSettingColor("controller_colour_charging", "Connection / charging colour", status.controller_colour_charging, setStatus)} />
      </PanelSectionRow>
    </PanelSection></SettingsDetails>
    <SettingsDetails title="Choose preview controllers"><PanelSection title="Preview setup">
      <PanelSectionRow><DropdownItem label="Controllers in preview"
        description="Uses sample levels only. It does not change the detected controller roster."
        rgOptions={CONTROLLER_PREVIEW_COUNT_OPTIONS} selectedOption={previewCount}
        onChange={(option) => {
          const count = Number(option.data);
          setPreviewCount(count);
          setPreviewTarget((target) => Math.min(target, count - 1));
        }} /></PanelSectionRow>
      <PanelSectionRow><DropdownItem label="Preview controller"
        description="Connection, low-battery and charging previews use this player seat."
        rgOptions={CONTROLLER_PREVIEW_COUNT_OPTIONS.slice(0, previewCount).map((_, index) => ({ data: index, label: `Controller ${index + 1}` }))}
        selectedOption={previewTarget}
        onChange={(option) => setPreviewTarget(Number(option.data))} /></PanelSectionRow>
    </PanelSection></SettingsDetails>
    {compact?<PanelSectionRow><DropdownItem label="Controller signal to configure" selectedOption={kindFilter}
      rgOptions={groups.map(([data,label])=>({data,label}))} onChange={option=>setKindFilter(String(option.data))}/></PanelSectionRow>:null}
    {groups.filter(([kind])=>!compact||kind===kindFilter).map(([kind, title, enabledKey, variantKey]) => {
      const selected = status[variantKey];
      const options = CONTROLLER_VARIANTS[kind];
      const detail = options.find((item) => item.data === selected)?.detail ?? "";
      return <PanelSection key={kind} title={title}>
        {kind === "charging" ? <SettingsHelpText><PanelSectionRow><div style={{ fontSize: ".78em", opacity: .78 }}>
          This style is used for the brief signal or the repeating animation, depending on Charging behavior. Preview shows one cycle only.
        </div></PanelSectionRow></SettingsHelpText> : null}
        {enabledKey ? <PanelSectionRow><ToggleField label={`Show ${title.toLowerCase()}`}
          checked={status[enabledKey]}
          onChange={async (value) => setStatus(await setSetting(enabledKey, value))} /></PanelSectionRow> : null}
        <PanelSectionRow><DropdownItem label="Visual style" rgOptions={[...options]}
          selectedOption={selected}
          onChange={async (option) => setStatus(await setSetting(variantKey, String(option.data)))} /></PanelSectionRow>
        <PanelSectionRow><div style={{ fontSize: ".8em", opacity: .78 }}>{detail}</div></PanelSectionRow>
        <PanelSectionRow><div style={{ width: "100%", fontSize: ".78em", opacity: .8 }}>
          {status.controllers.active && status.controllers.kind === kind ? `Playing: ${status.controllers.variant}` : "No preview playing"}
          <PalettePreview source={status.controllers.active && status.controllers.kind === kind ? "controllers" : undefined} colors={status.controllers.active && status.controllers.kind === kind ? status.controllers.colors : []} />
        </div></PanelSectionRow>
        <PanelSectionRow><ButtonItem label={`Preview ${title.toLowerCase()}`}
          description="Uses sample battery data; it does not verify Steam detection. Disabled mode, countdown priority and Steam ownership can prevent LED output."
          onClick={() => void preview(kind, selected).catch(actionFailed)}>Play selected</ButtonItem></PanelSectionRow>
      </PanelSection>;
    })}
  </>;
}

function WeatherIconSetPreview({ style }: { style: WeatherIconStyle }) {
  return <Localized><div style={{ width: "100%" }}>
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
      {WEATHER_CONDITIONS.map((condition) => <span
        key={condition.data}
        role="img"
        aria-label={condition.label}
        title={condition.label}
        style={{ display: "inline-flex", width: 27, height: 27, alignItems: "center", justifyContent: "center" }}
        dangerouslySetInnerHTML={{ __html: weatherIconSvg(style, condition.data) }}
      />)}
    </div>
    <div style={{ marginTop: 6, fontSize: ".72em", opacity: .7 }}>
      Clear day, clear night, rain, cloud, cloud night, partly cloudy day, partly cloudy night, snow and thunderstorm.
    </div>
  </div></Localized>;
}

function FaceplateBrightnessSlider({ status, setStatus }: {
  status: Status;
  setStatus: (next: Status) => void;
}) {
  const [value, setValue] = useState(status.faceplate_brightness);
  const latest = useRef(value);
  const mounted = useRef(true);
  const writer = useRef<ReturnType<typeof trailingSetting<number, Status>> | null>(null);
  if (!writer.current) writer.current = trailingSetting(async (next) => {
    const saved = await setSetting("faceplate_brightness", next);
    if (mounted.current && latest.current === next) setStatus(saved);
    return saved;
  });
  useEffect(() => {
    if (!writer.current?.pending()) setValue(status.faceplate_brightness);
  }, [status.faceplate_brightness]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      void writer.current?.flush().catch((error) => console.warn("[GabeCubeAura] faceplate brightness save failed", error));
    };
  }, []);
  const change = (next: number) => {
    latest.current = next;
    setValue(next);
    writer.current?.push(next);
  };
  return <><SliderField label="Faceplate brightness" min={5} max={100} step={5}
    description="Global GabeCubeAura matrix brightness. One update is sent after a short pause; moving this slider never starts Pixel Studio."
    showValue valueSuffix="%" value={value} onChange={change} />
    {faceplateBrightnessNotice(value)?<Localized><small role="status">{faceplateBrightnessNotice(value)}</small></Localized>:null}</>;
}

function FaceplateWeatherMatrixPreview({ condition, variant, temperature, unit, visualTheme, scene = "weather" }: {
  condition: WeatherPreviewCondition;
  variant: number;
  temperature: number | null;
  unit: "celsius" | "fahrenheit";
  visualTheme: FaceplateWeatherVisualTheme | FaceplateDashboardVisualTheme;
  scene?: "weather" | "dashboard";
}) {
  const [preview, setPreview] = useState<FaceplateWeatherPreview>({
    data_uri: "", error: "",
  });
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    const request = scene === "dashboard"
      ? getFaceplateDashboardPreview(condition, variant, visualTheme as FaceplateDashboardVisualTheme)
      : getFaceplateWeatherPreview(condition, variant, visualTheme as FaceplateWeatherVisualTheme);
    void request
      .then((next) => { if (alive) setPreview(next); })
      .catch((error) => { if (alive) setPreview({ data_uri: "", error: String(error) }); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [condition, variant, temperature, unit, visualTheme, scene]);
  const metadata = weatherPreviewMeta(preview);
  return <div style={{ width: "100%" }}>
    <div style={{ fontSize: ".76em", opacity: .78, marginBottom: 7 }}>
      Faceplate 64 × 54 · {scene === "dashboard" ? "Dashboard Home" : "exact Weather GIF"}
      {preview.phase ? ` · ${preview.phase}` : ""}
      {metadata.length ? ` · ${metadata.join(" · ")}` : ""}
    </div>
    <div style={{
      position: "relative", width: "min(100%, 320px)", aspectRatio: "64 / 54",
      margin: "0 auto", overflow: "hidden", borderRadius: 7,
      background: "#01030a", border: "1px solid rgba(126,220,255,.38)",
      boxShadow: "0 10px 28px rgba(0,0,0,.38), inset 0 0 18px rgba(36,151,255,.12)",
    }}>
      {preview.data_uri ? <img src={preview.data_uri} alt={`${condition} Faceplate preview`}
        loading="lazy" decoding="async"
        style={{ width: "100%", height: "100%", display: "block", imageRendering: "pixelated" }} /> : null}
      <div aria-hidden style={{
        position: "absolute", inset: 0, pointerEvents: "none",
        backgroundImage: "radial-gradient(circle, transparent 42%, rgba(0,0,0,.72) 55%, rgba(0,0,0,.92) 72%)",
        backgroundSize: "calc(100% / 64) calc(100% / 54)",
      }} />
      {loading ? <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(1,3,10,.72)", fontSize: ".78em" }}>Rendering…</div> : null}
    </div>
    {preview.error ? <div style={{ marginTop: 7, fontSize: ".74em", color: "#ff9d8d" }}>
      Faceplate preview unavailable: {preview.error}
    </div> : null}
    {preview.selection_status === "fallback" && preview.fallback_reason ? <div style={{
      marginTop: 7, fontSize: ".74em", color: "#ffd38a",
    }}>
      Artwork fallback: {preview.fallback_reason}
    </div> : null}
  </div>;
}

function PixelStudioWeatherCatalog({ status, setStatus }: {
  status: Status;
  setStatus: (next: Status) => void;
}) {
  const liveCondition = status.weather.condition;
  const initialCondition = weatherConfigurationCondition(liveCondition, status.weather.is_day);
  const [condition, setCondition] = useState<WeatherConfigurationCondition>(initialCondition);
  const [message, setMessage] = useState("");
  const variantKey = weatherVariantKey(condition);
  const variant = Number(status[variantKey]);
  const weatherVisualTheme: FaceplateWeatherVisualTheme = "weather-artwork-v2";
  return <SettingsPart slot="faceplate.catalog"><SettingsDetails title="Faceplate weather animations"><PanelSection title="Weather Artwork catalog">
    <SettingsHelpText><PanelSectionRow><div style={{ fontSize: ".78em", lineHeight: 1.45, opacity: .82 }}>
      <b>Realistic · 28 day/night animated scenes.</b>
      <Localized>Weather and Dashboard automatically share the same atmosphere.</Localized>
    </div></PanelSectionRow></SettingsHelpText>
    <PanelSectionRow><div style={{ width: "100%", fontSize: ".78em", lineHeight: 1.45 }}>
      Active collection: <b>Realistic</b>
    </div></PanelSectionRow>
    <PanelSectionRow><DropdownItem label="Weather condition"
      rgOptions={WEATHER_CONFIGURATION_CONDITIONS} selectedOption={condition}
      onChange={(option) => setCondition(option.data as WeatherConfigurationCondition)} /></PanelSectionRow>
    <PanelSectionRow><DropdownItem label="Animated scene"
      description="This choice is shared with the automatic Weather route."
      rgOptions={WEATHER_CONFIGURATION_VARIANTS[condition].map((item, index) => ({
        data: index, label: item.label,
      }))}
      selectedOption={variant}
      onChange={async (option) => setStatus(await setSetting(
        variantKey, Number(option.data),
      ))} /></PanelSectionRow>
    <PanelSectionRow><div style={{ fontSize: ".76em", opacity: .76 }}>
      {WEATHER_CONFIGURATION_VARIANTS[condition][variant]?.detail}
    </div></PanelSectionRow>
    <SettingsHelpText><PanelSectionRow><div style={{ fontSize: ".76em", opacity: .76 }}>
      A game artwork chosen explicitly as the Dashboard Home background remains
      available and receives the same compact weather header.
    </div></PanelSectionRow></SettingsHelpText>
    {status.faceplate.available ? <PanelSectionRow><FaceplateWeatherMatrixPreview
      condition={condition} variant={variant}
      temperature={status.weather.temperature_c}
      unit={status.weather_temperature_unit}
      visualTheme={weatherVisualTheme} scene="weather" />
    </PanelSectionRow> : null}
    <PanelSectionRow><ButtonItem label="Preview Realistic on Faceplate"
      description="Renders and sends the exact scene shown above."
      onClick={async () => {
        try {
          const played = await previewWeather(condition, variant, weatherVisualTheme);
          setMessage(played
            ? "Realistic sent to the Faceplate."
            : "Preview unavailable while the weather preview is blocked.");
        } catch (error) {
          setMessage(`Faceplate preview failed: ${String(error)}`);
        }
      }}>Send to Faceplate</ButtonItem></PanelSectionRow>
    {message ? <PanelSectionRow><div style={{ fontSize: ".76em", opacity: .82 }}>
      {message}
    </div></PanelSectionRow> : null}
  </PanelSection></SettingsDetails></SettingsPart>;
}

function WeatherPanel({ status, setStatus }: { status: Status; setStatus: (next: Status) => void }) {
  const [cityQuery, setCityQuery] = useState("");
  const [countryQuery, setCountryQuery] = useState("");
  const [cityResults, setCityResults] = useState<WeatherLocation[]>([]);
  const [searching, setSearching] = useState(false);
  const [message, setMessage] = useState("");
  const [previewCondition, setPreviewCondition] = useState<WeatherConfigurationCondition>("clear_day");
  const variantKey = weatherVariantKey(previewCondition);
  const selectedVariant = Number(status[variantKey]);
  const weatherVisualTheme: FaceplateWeatherVisualTheme = "weather-artwork-v2";
  const currentLabel = WEATHER_CONFIGURATION_CONDITIONS.find((item) => item.data === weatherConfigurationCondition(status.weather.condition, status.weather.is_day))?.label ?? "Unknown";
  const findCity = async () => {
    setSearching(true);
    setMessage("");
    try {
      const city = cityQuery.trim();
      const country = countryQuery.trim();
      const response = await searchWeatherCities(country ? `${city}, ${country}` : city);
      setCityResults(response.results);
      if (response.error) setMessage(`City search failed: ${response.error}`);
      else if (!response.results.length) setMessage("No matching city. Enter the full country name, or try searching without it.");
    } catch (error) {
      setCityResults([]);
      setMessage(`City search failed: ${error instanceof Error ? error.message : String(error)}`);
    } finally { setSearching(false); }
  };
  const chooseCity = async (city: WeatherLocation) => {
    try {
      setStatus(await setSetting("weather_location", city));
      setCityResults([]);
      setCityQuery(city.name);
      setCountryQuery(city.country);
      setMessage("City saved. Select Weather on the Display routing page to show it on the LED bar.");
    } catch (error) { setMessage(`Could not save city: ${String(error)}`); }
  };
  const playPreview = async (condition: WeatherConfigurationCondition = previewCondition) => {
    try {
      const variant = Number(status[weatherVariantKey(condition)]);
      const played = await previewWeather(condition, variant, weatherVisualTheme);
      const next = await getStatus();
      setStatus(next);
      setMessage(played
        ? next.faceplate_lab_enabled
          ? `${next.faceplate.detail}. Realistic is on the matrix; the light bar starts after its acknowledgement.`
          : "One cycle requested. Preview still follows countdown and Steam LED ownership."
        : "Preview unavailable in Disabled mode or during the final five minutes of a countdown.");
    } catch (error) { setMessage(`Preview failed: ${String(error)}`); }
  };
  return <>
    <SettingsPart slot="weather.forecast"><PanelSection title="Local weather">
      <PanelSectionRow><div style={{ fontSize: ".8em", opacity: .82 }}>
        {status.weather_location ? `${status.weather_location.name}, ${status.weather_location.country}` : "Choose a city to begin. Location is never detected automatically."}
        <div style={{ marginTop: 6 }}>
          {status.weather.phase === "ready"
            ? `${currentLabel} · updated ${formatAge(status.weather.age_s)}`
            : status.weather.phase === "loading" ? "Getting current weather…"
              : status.weather.phase === "error" ? `Weather unavailable: ${status.weather.error}`
                : status.weather.phase === "waiting" ? "Waiting for the first weather update…"
              : "Weather is off. The controller gauge is the fresh-install default."}
        </div>
        {message ? <div style={{ marginTop: 6 }}>{message}</div> : null}
      </div></PanelSectionRow>
      <PanelSectionRow><TextField label="City or postal code" value={cityQuery} onChange={(event) => setCityQuery(event.currentTarget.value)}
        description="Enter a city name or postal code." /></PanelSectionRow>
      <PanelSectionRow><TextField label="Country (full name, optional)" value={countryQuery} onChange={(event) => setCountryQuery(event.currentTarget.value)}
        description="Use the full country name, for example France. Two-letter codes do not work here." /></PanelSectionRow>
      <PanelSectionRow><ButtonItem label="Find city" disabled={searching || cityQuery.trim().length < 2}
        onClick={() => void findCity()}>{searching ? "Searching…" : "Search"}</ButtonItem></PanelSectionRow>
      {cityResults.map((city, index) => <PanelSectionRow key={`${city.latitude}:${city.longitude}:${index}`}>
        <ButtonItem label={`${city.name}, ${city.country}`} untranslatedProps={["label"]} onClick={() => void chooseCity(city)}>Use this city</ButtonItem>
      </PanelSectionRow>)}
      {status.weather_location ? <PanelSectionRow><ButtonItem label="Remove city"
        description="Turns weather off and stops weather requests."
        onClick={() => void setSetting("weather_location", null).then((next) => { setStatus(next); setMessage("City removed."); }).catch((error) => setMessage(String(error)))}>Remove</ButtonItem></PanelSectionRow> : null}
      <PanelSectionRow><ToggleField label="SteamOS top-bar weather"
        description="Show a weather icon and temperature beside the clock when Steam's top bar is available. Needs a chosen city. Independent of the LED display and controller gauge; hides if the top bar cannot be found."
        checked={status.weather_topbar_enabled}
        onChange={async (enabled) => {
          try {
            setStatus(await setSetting("weather_topbar_enabled", enabled));
            setMessage(enabled
              ? status.weather_location
                ? "Top-bar weather enabled. It may take a few seconds to appear."
                : "Top-bar weather enabled. Choose a city when you want it to appear."
              : "Top-bar weather disabled.");
          } catch (error) { setMessage(`Could not change top-bar weather: ${String(error)}`); }
        }} /></PanelSectionRow>
      <PanelSectionRow><DropdownItem label="Top-bar icon family"
        description="Choose the complete nine-condition icon set. Every icon is bundled locally; no icon CDN is contacted."
        rgOptions={WEATHER_ICON_STYLE_OPTIONS} selectedOption={status.weather_icon_style}
        onChange={async (option) => setStatus(await setSetting("weather_icon_style", String(option.data)))} /></PanelSectionRow>
      <PanelSectionRow><WeatherIconSetPreview style={status.weather_icon_style} /></PanelSectionRow>
      <PanelSectionRow><DropdownItem label="Weather temperature unit"
        description="Applies to the SteamOS top bar and the 64 × 54 Faceplate Weather and Dashboard scenes."
        rgOptions={WEATHER_TEMPERATURE_UNITS} selectedOption={status.weather_temperature_unit}
        onChange={async (option) => setStatus(await setSetting("weather_temperature_unit", String(option.data)))} /></PanelSectionRow>
      <SettingsHelpText><PanelSectionRow><div style={{ fontSize: ".78em", opacity: .75 }}>
        Select <b>Weather</b> for Home, In game, or a game override on the Display routing page. Brief alerts and playtime warnings remain independent.
      </div></PanelSectionRow></SettingsHelpText>
      <PanelSectionRow><div style={{ fontSize: ".76em", opacity: .72 }}>
        Current conditions refresh about every 15 minutes. The last reading can be reused for up to one hour; then weather yields the bar. No city, no network request. Data by <a href="https://open-meteo.com/" target="_blank" rel="noreferrer">Open-Meteo</a>.
      </div></PanelSectionRow>
    </PanelSection></SettingsPart>
    <SettingsPart slot="weather.night"><PanelSection title="Automatic night brightness">
      <SettingsHelpText><PanelSectionRow><div style={{ fontSize: ".78em", opacity: .78 }}>
        Sunset dimming now belongs to the single global <b>Light bar brightness</b> section in Display routing. Weather keeps the shared city and solar data.
      </div></PanelSectionRow></SettingsHelpText>
    </PanelSection></SettingsPart>
    <SettingsPart slot="weather.animations"><PanelSection title="Weather animations">
      <SettingsHelpText><PanelSectionRow><div style={{ fontSize: ".8em", lineHeight: 1.45 }}>
        <b>Realistic</b>
        <div style={{ opacity: .72 }}>One coherent, systemic Weather language for the faceplate and light bar.</div>
      </div></PanelSectionRow></SettingsHelpText>
      <SettingsHelpText><PanelSectionRow><div style={{ fontSize: ".76em", opacity: .72 }}>
        All 28 day/night scenes are precompiled as native 64 × 54 animations. Rain, Snow and Thunderstorm have independent day and night choices.
      </div></PanelSectionRow></SettingsHelpText>
      <PanelSectionRow><DropdownItem label="Condition to configure" rgOptions={WEATHER_CONFIGURATION_CONDITIONS}
        selectedOption={previewCondition} onChange={(option) => setPreviewCondition(option.data as WeatherConfigurationCondition)} /></PanelSectionRow>
      <PanelSectionRow><DropdownItem label="Animation" rgOptions={WEATHER_CONFIGURATION_VARIANTS[previewCondition].map((item, index) => ({ data: index, label: item.label }))}
        selectedOption={selectedVariant}
        onChange={async (option) => setStatus(await setSetting(variantKey, Number(option.data)))} /></PanelSectionRow>
      <PanelSectionRow><div style={{ fontSize: ".78em", opacity: .78 }}>
        {WEATHER_CONFIGURATION_VARIANTS[previewCondition][selectedVariant]?.detail}
      </div></PanelSectionRow>
      {status.faceplate.available ? <PanelSectionRow><FaceplateWeatherMatrixPreview
        condition={previewCondition} variant={selectedVariant}
        temperature={status.weather.temperature_c} unit={status.weather_temperature_unit}
        visualTheme={weatherVisualTheme} />
      </PanelSectionRow> : null}
      <PanelSectionRow><ButtonItem label="Preview this animation"
        description={status.faceplate_lab_enabled && (previewCondition === "rain_day" || previewCondition === "rain_night")
          ? "Prepares the rain animation and starts the Faceplate and light bar together."
          : "Plays one weather cycle with the selected condition, even before you choose a city. This does not test the weather connection."}
        onClick={() => void playPreview()}>Play preview</ButtonItem></PanelSectionRow>
      <PanelSectionRow><div style={{ width: "100%", fontSize: ".78em", opacity: .8 }}>
        {status.weather.preview_active ? "Preview playing" : status.weather.active_here ? "Live weather signal available here" : "No weather signal playing here"}
        <PalettePreview source="weather" colors={status.weather.colors} />
      </div></PanelSectionRow>
    </PanelSection></SettingsPart>
    <SettingsPart slot="weather.faceplate"><PanelSection title="JSAUX PIXEL Faceplate">
      <PanelSectionRow><ToggleField label="Follow GabeCubeAura automatically"
        description="Automatically shows each launched game's local Steam or SteamGridDB artwork and follows supported durable weather scenes. Stop the JSAUX daemon and disable the separate Pixel Faceplate plugin first."
        checked={status.faceplate_lab_enabled}
        onChange={async (enabled) => setStatus(await setSetting("faceplate_lab_enabled", enabled))} /></PanelSectionRow>
      {status.faceplate_lab_enabled ? <>
        <PanelSectionRow><FaceplateBrightnessSlider status={status} setStatus={setStatus} /></PanelSectionRow>
        <PanelSectionRow><Localized>{status.faceplate.busy ? "Faceplate port is busy. Stop the other Faceplate plugin." : status.faceplate.available ? "Faceplate connected" : "Faceplate not detected"}</Localized></PanelSectionRow>
        {status.faceplate.error ? <PanelSectionRow><Localized>{status.faceplate.error}</Localized></PanelSectionRow> : null}
        <FaceplateDiagnostics status={status}/>
        <SettingsHelpText><PanelSectionRow><div style={{ fontSize: ".76em", opacity: .72 }}>
          Prepared images are reused automatically when a game starts. Until an image is ready, the local Steam artwork is shown. Pixel Studio prepares new images only when you request it.
        </div></PanelSectionRow></SettingsHelpText>
      </> : null}
    </PanelSection></SettingsPart>
    <SettingsPart slot="weather.brightness"><PanelSection title="Weather brightness">
      <SettingsHelpText><PanelSectionRow><div style={{ fontSize: ".78em", opacity: .78 }}>
        Brightness scales RGB linearly for all weather animations. Use 100% with cutoff 0 for the unprocessed animation. These controls affect Weather only, not Steam's master LED brightness or other GabeCubeAura modes.
      </div></PanelSectionRow></SettingsHelpText>
      <PanelSectionRow><SliderField label="Weather LED brightness" min={10} max={100} step={5}
        showValue valueSuffix="%" value={status.weather_brightness}
        onChange={async (value) => setStatus(await setSetting("weather_brightness", value))} /></PanelSectionRow>
      <PanelSectionRow><SliderField label="Turn faint LEDs off" min={0} max={60} step={5}
        showValue value={status.weather_shadow_cutoff}
        onChange={async (value) => setStatus(await setSetting("weather_shadow_cutoff", value))} /></PanelSectionRow>
      <SettingsHelpText><PanelSectionRow><div style={{ fontSize: ".76em", opacity: .72 }}>
        Cutoff turns a pixel fully off when its strongest RGB channel is at or below this value (scale from 0 to 255). It does not dim the remaining pixels further. A high cutoff can make transitions more abrupt. These are brightness controls, not measured hardware colour calibration.
      </div></PanelSectionRow></SettingsHelpText>
    </PanelSection></SettingsPart>
  </>;
}

function CustomizationPanel({ status, setStatus }: { status: Status; setStatus: (next: Status) => void }) {
  const activeHome = status.home_display === "customization";
  const activeGame = status.game_display === "customization";
  const context = activeHome && activeGame ? "Everywhere" : activeHome ? "Home" : activeGame ? "In game" : "Not selected";
  const colourKeys = ["customization_colour_1", "customization_colour_2", "customization_colour_3"] as const;
  const preview = async () => {
    await previewCustomization();
    setStatus(await getStatus());
  };
  return <PanelSection title="Customization+">
    <PanelSectionRow><div style={{ fontSize: ".8em", opacity: .82 }}>
      Permanent display · <b>{context}</b>. Select Customization+ in Display routing for Home, in game, or both. Temporary layers still take priority.
    </div></PanelSectionRow>
    <PanelSectionRow><DropdownItem label="Pattern" rgOptions={CUSTOMIZATION_PATTERN_OPTIONS}
      selectedOption={status.customization_pattern}
      onChange={async (option) => setStatus(await setSetting("customization_pattern", String(option.data)))} /></PanelSectionRow>
    <>
      <PanelSectionRow><DropdownItem label="Palette" rgOptions={CUSTOMIZATION_COLOUR_OPTIONS}
        selectedOption={status.customization_colour_count}
        onChange={async (option) => setStatus(await setSetting("customization_colour_count", Number(option.data)))} /></PanelSectionRow>
      {colourKeys.slice(0, status.customization_colour_count).map((key, index) => <PanelSectionRow key={key}>
        <PreciseColorEditor label={`Colour ${index + 1}`} color={status[key]}
          onChange={(color) => void setSetting(key, color).then(setStatus).catch(actionFailed)} />
      </PanelSectionRow>)}
    </>
    <PanelSectionRow><SliderField label="Brightness" description="Raw RGB ceiling: 34 is the minimum retained by GabeCubeAura because lower values switch the physical bar off; 255 is full output."
      value={status.customization_brightness} min={34} max={255} step={1} showValue valueSuffix=" / 255"
      onChange={async (value) => setStatus(await setSetting("customization_brightness", value))} /></PanelSectionRow>
    {status.customization_pattern !== "steady" ? <PanelSectionRow><SliderField label="Speed"
      value={status.customization_speed} min={1} max={100} step={1} showValue valueSuffix=" / 100"
      onChange={async (value) => setStatus(await setSetting("customization_speed", value))} /></PanelSectionRow> : null}
    {status.customization_pattern !== "steady" ? <PanelSectionRow>
      <DropdownItem label="Direction" rgOptions={CUSTOMIZATION_DIRECTION_OPTIONS}
        selectedOption={status.customization_direction}
        onChange={async (option) => setStatus(await setSetting("customization_direction", String(option.data)))} />
    </PanelSectionRow> : null}
    <PanelSectionRow><ButtonItem label="Preview Customization+" description="Plays for 8 seconds without changing Display routing."
      onClick={() => void preview().catch(actionFailed)}>Preview</ButtonItem></PanelSectionRow>
    <PanelSectionRow><div style={{ width: "100%", fontSize: ".78em", opacity: .82 }}>
      {status.customization.preview_active ? "Preview playing" : "Live 17-LED preview"}
      <PalettePreview source="customization" colors={status.customization.colors} />
    </div></PanelSectionRow>
  </PanelSection>;
}

function LightBarBrightness({ status, setStatus }: {
  status: Status;
  setStatus: (next: Status) => void;
}) {
  const compact=useSettingsPresentation();
  const brightness = status.light_bar_brightness;
  const [changingCity, setChangingCity] = useState(false);
  const [cityQuery, setCityQuery] = useState("");
  const [countryQuery, setCountryQuery] = useState("");
  const [cityResults, setCityResults] = useState<WeatherLocation[]>([]);
  const [searching, setSearching] = useState(false);
  const [message, setMessage] = useState("");
  const nightOutput = Math.max(1, Math.round(status.light_bar_day_brightness * status.night_mode_brightness / 100));
  const currentOutput = brightness.current_output === "night"
    ? `Night · ${brightness.target_brightness ?? nightOutput}/255${status.night_mode.sunrise_at ? ` until ${formatSolarTime(status.night_mode.sunrise_at)}` : ""}`
    : brightness.current_output === "alert"
      ? `Important alert · ${status.light_bar_day_brightness}/255`
      : brightness.current_output === "valve"
        ? "Valve control · Steam brightness restored"
        : `Daytime · ${brightness.target_brightness ?? status.light_bar_day_brightness}/255`;
  const preview = async (mode: "day" | "night", key: "light_bar_day_brightness" | "night_mode_brightness", value: number) => {
    try {
      setStatus(await setLightBarBrightness(key, value, mode));
    } catch (error) { setMessage(`Brightness preview failed: ${String(error)}`); }
  };
  const findCity = async () => {
    setSearching(true);
    setMessage("");
    try {
      const country = countryQuery.trim();
      const response = await searchWeatherCities(country ? `${cityQuery.trim()}, ${country}` : cityQuery.trim());
      setCityResults(response.results);
      if (response.error) setMessage(`City search failed: ${response.error}`);
      else if (!response.results.length) setMessage("No matching city. Try the full city and country name.");
    } catch (error) { setMessage(`City search failed: ${String(error)}`); }
    finally { setSearching(false); }
  };
  const chooseCity = async (city: WeatherLocation) => {
    try {
      let next = await setSetting("weather_location", city);
      next = await setSetting("night_mode_enabled", true);
      setStatus(next);
      setChangingCity(false);
      setCityResults([]);
      setMessage("");
    } catch (error) { setMessage(`Could not save city: ${String(error)}`); }
  };
  return <PanelSection title="Light bar brightness">
    <SettingsHelpText><PanelSectionRow><div style={{ fontSize: ".78em", opacity: .82 }}>
      One global intensity for every Home and in-game display. Changing a preset or route never changes it.
    </div></PanelSectionRow></SettingsHelpText>
    <PanelSectionRow><SliderField label="Day brightness" description="Direct hardware brightness. Moving the slider previews it immediately on the 17-LED bar."
      min={1} max={255} step={1} showValue valueSuffix=" / 255" value={status.light_bar_day_brightness}
      onChange={(value) => void preview("day", "light_bar_day_brightness", value)} /></PanelSectionRow>
    {status.light_bar_day_brightness < 8 ? <PanelSectionRow>
      <LowBrightnessWarning mode="Day" value={status.light_bar_day_brightness} />
    </PanelSectionRow> : null}
    <PanelSectionRow><ToggleField label="Dim automatically after sunset"
      description={status.weather_location
        ? `Uses sunset and sunrise for ${status.weather_location.name}, ${status.weather_location.country}.`
        : "Choose a city to calculate exact local sunset and sunrise times."}
      disabled={!status.weather_location}
      checked={status.night_mode_enabled}
      onChange={async (enabled) => setStatus(await setSetting("night_mode_enabled", enabled))} /></PanelSectionRow>
    {!compact||status.night_mode_enabled?<PanelSectionRow><SliderField label="Night brightness"
      description={`${status.night_mode_brightness}% of day brightness · ${nightOutput}/255. Moving the slider previews the night output immediately.`}
      min={10} max={100} step={5} showValue valueSuffix="%" value={status.night_mode_brightness}
      onChange={(value) => void preview("night", "night_mode_brightness", value)} /></PanelSectionRow>:null}
    {nightOutput < 8 && (!compact||status.night_mode_enabled) ? <PanelSectionRow>
      <LowBrightnessWarning mode="Night" value={nightOutput} />
    </PanelSectionRow> : null}
    <SettingsDetails title="Current brightness and hardware"><PanelSectionRow><div style={{ width: "100%", fontSize: ".79em", lineHeight: 1.5 }}>
      <div>Current output: <b>{currentOutput}</b></div>
      <div>Location: <b>{status.weather_location ? `${status.weather_location.name}, ${status.weather_location.country}` : "Not set"}</b></div>
      <div>Control: <b>{brightness.supported ? "Hardware brightness" : "Colour brightness adjustment"}</b></div>
      {brightness.saved_steam_brightness != null
        ? <div>Steam value saved for handoff: <b>{brightness.saved_steam_brightness}/255</b></div> : null}
      {!brightness.supported && status.available
        ? <div style={{ color: "#ffd27a" }}>This driver has no brightness_scale. GabeCubeAura is using RGB attenuation instead.</div> : null}
      {brightness.startup_recovered
        ? <div style={{ color: "#93f7a7" }}>A brightness value left by an interrupted session was restored safely.</div>
        : null}
    </div></PanelSectionRow></SettingsDetails>
    <PanelSectionRow><ButtonItem label={status.weather_location ? "Change city" : "Choose city"}
      onClick={() => { if(compact){compact.open({category:'weather',tab:'forecast'});return;} setChangingCity(!changingCity); setCityResults([]); setMessage(""); }}>
      {changingCity ? "Close" : "Open city search"}
    </ButtonItem></PanelSectionRow>
    {changingCity ? <>
      <PanelSectionRow><TextField label="City or postal code" value={cityQuery}
        onChange={(event) => setCityQuery(event.currentTarget.value)} /></PanelSectionRow>
      <PanelSectionRow><TextField label="Country (optional)" value={countryQuery}
        onChange={(event) => setCountryQuery(event.currentTarget.value)} /></PanelSectionRow>
      <PanelSectionRow><ButtonItem label="Find city" disabled={searching || cityQuery.trim().length < 2}
        onClick={() => void findCity()}>{searching ? "Searching…" : "Search"}</ButtonItem></PanelSectionRow>
      {cityResults.map((city, index) => <PanelSectionRow key={`${city.latitude}:${city.longitude}:${index}`}>
        <ButtonItem label={`${city.name}, ${city.country}`} untranslatedProps={["label"]} onClick={() => void chooseCity(city)}>Use this city</ButtonItem>
      </PanelSectionRow>)}
    </> : null}
    {message ? <PanelSectionRow><div style={{ color: "#ffd27a", fontSize: ".78em" }}>{message}</div></PanelSectionRow> : null}
  </PanelSection>;
}

function ScreenSyncPanel({ status, setStatus }: { status: Status; setStatus: (next: Status) => void }) {
  const [showLiveDiagnostics, setShowLiveDiagnostics] = useState(false);
  const activation = status.screen_sync.activation;
  const directGamescopeSelector = status.screen_sync.node_id === null
    && status.screen_sync.capture_selector.toLowerCase().includes("gamescope name");
  const activationLabel = activation.reason === "manual-preview"
    ? `Manual preview (${Math.ceil(activation.preview_remaining_s)} s remaining)`
    : activation.reason === "steam-screensaver"
      ? "Following Steam screensaver"
      : activation.reason === "game-route"
        ? "Following the current game"
        : activation.screensaver_detection === "unavailable"
          ? "Steam screensaver detection unavailable"
          : activation.screensaver_detection === "error"
            ? `Steam screensaver detection error: ${activation.screensaver_detail}`
            : "Waiting for an activation context";
  const phase = status.screen_sync.fallback_active
    ? `Using Customization+: ${status.screen_sync.fallback_reason}`
    : status.screen_sync.phase === "capturing"
    ? `Capturing ${status.screen_sync.frames_per_second.toFixed(1)} frames/s`
    : status.screen_sync.phase === "conflict"
      ? "Paused because another app is capturing Gamescope"
      : status.screen_sync.phase === "waiting"
        ? `Waiting for Gamescope${status.screen_sync.error ? `: ${status.screen_sync.error}` : ""}`
      : status.screen_sync.phase === "error"
        ? `Unavailable: ${status.screen_sync.error}`
        : status.current_display === "screen_sync" && status.game.appid > 0
          ? "Waiting for safe LED ownership"
          : "Select Screen Sync as the in-game display or for the current game";
  return <>
    <SettingsDetails title="Capture status"><PanelSection title="Screen Sync">
      <SettingsHelpText><PanelSectionRow><div style={{ fontSize: ".8em", opacity: .82 }}>
        Matches the visible picture to the light bar. Frames stay in memory and are never saved or sent over the network.
      </div></PanelSectionRow></SettingsHelpText>
      <PanelSectionRow><ToggleField
        label="Show live diagnostics"
        description="Shows capture source, PipeWire state, frame rate and the live 17-colour preview. Intended for troubleshooting."
        checked={showLiveDiagnostics}
        onChange={setShowLiveDiagnostics} />
      </PanelSectionRow>
      {showLiveDiagnostics ? <PanelSectionRow><div style={{ width: "100%", fontSize: ".78em", opacity: .78 }}>
        <div>Capture revision: {status.screen_sync.revision}</div>
        <div style={{ color: status.debug.engine_running ? "#93f7a7" : "#ff9a9a" }}>
          Runtime: {status.debug.engine_running
            ? `render loop live · decision ${formatAge(status.debug.decision_age_s)}`
            : `render loop stopped${status.error ? ` · ${status.error}` : ""}`}
        </div>
        {status.debug.last_runtime_error ? <div style={{ color: "#ff9a9a" }}>
          Last runtime fault ({formatAge(status.debug.last_runtime_error_age_s)}): {status.debug.last_runtime_error}
        </div> : null}
        <div>{phase}</div>
        {status.screen_sync.node_name ? <div>Source: {status.screen_sync.node_name}</div> : null}
        {status.screen_sync.runtime_dir ? <div>PipeWire session: {status.screen_sync.runtime_dir}</div> : null}
        {status.screen_sync.capture_identity ? <div>PipeWire identity: {status.screen_sync.capture_identity}</div> : null}
        {status.screen_sync.capture_selector ? <div>Selector: {status.screen_sync.capture_selector}</div> : null}
        {directGamescopeSelector
          ? <div style={{ color: status.screen_sync.phase === "capturing" ? "#93f7a7" : "#ffd37a" }}>
            {status.screen_sync.phase === "capturing"
              ? "Direct Gamescope source active. Numeric node enumeration is not required."
              : "Gamescope is not ready in this PipeWire session yet. Retrying automatically."}
          </div>
          : null}
        {status.screen_sync.orphan_processes_cleaned > 0
          ? <div>Recovered stale capture processes: {status.screen_sync.orphan_processes_cleaned}</div>
          : null}
        {status.screen_sync.capture_sessions_released > 0
          ? <div>Failed capture sessions released before retry: {status.screen_sync.capture_sessions_released}</div>
          : null}
        {status.screen_sync.last_release_error
          ? <div>Last released session: {status.screen_sync.last_release_error}</div>
          : null}
        {status.screen_sync.phase === "error" && status.screen_sync.discovery_detail
          ? <div>Discovery: {status.screen_sync.discovery_detail}</div>
          : null}
        {status.screen_sync.crop_top || status.screen_sync.crop_bottom
          ? <div>Ignored black bars: {status.screen_sync.crop_top} top, {status.screen_sync.crop_bottom} bottom</div>
          : null}
        <PalettePreview source="screen_sync" colors={status.screen_sync.colors} />
      </div></PanelSectionRow> : null}
    </PanelSection></SettingsDetails>
    <SettingsDetails title="Activation and preview"><PanelSection title="Activation">
      <ScreensaverLightBarChoice status={status} setStatus={setStatus}/>
      <PanelSectionRow><div style={{ width: "100%", fontSize: ".78em", opacity: .78 }}>
        <div>{activationLabel}</div>
        <div>In-game default: {displayLabel(status.game_display)}</div>
        {status.display_override !== "inherit" && status.game.appid > 0
          ? <div>Current game override: {displayLabel(status.display_override)}</div>
          : null}
      </div></PanelSectionRow>
      <PanelSectionRow><ButtonItem
        label="Preview Screen Sync"
        description="Uses the real capture and rendering path for 15 seconds without changing Display routing."
        onClick={() => void previewScreenSync().then(setStatus).catch(actionFailed)}>
        Preview for 15 seconds
      </ButtonItem></PanelSectionRow>
    </PanelSection></SettingsDetails>
    <PanelSection title="Screen mapping">
      <PanelSectionRow><DropdownItem label="Style" rgOptions={SCREEN_SYNC_STYLE_OPTIONS}
        selectedOption={status.screen_sync_style}
        onChange={async (option) => setStatus(await setSetting("screen_sync_style", String(option.data)))} /></PanelSectionRow>
      <PanelSectionRow><DropdownItem label="Reactivity" rgOptions={SCREEN_SYNC_REACTIVITY_OPTIONS}
        selectedOption={status.screen_sync_reactivity}
        onChange={async (option) => setStatus(await setSetting("screen_sync_reactivity", String(option.data)))} /></PanelSectionRow>
      <PanelSectionRow><DropdownItem label="Colour intensity" rgOptions={SCREEN_SYNC_COLOUR_OPTIONS}
        selectedOption={status.screen_sync_colour_intensity}
        onChange={async (option) => setStatus(await setSetting("screen_sync_colour_intensity", String(option.data)))} /></PanelSectionRow>
      <PanelSectionRow><SliderField label="Brightness"
        description="34 is the minimum retained because lower values switch the physical light bar off."
        value={status.screen_sync_brightness} min={34} max={255} step={1} showValue valueSuffix=" / 255"
        onChange={async (value) => setStatus(await setSetting("screen_sync_brightness", value))} /></PanelSectionRow>
      <PanelSectionRow><ToggleField label="Ignore cinematic black bars"
        description="Applies a crop only after the same top and bottom bars are detected in three consecutive frames."
        checked={status.screen_sync_ignore_black_bars}
        onChange={async (value) => setStatus(await setSetting("screen_sync_ignore_black_bars", value))} /></PanelSectionRow>
      <PanelSectionRow><SliderField label="Black threshold"
        description="Pixels at or below this brightness are treated as fully off."
        value={status.screen_sync_black_threshold} min={0} max={32} step={1} showValue
        onChange={async (value) => setStatus(await setSetting("screen_sync_black_threshold", value))} /></PanelSectionRow>
    </PanelSection>
    <SettingsDetails title="Capture fallback"><PanelSection title="Capture fallback">
      <SettingsHelpText><PanelSectionRow><div style={{ fontSize: ".76em", opacity: .76 }}>
        When Screen Sync pauses for Steam Game Recording or another capture consumer, Customization+ takes over automatically. The centre LED remains red while recording.
      </div></PanelSectionRow></SettingsHelpText>
      {showLiveDiagnostics && status.screen_sync.fallback_active ? <PanelSectionRow><div style={{ fontSize: ".78em" }}>
        Active: {status.screen_sync.fallback_reason}
      </div></PanelSectionRow> : null}
    </PanelSection></SettingsDetails>
    <SettingsDetails title="Capture safety"><PanelSection title="Capture safety">
      <SettingsHelpText><PanelSectionRow>
        <div style={{ fontSize: ".76em", opacity: .74, paddingBottom: 8 }}>
          Screen Sync uses the local Gamescope PipeWire video source at 34 by 18 pixels and 10 frames per second. If Steam Game Recording, screen sharing, or another Gamescope capture consumer is active, capture stops and the fallback is used instead of competing for the stream.
        </div>
      </PanelSectionRow></SettingsHelpText>
    </PanelSection></SettingsDetails>
  </>;
}

function AudioContextMapping({ context, status, setStatus }: {
  context: "home" | "game";
  status: Status;
  setStatus: (next: Status) => void;
}) {
  const styleKey = context === "home" ? "audio_sync_home_style" : "audio_sync_game_style";
  const paletteKey = context === "home" ? "audio_sync_home_palette" : "audio_sync_game_palette";
  const colourKeys: [
    "audio_sync_home_colour_low" | "audio_sync_game_colour_low",
    "audio_sync_home_colour_middle" | "audio_sync_game_colour_middle",
    "audio_sync_home_colour_high" | "audio_sync_game_colour_high",
  ] = context === "home"
    ? ["audio_sync_home_colour_low", "audio_sync_home_colour_middle", "audio_sync_home_colour_high"]
    : ["audio_sync_game_colour_low", "audio_sync_game_colour_middle", "audio_sync_game_colour_high"];
  const style = status[styleKey];
  const palette = status[paletteKey];
  const recommended = AUDIO_SYNC_STYLE_TUNING[style];
  const activeContext = context === "home" ? status.game.appid === 0 : status.game.appid > 0;
  return <PanelSection title={context === "home" ? "Home pattern and palette" : "In-game pattern and palette"}>
    <PanelSectionRow><div style={{ fontSize: ".76em", opacity: .78 }}>
      {context === "home"
        ? "Used when no game is running and Home is routed to Audio Sync."
        : "Used when a game is running and its display route resolves to Audio Sync."}
      {activeContext ? " This is the active context." : ""}
    </div></PanelSectionRow>
    <PanelSectionRow><DropdownItem label="Pattern" rgOptions={AUDIO_SYNC_STYLE_OPTIONS}
      selectedOption={style}
      onChange={async (option) => setStatus(await setSetting(styleKey, String(option.data)))} /></PanelSectionRow>
    <PanelSectionRow><DropdownItem label="Palette" rgOptions={AUDIO_SYNC_PALETTE_OPTIONS}
      selectedOption={palette}
      onChange={async (option) => setStatus(await setSetting(paletteKey, String(option.data)))} /></PanelSectionRow>
    {palette === "custom" ? colourKeys.map((key, index) => <PanelSectionRow key={key}>
      <PreciseColorEditor label={["High frequencies · edges", "Middle frequencies · shoulders", "Low frequencies · centre"][index]}
        color={status[key]}
        onChange={(color) => void setSetting(key, color).then(setStatus).catch(actionFailed)} />
    </PanelSectionRow>) : null}
    <PanelSectionRow><div style={{ fontSize: ".76em", opacity: .78 }}>
      <b>Recommended shared tuning:</b> {recommended.reactivity[0].toUpperCase() + recommended.reactivity.slice(1)} · Brightness {recommended.brightness} / 255<br />
      {recommended.note}
    </div></PanelSectionRow>
    <PanelSectionRow><ButtonItem label="Apply recommended shared tuning"
      description="Loads the Steam Machine reference response for this pattern. It changes shared reactivity and brightness, but not either context palette."
      onClick={() => void setSetting(styleKey, style).then(setStatus).catch(actionFailed)}>
      Apply
    </ButtonItem></PanelSectionRow>
    {palette === "screen-sync" ? <SettingsHelpText><PanelSectionRow><div style={{ fontSize: ".76em", opacity: .74 }}>
      Screen Sync extracts three coherent colours from live Gamescope. Artwork is used when live capture is unavailable. During session changes, the last stable palette is held until a new contextual palette is ready.
    </div></PanelSectionRow></SettingsHelpText> : null}
    {palette === "artwork" ? <SettingsHelpText><PanelSectionRow><div style={{ fontSize: ".76em", opacity: .74 }}>
      Artwork uses the current game's three-colour artwork palette. During session changes, the last stable palette is held until the new artwork palette is ready.
    </div></PanelSectionRow></SettingsHelpText> : null}
  </PanelSection>;
}

function AudioTimingReadout({ status }: { status: Status }) {
  const audio = status.audio_sync;
  const timing = audio.response_timing;
  const actualBlockMs = audio.blocks_per_second > 0
    ? 1000 / audio.blocks_per_second
    : null;
  const sampleAgeMs = audio.frame_age_s == null ? null : audio.frame_age_s * 1000;
  const pair = (value: { rise_ms: number; fall_ms: number }) =>
    `${Math.round(value.rise_ms)} / ${Math.round(value.fall_ms)} ms`;
  return <PanelSectionRow><div style={{ width: "100%", fontSize: ".76em", opacity: .82 }}>
    <div><b>Audio timing</b></div>
    <div>
      Analysis block: {audio.analysis_hop_ms.toFixed(0)} ms target
      {actualBlockMs == null ? "" : ` · ${actualBlockMs.toFixed(1)} ms actual`}
      {` · ${audio.blocks_per_second.toFixed(1)} blocks/s`}
    </div>
    <div>
      FFT window: {audio.analysis_window_ms.toFixed(1)} ms · PipeWire request: {audio.capture_latency_ms.toFixed(0)} ms
    </div>
    <div>
      LED request: {audio.led_request_interval_ms.toFixed(0)} ms · renderer floor: {audio.led_render_floor_ms.toFixed(0)} ms
    </div>
    <div>
      Sample age: {sampleAgeMs == null ? "waiting" : `${sampleAgeMs.toFixed(1)} ms`}
      {` · residual buffer ${audio.buffered_ms.toFixed(1)} ms · queue ${audio.queued_blocks}`}
    </div>
    <div>
      Adaptive source level: shared {audio.hifi_metrics.window_s.toFixed(1)} / 10.2 s programme window
    </div>
    <div style={{ marginTop: 3 }}>
      {timing.reactivity[0].toUpperCase() + timing.reactivity.slice(1)} 90% rise / fall:
      {` level ${pair(timing.level)} · impact ${pair(timing.impact)} · attack ${pair(timing.attack)} · texture ${pair(timing.texture)} · background ${pair(timing.background)}`}
    </div>
    {status.audio_sync_style === "hifi-crest" ? <div>
      Crest: {Math.round(timing.crest.cooldown_ms)} ms retrigger · {Math.round(timing.crest.centre_to_edge_ms)} ms centre to edge · {Math.round(timing.crest.lifetime_ms)} ms base lifetime
    </div> : EXPERIMENTAL_AUDIO_DESCRIPTIONS[status.audio_sync_style] ? <div>
      Animation cadence: 60 ms frames · optical blending active
    </div> : null}
    {audio.dropped_blocks > 0 ? <div style={{ color: "#ff9a9a" }}>
      Warning: {audio.dropped_blocks} analysis block{audio.dropped_blocks === 1 ? "" : "s"} dropped because the processing queue filled.
    </div> : null}
  </div></PanelSectionRow>;
}

function AudioSyncPanel({ status, setStatus }: { status: Status; setStatus: (next: Status) => void }) {
  const [showLiveDiagnostics, setShowLiveDiagnostics] = useState(false);
  const activeHome = status.home_display === "audio_sync";
  const activeGame = status.game_display === "audio_sync";
  const context = activeHome && activeGame ? "Everywhere" : activeHome ? "Home" : activeGame ? "In game" : "Not selected";
  const phase = status.audio_sync.phase === "capturing"
    ? `Listening at ${status.audio_sync.sample_rate / 1000} kHz stereo`
    : status.audio_sync.phase === "error"
      ? `Unavailable: ${status.audio_sync.error}`
      : status.current_display === "audio_sync"
        ? "Waiting for safe LED ownership"
        : "Select Audio Sync in Display routing or start a preview";
  return <>
    <SettingsDetails title="Audio status and preview"><PanelSection title="Audio Sync">
      <SettingsHelpText><PanelSectionRow><div style={{ fontSize: ".8em", opacity: .84 }}>
        Turns the mixed system output into a responsive 17-pixel display. Capture and analysis stay local in memory. Audio is never saved or sent over the network.
      </div></PanelSectionRow></SettingsHelpText>
      <PanelSectionRow><ToggleField
        label="Show live diagnostics"
        description="Shows capture state, live levels, palette source, timing and the 17-LED preview. Intended for troubleshooting."
        checked={showLiveDiagnostics}
        onChange={setShowLiveDiagnostics} />
      </PanelSectionRow>
      {showLiveDiagnostics ? <PanelSectionRow><div style={{ width: "100%", fontSize: ".78em", opacity: .8 }}>
        <div>Permanent display: <b>{context}</b></div>
        <div>{phase}</div>
        <div>Capture revision: {status.audio_sync.revision}</div>
        {status.audio_sync.runtime_dir ? <div>PipeWire session: {status.audio_sync.runtime_dir}</div> : null}
        {status.audio_sync.capture_identity ? <div>PipeWire identity: {status.audio_sync.capture_identity}</div> : null}
        {status.audio_sync.phase === "capturing" ? <div>
          Left {Math.round(status.audio_sync.left_level * 100)}% · Right {Math.round(status.audio_sync.right_level * 100)}%
        </div> : null}
        {["screen-sync", "artwork"].includes(status.audio_sync_palette) && status.audio_sync.screen_palette.length === 3 ? <div>
          Context palette: {status.audio_sync.screen_palette.map((color) =>
            `#${color.map((channel) => channel.toString(16).padStart(2, "0")).join("").toUpperCase()}`
          ).join(" · ")}
        </div> : null}
        {ADAPTIVE_AUDIO_STYLES.includes(status.audio_sync_style) && ["screen-sync", "artwork"].includes(status.audio_sync_palette) ? <div>
          Palette source: <b>{status.audio_sync.palette_source === "screen-sync" ? "Screen Sync" : status.audio_sync.palette_source === "artwork" ? "Artwork" : status.audio_sync.palette_source === "held-transition" ? "Last stable palette" : status.audio_sync.palette_source === "selected" ? "Selected palette" : "Sapphire fallback"}</b>
          {status.audio_sync_palette === "screen-sync" && status.audio_sync.palette_source !== "screen-sync" && status.screen_sync.error ? ` · ${status.screen_sync.error}` : ""}
        </div> : null}
        <PalettePreview source="audio_sync" colors={status.audio_sync.colors} />
        {ADAPTIVE_AUDIO_STYLES.includes(status.audio_sync_style) ? <div>
          Impact {Math.round(status.audio_sync.hifi_metrics.impact * 100)}% · Attack {Math.round(status.audio_sync.hifi_metrics.attack * 100)}% · Texture {Math.round(status.audio_sync.hifi_metrics.texture * 100)}% · Stereo {Math.round(status.audio_sync.hifi_metrics.stereo * 100)}% · Window {status.audio_sync.hifi_metrics.window_s.toFixed(1)} s
        </div> : null}
      </div></PanelSectionRow> : null}
      {showLiveDiagnostics ? <AudioTimingReadout status={status} /> : null}
      <PanelSectionRow><ButtonItem label="Preview Audio Sync"
        description="Uses the real system audio path for 15 seconds without changing Display routing."
        onClick={() => void previewAudioSync().then(setStatus).catch(actionFailed)}>
        Preview for 15 seconds
      </ButtonItem></PanelSectionRow>
    </PanelSection></SettingsDetails>
    <AudioContextMapping context="home" status={status} setStatus={setStatus} />
    <AudioContextMapping context="game" status={status} setStatus={setStatus} />
    <PanelSection title="Shared response">
      <SettingsHelpText><PanelSectionRow><div style={{ fontSize: ".76em", opacity: .78 }}>
        Reactivity and brightness are shared by Home and in-game patterns. Automatic source-level matching stays active for every pattern.
      </div></PanelSectionRow></SettingsHelpText>
      <PanelSectionRow><DropdownItem label="Reactivity" rgOptions={AUDIO_SYNC_REACTIVITY_OPTIONS}
        selectedOption={status.audio_sync_reactivity}
        onChange={async (option) => setStatus(await setSetting("audio_sync_reactivity", String(option.data)))} /></PanelSectionRow>
      <PanelSectionRow><SliderField label="Brightness"
        description="34 is the minimum retained because lower values switch the physical light bar off."
        value={status.audio_sync_brightness} min={34} max={255} step={1} showValue valueSuffix=" / 255"
        onChange={async (value) => setStatus(await setSetting("audio_sync_brightness", value))} /></PanelSectionRow>
    </PanelSection>
    <SettingsDetails title="Audio recovery and priority"><PanelSection title="Priority and recovery">
      <SettingsHelpText><PanelSectionRow><div style={{ fontSize: ".77em", opacity: .8 }}>
        Steam and temporary alerts keep priority. Screensaver Screen Sync pauses Audio Sync, which resumes automatically afterward.
      </div></PanelSectionRow></SettingsHelpText>
      {status.audio_sync_style === "audio-pulse" ? <SettingsHelpText><PanelSectionRow><div style={{ fontSize: ".76em", opacity: .74 }}>
        Audio Pulse applies one global audio envelope to a mirrored three-colour gradient from the selected palette.
      </div></PanelSectionRow></SettingsHelpText> : null}
      {status.audio_sync_style === "bass" ? <SettingsHelpText><PanelSectionRow><div style={{ fontSize: ".76em", opacity: .74 }}>
        Bass pulse mirrors the selected three-colour palette as an edge, shoulder, centre, shoulder, edge gradient. Low-frequency energy remains strongest at the centre and softer toward both edges.
      </div></PanelSectionRow></SettingsHelpText> : null}
      {status.audio_sync_style === "hifi-crest" ? <SettingsHelpText><PanelSectionRow><div style={{ fontSize: ".76em", opacity: .74 }}>
        Hi-Fi Crest places bass impact at the centre, mid attack on both shoulders and high texture at the edges. Stereo balance weights each side, while strong bass onsets launch a restrained centre-out crest.
      </div></PanelSectionRow></SettingsHelpText> : null}
      {EXPERIMENTAL_AUDIO_DESCRIPTIONS[status.audio_sync_style] ? <PanelSectionRow><div style={{ fontSize: ".76em", opacity: .74 }}>
        <b>Experimental optical pattern.</b> {EXPERIMENTAL_AUDIO_DESCRIPTIONS[status.audio_sync_style]}
      </div></PanelSectionRow> : null}
    </PanelSection></SettingsDetails>
  </>;
}

type Page = "profiles" | "quick" | "routing" | "customization" | "artwork" | "performance" | "screen-sync" | "audio-sync" | "launches" | "countdown" | "events" | "controllers" | "weather" | "pixel-settings" | "pixel-artwork" | "updates" | "advanced";

const statusRefreshDelay = (page: Page) => {
  if (page === "events" || page === "controllers" || page === "launches") return 1000;
  if (page === "weather" || page === "performance"
      || page === "screen-sync" || page === "audio-sync") return 2000;
  if (page === "quick") return 2000;
  return 10000;
};

// Settings routes mount separate Content instances. Preserve the last valid
// snapshot between them so navigation never falls back to a blank Loading row
// while the backend refreshes in the background.
let retainedStatus: Status | null = null;

const PAGE_END_LABELS: Record<Exclude<Page, "quick">, string> = {
  profiles: "Ambience profiles",
  routing: "Display routing",
  customization: "Customization+",
  artwork: "Artwork",
  performance: "Performance",
  "screen-sync": "Screen Sync",
  "audio-sync": "Audio Sync",
  launches: "Game launches",
  countdown: "Playtime",
  events: "Light events",
  controllers: "Controllers",
  weather: "Weather",
  "pixel-settings": "Pixel Studio Settings",
  "pixel-artwork": "Faceplate Artwork Studio",
  updates: "Updates",
  advanced: "Advanced",
};

function SettingsPageEnd({ page, setStatus }: {
  page: Exclude<Page, "quick">;
  setStatus: (next: Status) => void;
}) {
  return <PanelSection>
    <PanelSectionRow><ButtonItem
      label={`End of ${PAGE_END_LABELS[page]} settings`}
      description="This final row keeps the complete page reachable with controller navigation."
      onClick={() => void getStatus().then(setStatus).catch(actionFailed)}>
      Refresh status
    </ButtonItem></PanelSectionRow>
  </PanelSection>;
}


function SetupFrame({ step, title, description, children, showScrollCue = false }: {
  step: 1 | 2 | 3;
  title: string;
  description: string;
  children: ReactNode;
  showScrollCue?: boolean;
}) {
  const steps = ["Experience", "Brightness", "Review"];
  const [scrollCueVisible, setScrollCueVisible] = useState(showScrollCue);

  useEffect(() => {
    setScrollCueVisible(showScrollCue);
  }, [showScrollCue, step]);

  return <Focusable aria-label={`GabeCubeAura setup, step ${step} of 3`} style={{
    width: "100%",
    height: "100%",
    maxHeight: "100%",
    boxSizing: "border-box",
    overflow: "hidden",
    position: "relative",
    background: "var(--gpSystemDarkestGrey,#0e141b)",
  }} onScrollCapture={() => setScrollCueVisible(false)}>
    <ScrollPanel><div style={{ width: "100%", maxWidth: 1040, margin: "0 auto", boxSizing: "border-box", padding: "40px clamp(32px, 6vw, 88px) 156px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 28 }}>
        <TbCubeSpark size={36} color="#55b9f3" />
        <div>
          <div style={{ fontSize: "1.35em", fontWeight: 700 }}>GabeCubeAura</div>
          <div style={{ fontSize: ".78em", opacity: .68 }}>First-time setup</div>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 10, marginBottom: 34 }}>
        {steps.map((label, index) => {
          const number = index + 1;
          const active = number === step;
          const complete = number < step;
          return <div key={label} style={{
            padding: "10px 14px",
            textAlign: "center",
            fontSize: ".78em",
            fontWeight: active ? 700 : 400,
          }}>{complete ? "✓ " : `${number}. `}{label}</div>;
        })}
      </div>
      <div style={{ marginBottom: 24 }}>
        <DialogHeader>{title}</DialogHeader>
        <div style={{ maxWidth: 760, fontSize: ".95em", lineHeight: 1.5, opacity: .75 }}>{description}</div>
      </div>
      <DialogBody><DialogControlsSection>{children}</DialogControlsSection></DialogBody>
    </div></ScrollPanel>
    {scrollCueVisible ? <div role="note" style={{
      position: "absolute",
      left: "50%",
      bottom: 172,
      zIndex: 20,
      transform: "translateX(-50%)",
      pointerEvents: "none",
      display: "flex",
      alignItems: "center",
      gap: 9,
      whiteSpace: "nowrap",
      padding: "10px 16px",
      borderRadius: 999,
      color: "#e9f7ff",
      background: "rgba(12, 23, 34, .94)",
      border: "1px solid rgba(104, 199, 255, .55)",
      boxShadow: "0 10px 28px rgba(0, 0, 0, .42)",
      fontSize: ".82em",
      fontWeight: 700,
    }}><span aria-hidden="true" style={{ fontSize: "1.35em", lineHeight: 1 }}>↓</span> Scroll down for the buttons</div> : null}
  </Focusable>;
}

function LowBrightnessWarning({ mode, value }: { mode: "Day" | "Night"; value: number }) {
  if (value >= 8) return null;
  return <Localized><div style={{ margin: "0 0 18px", padding: "11px 14px", borderRadius: 10,
    color: "#ff8f8f", background: "rgba(190, 32, 42, .16)", border: "1px solid rgba(255, 92, 102, .52)", fontWeight: 700 }}>
    {mode} output is {value}/255. Below 8/255, the lighting experience may be strongly affected.
  </div></Localized>;
}


function FirstRunSetupRoute({faceplateOnly=false}:{faceplateOnly?:boolean}) {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    void getStatus().then((next) => {
      if (alive) setStatus(next);
    }).catch((reason) => {
      if (alive) setError(String(reason));
    });
    return () => { alive = false; };
  }, []);

  if (!status) return <SetupFrame step={1} title="Loading GabeCubeAura"
    description="Preparing the first-time setup.">
    <div style={{ opacity: .76 }}>{error || "Reading the saved configuration…"}</div>
    {error ? <div style={{ marginTop: 16 }}><ButtonItem label="Back" onClick={() => Navigation.NavigateBack()}>Return to Steam</ButtonItem></div> : null}
  </SetupFrame>;

  return <FirstRunOnboarding faceplateOnly={faceplateOnly} status={status} setStatus={next=>{retainedStatus=next;publishQuickSetupStatus(next);setStatus(next);}}
    openBrowser={openCopyCapableBrowser} onClose={() => Navigation.NavigateBack()} />;
}

const FACEPLATE_ARTWORK_SEARCH_OPTIONS = [
  { data: "static", label: "Static square · 1:1" },
  { data: "animated_any", label: "Animated · hero, portrait or wide" },
  { data: "hero_pan", label: "Static horizontal hero · panorama" },
];

const FACEPLATE_LOOP_CLEANUP_OPTIONS = [
  { data: "no", label: "No cut · keep every frame" },
  { data: "soft", label: "Soft · automatic" },
  { data: "medium", label: "Medium · best seam within 0.5 s" },
  { data: "aggressive", label: "Aggressive · best seam within 1 s" },
];

const FACEPLATE_RESULT_PREVIEW_OPTIONS = [
  { data: "artwork", label: "Artwork in-game · exact prepared GIF" },
  { data: "dashboard", label: "Artwork Dashboard · artwork with live overlay" },
  { data: "weather-dashboard", label: "Weather Dashboard · current atmosphere" },
];

const FACEPLATE_ARTWORK_STYLE_OPTIONS = [
  { data: "art", label: "Artwork only" },
  { data: "logo_dim", label: "Artwork + logo on shaded band" },
  { data: "logo", label: "Artwork + logo, no band" },
  { data: "logo_only", label: "Logo only, black background" },
];
const FACEPLATE_LOGO_POSITION_OPTIONS = [
  { data: "bottom", label: "Bottom · above status bar" },
  { data: "bottom_rail", label: "Bottom · replaces status bar" },
  { data: "centre", label: "Centre" },
  { data: "top", label: "Top · replaces clock" },
];

function PixelStudioArtworkPanel({ status, setStatus }: {
  status: Status;
  setStatus: (next: Status) => void;
}) {
  const [games, setGames] = useState<FaceplateInstalledGame[]>([]);
  const [gameQuery, setGameQuery] = useState("");
  const [selectedGame, setSelectedGame] = useState<FaceplateInstalledGame | null>(null);
  const [choosingGame, setChoosingGame] = useState(true);
  const [preference, setPreference] = useState<"static" | "animated_any" | "hero_pan">("static");
  const [results, setResults] = useState<FaceplateArtworkAsset[]>([]);
  const [resultIndex, setResultIndex] = useState(0);
  const [selectedAsset, setSelectedAsset] = useState<FaceplateArtworkAsset | null>(null);
  const [artworkState, setArtworkState] = useState<FaceplateArtworkState | null>(null);
  const [library, setLibrary] = useState<FaceplateArtworkLibraryEntry[]>([]);
  const [librarySelection, setLibrarySelection] = useState("");
  const [libraryBusy, setLibraryBusy] = useState(false);
  const [showAdjustments, setShowAdjustments] = useState(false);
  const [cropEditing, setCropEditing] = useState(false);
  const [previewPlaying, setPreviewPlaying] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [dashboardPreview, setDashboardPreview] = useState("");
  const [dashboardPreviewBusy, setDashboardPreviewBusy] = useState(false);
  const [weatherDashboardPreview, setWeatherDashboardPreview] = useState("");
  const [nativePreview, setNativePreview] = useState("");
  const [nativePreviewBusy, setNativePreviewBusy] = useState(false);
  const [previewTarget, setPreviewTarget] = useState<
    "artwork" | "dashboard" | "weather-dashboard"
  >("artwork");
  const [cropY, setCropY] = useState(50);
  const [cropX, setCropX] = useState(50);
  const [saturation, setSaturation] = useState(110);
  const [brightness, setBrightness] = useState(100);
  const [logoScale, setLogoScale] = useState(100);
  const logoScaleEdited = useRef(false);
  const [dashboardTreatment, setDashboardTreatment] = useState<"none" | "cinema" | "hero-cut" | "palette-echo">("none");
  const [dashboardCompression, setDashboardCompression] = useState<"compatible" | "balanced" | "fine">("compatible");
  const [dashboardClockSize, setDashboardClockSize] = useState<"compact" | "large">("large");
  const [dashboardShowSession, setDashboardShowSession] = useState(true);
  const [dashboardShowBattery, setDashboardShowBattery] = useState(true);
  const [useForDashboardHome, setUseForDashboardHome] = useState(false);
  type Destination = "game" | "game-dashboard" | "home" | "both";
  const [destination, setDestination] = useState<Destination>("game");
  const [draftPreviewKey, setDraftPreviewKey] = useState("");
  const [appliedDraftKey, setAppliedDraftKey] = useState("");
  const [loopCleanup, setLoopCleanup] = useState<"no" | "soft" | "medium" | "aggressive">("no");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const activateWhenReady = useRef<{ appid: number; destination: Destination } | null>(null);
  const appliedSha = useRef("");
  const applyingPrepared = useRef(false);
  const [deliveryWatch, setDeliveryWatch] = useState(0);
  const [deliveryStatus, setDeliveryStatus] = useState<Awaited<ReturnType<typeof getFaceplateDeliveryStatus>> | null>(null);
  const [deliveryReadError, setDeliveryReadError] = useState("");
  const preparedIdentity = useRef("");
  const prepareFocus = useRef("use-artwork");
  const deliveryKey = useRef("");
  const preparationIdentity = JSON.stringify([
    selectedGame?.appid, selectedAsset?.id, selectedAsset?.kind,
    cropX, cropY, saturation, brightness, logoScale, loopCleanup, preference,
    dashboardTreatment, dashboardCompression,
    dashboardClockSize, dashboardShowSession, dashboardShowBattery,
    status.faceplate_artwork_profiles[String(selectedGame?.appid)]?.style ?? status.faceplate_artwork_style,
    status.faceplate_artwork_profiles[String(selectedGame?.appid)]?.position ?? status.faceplate_logo_position,
  ]);
  const artworkPanelRef = useRef<HTMLDivElement | null>(null);
  const focusFrame = useRef<number | null>(null);
  const libraryRequest = useRef(0);

  const restoreArtworkFocus = useCallback((target: string) => {
    if (focusFrame.current != null) window.cancelAnimationFrame(focusFrame.current);
    let attempts = 0;
    const tryFocus = () => {
      focusFrame.current = null;
      const panel = artworkPanelRef.current;
      const region = panel?.querySelector<HTMLElement>(`[data-artwork-focus="${target}"]`) ?? null;
      if (region?.isConnected) {
        try {
          const focusNav = getFocusNavController();
          if (!focusNav?.m_ActiveContext && focusNav?.m_LastActiveContext) {
            focusNav.FindAnActiveContext?.();
          }
          if (takeArtworkNativeFocus(
            region,
            (getGamepadNavigationTrees() || []) as ArtworkNativeNavigationTree[],
          )) return;
        } catch (error) {
          console.warn("[GabeCubeAura] Pixel Studio focus restore failed", error);
          return;
        }
      }
      attempts += 1;
      if (attempts < 18) focusFrame.current = window.requestAnimationFrame(tryFocus);
    };
    focusFrame.current = window.requestAnimationFrame(tryFocus);
  }, []);

  useEffect(() => () => {
    if (focusFrame.current != null) window.cancelAnimationFrame(focusFrame.current);
  }, []);

  const refreshArtworkState = useCallback(async (appid: number) => {
    if (appid <= 0) return;
    setArtworkState(await getFaceplateArtworkJob(appid));
  }, []);

  const refreshLibrary = useCallback(async () => {
    const request = ++libraryRequest.current;
    const value = await getFaceplateArtworkLibrary();
    // A delete or a newer refresh may have changed the local list while the
    // backend was resolving Steam game names. Never restore that stale list.
    if (request !== libraryRequest.current) return;
    setLibrary(value.entries);
    setLibrarySelection((current) => current && value.entries.some(
      (item) => `${item.appid}:${item.mode}` === current,
    ) ? current : value.entries.length
      ? `${value.entries[0].appid}:${value.entries[0].mode}` : "");
  }, []);

  useEffect(() => {
    void refreshLibrary().catch((error) => {
      console.warn("[GabeCubeAura] artwork library failed", error);
    });
  }, [refreshLibrary]);

  const activatePrepared = useCallback(async (
    appid: number, mode: "static" | "animated" | "pan",
    prepared?: FaceplateArtworkManifest,
    target: Destination = destination,
  ) => {
    if (applyingPrepared.current) return;
    applyingPrepared.current = true;
    try {
      if (STUDIO_UX) {
        setBusy(true);
        appliedSha.current = prepared?.sha256 ?? "";
        if (target === "game" || target === "game-dashboard") {
          await activateFaceplateArtwork(appid, mode, true, prepared?.sha256,
            target === "game" ? "artwork" : "artwork-dashboard");
        } else await commitFaceplateDashboardArtwork(appid, mode, true, target === "home", prepared?.sha256, false);
        await getStatus().then(setStatus).catch((error) => {
          console.warn("[GabeCubeAura] artwork applied; status refresh failed", error);
        });
        setAppliedDraftKey(`${prepared?.sha256}:${target}`);
        if ((target === "home" && status.game.appid === 0) || target === "both"
            || (target.startsWith("game") && status.game.appid === appid)) {
          deliveryKey.current = "";
          setDeliveryStatus(null); setDeliveryReadError("");
          try {
            const receipt = await getFaceplateDeliveryStatus();
            deliveryKey.current = receipt.routing.desired_content_key;
            setDeliveryStatus(receipt);
          } catch { /* The bounded receipt reader below can retry once. */ }
          setDeliveryWatch((previous) => previous + 1);
        }
        await Promise.all([refreshArtworkState(appid), refreshLibrary()]).catch((error) => {
          console.warn("[GabeCubeAura] artwork applied; library refresh failed", error);
        });
        setMessage(target === "home" && status.game.appid > 0
          ? "Saved for Home. It will appear when the game closes."
          : target.startsWith("game") && status.game.appid !== appid
            ? "Saved. It will appear when this game starts."
            : "Display selected. Sending to the Faceplate…");
        restoreArtworkFocus(mode === "static" ? prepareFocus.current : "result-preview");
        return;
      }
      let nextStatus = status;
      if (useForDashboardHome) {
        // One backend transaction activates the prepared copy, stores the
        // Dashboard assignment and reconciles the panel exactly once.
        nextStatus = await assignFaceplateDashboardArtwork(appid, mode);
        setStatus(nextStatus);
      } else {
        await activateFaceplateArtwork(appid, mode);
      }
      await refreshArtworkState(appid);
      await refreshLibrary();
      const removed = prepared?.loop_trimmed_frames ?? 0;
      const cleanup = prepared?.loop_cleanup === "no"
        ? " Every source frame was kept."
        : removed
        ? ` Loop cleanup removed ${removed} frames (${((prepared?.loop_trimmed_ms ?? 0) / 1000).toFixed(1)} s).`
        : prepared?.loop_cleanup ? " Loop cleanup removed no terminal frames." : "";
      const legacyTarget = useForDashboardHome ? "dashboard" : "artwork";
      setPreviewTarget(legacyTarget);
      if (legacyTarget === "dashboard") setDashboardPreviewBusy(true);
      else setNativePreviewBusy(true);
      try {
        if (legacyTarget === "dashboard") {
          const preview = await getFaceplateArtworkDashboardPreview(appid, "", false, true);
          setDashboardPreview(preview.data_uri);
        } else {
          const preview = await getFaceplateArtworkPreview(appid);
          setNativePreview(preview.data_uri);
          if (preview.error) throw new Error(preview.error);
        }
        setMessage(
          `${useForDashboardHome ? "Dashboard Home and game artwork are ready." : "Done. This artwork will appear automatically when the game starts."}${cleanup}`,
        );
      } catch (error) {
        setMessage(
          `${useForDashboardHome ? "Dashboard Home and game artwork are ready." : "The game artwork is active."} Preview unavailable: ${String(error)}`,
        );
      } finally {
        setDashboardPreviewBusy(false); setNativePreviewBusy(false);
        restoreArtworkFocus("result-preview");
      }
    } catch (error) {
      setMessage(`The artwork is ready but could not be activated: ${String(error)}`);
    } finally {
      applyingPrepared.current = false;
      setBusy(false);
    }
  }, [refreshArtworkState, refreshLibrary, restoreArtworkFocus, setStatus, status, useForDashboardHome, destination]);

  useEffect(() => {
    if (!deliveryWatch) return;
    let alive = true;
    let timer: number | null = null;
    const deadline = Date.now() + 120_000;
    const poll = async () => {
      try {
        const next = await getFaceplateDeliveryStatus();
        if (!alive) return;
        setDeliveryStatus(next);
        if (!deliveryKey.current) deliveryKey.current = next.routing.desired_content_key;
        if (next.routing.desired_content_key !== deliveryKey.current) {
          setDeliveryReadError("Saved. Another display is now requested. Check the Decky panel.");
          return;
        }
        const state = next.routing.preparation.state;
        if (next.apply_deferred_reason || (!next.automation.busy && !next.automation.queued
            && (["error", "unconfirmed"].includes(state)
              || (state === "ready" && next.routing.effective_content_key === deliveryKey.current)))) return;
        if (Date.now() >= deadline) {
          setDeliveryReadError("Transfer still pending. Check status in the Decky panel.");
          return;
        }
        timer = window.setTimeout(() => void poll(), 2000);
      } catch {
        if (alive) setDeliveryReadError("Could not read transfer status. Check the Decky panel.");
      }
    };
    void poll();
    return () => { alive = false; if (timer != null) window.clearTimeout(timer); };
  }, [deliveryWatch]);

  useEffect(() => {
    const job = artworkState?.job;
    if (!selectedGame || !STUDIO_UX || job?.state !== "ready" || !job.mode
        || job.appid !== selectedGame?.appid || !job.prepared?.sha256
        || preparedIdentity.current !== preparationIdentity) return;
    let alive = true;
    setDraftPreviewKey("");
    const dashboard = destination !== "game";
    setNativePreview(""); setDashboardPreview("");
    setNativePreviewBusy(true);
    void (dashboard
      ? getFaceplateArtworkDashboardPreview(
          selectedGame.appid, job.mode, true, destination === "home" || destination === "both",
        )
      : getPreparedFaceplateArtworkPreview(selectedGame.appid, job.mode)
    ).then((preview) => {
      if (!alive) return;
      if (dashboard) setDashboardPreview(preview.data_uri);
      else setNativePreview(preview.data_uri);
      setCropEditing(false);
      setDraftPreviewKey(job.prepared?.sha256 ?? "");
      if (appliedSha.current !== job.prepared?.sha256 && !activateWhenReady.current) {
        setMessage("Preview ready. Apply to use this display.");
      }
    }).catch((error) => {
      if (alive) setMessage(`Prepared preview unavailable: ${String(error)}. Prepare again to retry.`);
    }).finally(() => {
      if (alive) {
        setNativePreviewBusy(false); setDashboardPreviewBusy(false);
        const region = artworkPanelRef.current?.querySelector<HTMLElement>(`[data-artwork-focus="${prepareFocus.current}"]`);
        if (!activateWhenReady.current && appliedSha.current !== job.prepared?.sha256
            && (region?.contains(document.activeElement)
              || region?.matches(":focus-within,.gpfocuswithin")
              || region?.querySelector(".gpfocus,.gpfocuswithin"))) {
          restoreArtworkFocus(job.mode === "static" ? "use-static" : "result-preview");
        }
      }
    });
    return () => { alive = false; };
  }, [STUDIO_UX, selectedGame?.appid, artworkState?.job.state, artworkState?.job.prepared?.sha256, destination, preparationIdentity, status.faceplate_dashboard_show_clock, status.faceplate_dashboard_show_weather, status.faceplate_dashboard_contexts]);

  useEffect(() => {
    if (!selectedGame) return;
    void refreshArtworkState(selectedGame.appid).catch((error) => {
      console.warn("[GabeCubeAura] faceplate artwork state failed", error);
    });
  }, [selectedGame?.appid, refreshArtworkState]);

  useEffect(() => {
    const saved = artworkState?.selected;
    if (!saved?.asset_id) return;
    setDashboardTreatment(
      ["cinema", "hero-cut", "palette-echo"].includes(saved.dashboard_treatment || "")
        ? saved.dashboard_treatment as typeof dashboardTreatment : "none",
    );
    setDashboardCompression(
      ["balanced", "fine"].includes(saved.dashboard_compression || "")
        ? saved.dashboard_compression as typeof dashboardCompression : "compatible",
    );
    setDashboardClockSize(saved.dashboard_clock_size === "compact" ? "compact" : "large");
    setDashboardShowSession(saved.dashboard_show_session ?? true);
    setDashboardShowBattery(saved.dashboard_show_battery ?? true);
  }, [selectedGame?.appid, artworkState?.selected?.asset_id]);

  useEffect(() => {
    if (!selectedGame || !artworkState
        || !["queued", "running", "cancelling"].includes(artworkState.job.state)) return;
    let alive = true;
    let timer: number | null = null;
    const poll = async () => {
      try {
        const next = await getFaceplateArtworkJob(selectedGame.appid);
        if (!alive) return;
        setArtworkState(next);
        if (["queued", "running", "cancelling"].includes(next.job.state)) {
          timer = window.setTimeout(() => void poll(), 1000);
        } else if (next.job.state === "ready" && next.job.mode && activateWhenReady.current) {
          const target = activateWhenReady.current;
          activateWhenReady.current = null;
          if (target.appid === selectedGame.appid) {
            await activatePrepared(target.appid, next.job.mode, next.job.prepared, target.destination);
          }
        } else if (["failed", "cancelled"].includes(next.job.state)) {
          activateWhenReady.current = null;
        }
      } catch (error) {
        console.warn("[GabeCubeAura] preparation poll failed", error);
        if (alive) timer = window.setTimeout(() => void poll(), 1500);
      }
    };
    timer = window.setTimeout(() => void poll(), 1000);
    return () => {
      alive = false;
      if (timer != null) window.clearTimeout(timer);
    };
  }, [selectedGame?.appid, artworkState?.job.state, activatePrepared]);

  const gameProfile = selectedGame
    ? status.faceplate_artwork_profiles[String(selectedGame.appid)] : undefined;
  const effectiveArtStyle = gameProfile?.style ?? status.faceplate_artwork_style;
  const effectiveLogoPosition = gameProfile?.position ?? status.faceplate_logo_position;

  const setArtworkPresentation = async (
    key: "style" | "position", value: string,
  ) => {
    if (key === "position" && value === "bottom_rail") {
      setDashboardShowSession(false);
      setDashboardShowBattery(false);
    }
    if (gameProfile && selectedGame) {
      const id = String(selectedGame.appid);
      const next = {
        ...status.faceplate_artwork_profiles,
        [id]: { ...gameProfile, [key]: value },
      };
      setStatus(await setSetting("faceplate_artwork_profiles", next));
    } else {
      setStatus(await setSetting(
        key === "style" ? "faceplate_artwork_style" : "faceplate_logo_position",
        value,
      ));
    }
    restoreArtworkFocus(key === "style" ? "artwork-style" : "logo-position");
  };

  const matchingGames = STUDIO_UX ? installedGameChoices(games, gameQuery) : gameQuery.trim().length >= 2
    ? games.filter((game) => game.name.toLocaleLowerCase().includes(
      gameQuery.trim().toLocaleLowerCase(),
    )).slice(0, 5)
    : [];
  const job = artworkState?.job;
  const jobRunning = Boolean(job && ["queued", "running", "cancelling"].includes(job.state));
  const selectedLibraryEntry = library.find(
    (item) => `${item.appid}:${item.mode}` === librarySelection,
  ) ?? null;
  const preparationMode: "static" | "animated" | "pan" = selectedAsset?.animated
    ? "animated" : selectedAsset?.kind === "hero" && preference === "hero_pan" ? "pan" : "static";
  useEffect(() => {
    if (logoScaleEdited.current || !selectedGame) return;
    const saved = artworkState?.prepared[preparationMode] ?? artworkState?.selected;
    if (saved?.appid === selectedGame.appid) {
      const size = saved.logo_scale;
      setLogoScale(typeof size === "number" && Number.isInteger(size) && size >= 50 && size <= 100 ? size : 100);
    }
  }, [selectedGame?.appid, preparationMode, artworkState?.prepared, artworkState?.selected]);
  const candidate = results[resultIndex] ?? null;
  const previewKind = candidate ? artworkPreviewMedia(candidate.thumb, candidate.animated) : "image";
  const weatherDashboardCondition: WeatherCondition = status.weather.condition ?? "clear_day";
  const weatherDashboardVariant = Number(status[
    `weather_${weatherDashboardCondition}_variant` as keyof Status
  ] ?? 0);
  const resultPreview = (STUDIO_UX ? destination === "game" : previewTarget === "artwork")
    ? nativePreview
    : STUDIO_UX || previewTarget === "dashboard" ? dashboardPreview : weatherDashboardPreview;
  const sourcePreview = candidate ? <ArtworkCropPreview asset={candidate}
    cropX={cropX} cropY={cropY} guides={showAdjustments} videoRef={videoRef}
    onPlay={() => setPreviewPlaying(true)} onPause={() => setPreviewPlaying(false)}
    onError={() => setPreviewError("This preview could not be played. You can still use the artwork.")} /> : null;

  useEffect(() => {
    setPreviewPlaying(false);
    setPreviewError("");
  }, [candidate?.id, candidate?.kind, candidate?.thumb]);

  const loadGames = async () => {
    let nextFocus = "choose-game";
    setBusy(true); setMessage("Reading installed Steam games…");
    try {
      const value = await getFaceplateInstalledGames();
      setGames(value.games); setMessage(`${value.count} installed games found.`);
      if (value.games.length) nextFocus = "game-search";
    } catch (error) {
      setMessage(`Could not read installed games: ${String(error)}`);
    } finally {
      setBusy(false);
      restoreArtworkFocus(nextFocus);
    }
  };

  const search = async () => {
    if (!selectedGame) return;
    setDraftPreviewKey("");
    setBusy(true); setMessage("Searching SteamGridDB…"); setResults([]); setResultIndex(0); setSelectedAsset(null);
    try {
      const value = await searchFaceplateArtwork(selectedGame.appid, preference);
      setResults(value.results);
      setSelectedAsset(value.results[0] ?? null);
      setMessage(value.count ? `${value.count} artwork choices found.` : "No matching artwork found.");
    } catch (error) {
      setMessage(`Search failed: ${String(error)}`);
    } finally {
      setBusy(false);
      restoreArtworkFocus("artwork-search");
    }
  };

  const prepare = async (apply = false) => {
    if (!selectedGame || !selectedAsset) return;
    if (busy || jobRunning) return;
    prepareFocus.current = apply && showAdjustments ? "use-static" : "use-artwork";
    activateWhenReady.current = apply ? { appid: selectedGame.appid, destination } : null;
    appliedSha.current = "";
    preparedIdentity.current = preparationIdentity;
    setDeliveryWatch(0); setDeliveryStatus(null); setDeliveryReadError("");
    setDraftPreviewKey(""); setAppliedDraftKey("");
    setBusy(true); setMessage("Preparing your artwork. The current faceplate image stays visible.");
    try {
      const next = await prepareFaceplateArtwork(
        selectedGame.appid, selectedAsset.id, selectedAsset.kind, preparationMode,
        cropY, saturation, brightness, cropX, dashboardTreatment,
        false, dashboardClockSize,
        dashboardShowSession, dashboardShowBattery,
        dashboardCompression,
        preparationMode === "animated" ? loopCleanup : "no",
        Boolean(STUDIO_UX), logoScale,
      );
      setArtworkState((previous) => ({
        job: next, selected: previous?.selected ?? {}, prepared: previous?.prepared ?? {},
      }));
      if (next.state === "ready" && next.mode && activateWhenReady.current) {
        const target = activateWhenReady.current;
        activateWhenReady.current = null;
        await activatePrepared(target.appid, next.mode, next.prepared, target.destination);
      }
    } catch (error) {
      activateWhenReady.current = null;
      setMessage(`Preparation failed: ${String(error)}`);
    } finally {
      setBusy(false);
      restoreArtworkFocus(prepareFocus.current);
    }
  };

  const chooseGame = (game: FaceplateInstalledGame) => {
    activateWhenReady.current = null;
    appliedSha.current = "";
    preparedIdentity.current = "";
    setDeliveryWatch(0); setDeliveryStatus(null); setDeliveryReadError("");
    setDraftPreviewKey(""); setAppliedDraftKey("");
    setSelectedGame(game); setChoosingGame(false); setGameQuery("");
    setResults([]); setResultIndex(0); setSelectedAsset(null); setShowAdjustments(false);
    setDashboardPreview(""); setWeatherDashboardPreview(""); setNativePreview("");
    setLoopCleanup("no"); setMessage("");
    logoScaleEdited.current = false; setLogoScale(100);
    setPreviewTarget("artwork");
    setUseForDashboardHome(
      status.faceplate_dashboard_home_source === "artwork"
      && status.faceplate_dashboard_home_appid === game.appid,
    );
    restoreArtworkFocus("artwork-type");
  };

  const showResult = (index: number) => {
    setDraftPreviewKey("");
    const nextIndex = Math.max(0, Math.min(results.length - 1, index));
    setResultIndex(nextIndex); setSelectedAsset(results[nextIndex] ?? null); setMessage("");
    restoreArtworkFocus("gallery-navigation");
  };

  const togglePreview = async () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      try { await video.play(); setPreviewError(""); }
      catch { setPreviewError("Preview could not start. The source can still be prepared for the faceplate."); }
    } else video.pause();
    restoreArtworkFocus("preview-playback");
  };

  const useLibraryEntry = async (home: boolean) => {
    if (!selectedLibraryEntry) return;
    setLibraryBusy(true); setMessage("");
    try {
      if (home) {
        if (!selectedLibraryEntry.dashboard_ready) {
          throw new Error("This saved copy must be prepared again before it can be used by Dashboard Home.");
        }
        const next = await assignFaceplateDashboardArtwork(
          selectedLibraryEntry.appid, selectedLibraryEntry.mode,
          false, Boolean(STUDIO_UX),
        );
        setStatus(next);
        const preview = await getFaceplateArtworkDashboardPreview(selectedLibraryEntry.appid, "", false, true);
        setDashboardPreview(preview.data_uri);
        setPreviewTarget("dashboard");
      } else {
        await activateFaceplateArtwork(selectedLibraryEntry.appid, selectedLibraryEntry.mode);
        const preview = await getFaceplateArtworkPreview(selectedLibraryEntry.appid);
        setNativePreview(preview.data_uri);
        setPreviewTarget("artwork");
      }
      await refreshLibrary();
      setMessage(home
        ? "Saved artwork assigned to Dashboard Home."
        : "Saved artwork activated for this game.");
    } catch (error) {
      setMessage(`Could not activate saved artwork: ${String(error)}`);
    } finally {
      setLibraryBusy(false);
      restoreArtworkFocus("saved-artwork");
    }
  };

  const confirmLibraryDelete = () => {
    if (!selectedLibraryEntry) return;
    const item = selectedLibraryEntry;
    const wasDashboardHome = status.faceplate_dashboard_home_appid === item.appid;
    let modal: ReturnType<typeof showModal> | undefined;
    modal = showModal(<ConfirmModal strTitle="Delete saved Faceplate artwork?"
      strDescription={`This removes the prepared ${item.mode} copy for ${item.name || `App ${item.appid}`}. The SteamGridDB source can be searched and prepared again later.`}
      strOKButtonText="Delete" strCancelButtonText="Cancel" bDestructiveWarning
      onCancel={() => modal?.Close()}
      onOK={() => {
        modal?.Close();
        const previousLibrary = library;
        const previousSelection = librarySelection;
        // Invalidate any library response already in flight before applying
        // the optimistic removal below.
        libraryRequest.current += 1;
        const optimistic = library.filter(
          (entry) => !(entry.appid === item.appid && entry.mode === item.mode),
        );
        const nextSelection = optimistic.length
          ? `${optimistic[0].appid}:${optimistic[0].mode}` : "";
        // Remove the card before filesystem/game-name refresh work completes.
        // If the RPC fails, the exact prior list and selection are restored.
        setLibrary(optimistic);
        setLibrarySelection(nextSelection);
        setLibraryBusy(true);
        setMessage("Deleting saved artwork…");
        void (async () => {
          try {
            const value = await deleteFaceplateArtwork(item.appid, item.mode);
            libraryRequest.current += 1;
            const names = new Map(previousLibrary.map(
              (entry) => [`${entry.appid}:${entry.mode}`, entry.name],
            ));
            const entries = value.entries.map((entry) => ({
              ...entry,
              name: entry.name || names.get(`${entry.appid}:${entry.mode}`) || "",
            }));
            setLibrary(entries);
            setLibrarySelection((current) => current && entries.some(
              (entry) => `${entry.appid}:${entry.mode}` === current,
            ) ? current : entries.length
              ? `${entries[0].appid}:${entries[0].mode}` : "");
            const next = await getStatus();
            setStatus(next);
            if (selectedGame?.appid === item.appid) {
              await refreshArtworkState(item.appid);
            }
            if (wasDashboardHome && next.faceplate_dashboard_home_appid !== item.appid) {
              setDashboardPreview("");
            }
            setMessage("Saved artwork deleted.");
          } catch (error) {
            setLibrary(previousLibrary);
            setLibrarySelection(previousSelection);
            setMessage(`Could not delete saved artwork: ${String(error)}`);
          } finally {
            setLibraryBusy(false);
            restoreArtworkFocus(optimistic.length ? "saved-artwork" : "choose-game");
          }
        })();
      }} />);
  };

  return <Focusable ref={artworkPanelRef} preferredFocus
    navEntryPreferPosition={NavEntryPositionPreferences.PREFERRED_CHILD}
    style={{ width: "100%" }}>
    {library.length ? <PanelSection title="Saved artwork">
      <PanelSectionRow><Focusable data-artwork-focus="saved-artwork" style={{ width: "100%" }}>
        <DropdownItem label="Your Faceplate library"
          untranslatedOptions
          description="Prepared once and reused instantly. No conversion runs when a game starts."
          rgOptions={library.map((item) => ({
            data: `${item.appid}:${item.mode}`,
            label: `${item.name || `App ${item.appid}`} · ${item.mode}${item.active ? ` · ${translate("Active")}` : ""}${item.dashboard_ready ? "" : ` · ${translate("Dashboard update needed")}`}`,
          }))}
          selectedOption={librarySelection}
          onChange={(option) => {
            setLibrarySelection(String(option.data));
            restoreArtworkFocus("saved-artwork");
          }} />
      </Focusable></PanelSectionRow>
      {selectedLibraryEntry?.thumb ? <PanelSectionRow><div style={{
        width: "100%", overflow: "hidden", borderRadius: 14, background: "#070a11",
      }}>
        {artworkPreviewMedia(selectedLibraryEntry.thumb, Boolean(selectedLibraryEntry.animated)) === "video"
          ? <video key={librarySelection} src={selectedLibraryEntry.thumb} autoPlay muted loop playsInline
            preload="metadata" controls={false}
            style={{ display: "block", width: "100%", height: 220, objectFit: "contain" }} />
          : <img src={selectedLibraryEntry.thumb} loading="lazy" referrerPolicy="no-referrer"
            style={{ display: "block", width: "100%", height: 220, objectFit: "contain" }} />}
      </div></PanelSectionRow> : null}
      <PanelSectionRow><ButtonItem label="Use for this game"
        description="Activates the prepared copy for automatic in-game display."
        disabled={libraryBusy || jobRunning}
        onClick={() => void useLibraryEntry(false)}>{libraryBusy ? "Working…" : "Use"}</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ButtonItem label="Use for Dashboard Home"
        description={selectedLibraryEntry?.dashboard_ready
          ? "Keeps the artwork and adds the exact Realistic Dashboard overlay."
          : "Prepare this saved artwork once again to create its Dashboard background."}
        disabled={libraryBusy || jobRunning
          || !selectedLibraryEntry?.dashboard_ready}
        onClick={() => void useLibraryEntry(true)}>Assign</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ButtonItem label="Delete from library"
        disabled={libraryBusy || jobRunning || status.game.appid > 0}
        onClick={confirmLibraryDelete}>Delete</ButtonItem></PanelSectionRow>
    </PanelSection> : null}
    <PanelSection title="Game">
      {selectedGame && !choosingGame ? <>
        <PanelSectionRow><div style={{
          width: "100%", padding: "12px 14px", borderRadius: 12,
          background: "linear-gradient(135deg,rgba(40,215,255,.15),rgba(173,92,255,.12))",
        }}>
          <div translate="no" style={{ fontSize: "1.05em", fontWeight: 700 }}>{selectedGame.name}</div>
          <div style={{ marginTop: 4, fontSize: ".76em", opacity: .68 }}>
            {artworkState?.selected?.asset_id
              ? `${artworkState.selected.animated ? "Animated" : "Static"} artwork active`
              : "No custom faceplate artwork yet"}
          </div>
        </div></PanelSectionRow>
        <PanelSectionRow><Focusable data-artwork-focus="change-game" style={{ width: "100%" }}>
          <ButtonItem label="Choose another game" disabled={jobRunning}
            onClick={() => {
              setChoosingGame(true); setGameQuery("");
              restoreArtworkFocus("game-search");
            }}>Change</ButtonItem>
        </Focusable></PanelSectionRow>
      </> : <>
        {!games.length ? <PanelSectionRow><Focusable data-artwork-focus="choose-game" style={{ width: "100%" }}>
          <ButtonItem label="Choose a game"
            description="Shows only games installed on this Steam Machine."
            disabled={busy || jobRunning} onClick={() => void loadGames()}>
            {busy ? "Loading…" : "Continue"}
          </ButtonItem>
        </Focusable></PanelSectionRow> : <>
          <PanelSectionRow><Focusable data-artwork-focus="game-search" style={{ width: "100%" }}>
            <TextField label="Search your games" description={STUDIO_UX ? "Browse installed games or filter by name." : "Type two letters or more."}
              value={gameQuery} onChange={(event) => setGameQuery(event.currentTarget.value)} />
          </Focusable>
          </PanelSectionRow>
          {matchingGames.map((game) => <PanelSectionRow key={game.appid}><Focusable
            data-artwork-focus={`game-${game.appid}`} style={{ width: "100%" }}>
            <ButtonItem label={game.name} untranslatedProps={["label"]} disabled={busy || jobRunning} onClick={() => chooseGame(game)}>
              Choose
            </ButtonItem>
          </Focusable></PanelSectionRow>)}
        </>}
      </>}
      {message && !selectedAsset ? <PanelSectionRow><div style={{ width: "100%", fontSize: ".78em", lineHeight: 1.45 }}>
        {message}
      </div></PanelSectionRow> : null}
    </PanelSection>

    {selectedGame && !choosingGame ? <PanelSection title="Artwork">
      <PanelSectionRow><Focusable data-artwork-focus="artwork-type" style={{ width: "100%" }}>
        <DropdownItem label="What would you like?"
          description="Animated includes wide and portrait artwork."
          disabled={busy || jobRunning}
          rgOptions={FACEPLATE_ARTWORK_SEARCH_OPTIONS} selectedOption={preference}
          onChange={(option) => {
            setPreference(option.data as typeof preference); setResults([]); setResultIndex(0); setSelectedAsset(null);
            restoreArtworkFocus("artwork-type");
          }} />
      </Focusable>
      </PanelSectionRow>
      <PanelSectionRow><Focusable data-artwork-focus="artwork-search" style={{ width: "100%" }}>
        <ButtonItem label={results.length ? "Show different artwork" : "Show artwork"}
          description={status.faceplate.steamgriddb.configured
            ? "Looks through SteamGridDB for this game."
            : "Add your SteamGridDB key in Pixel Studio Settings first."}
          disabled={busy || jobRunning || !status.faceplate.steamgriddb.configured}
          onClick={() => void search()}>{busy ? "Loading…" : results.length ? "Refresh" : "Continue"}</ButtonItem>
      </Focusable>
      </PanelSectionRow>
      {candidate ? <>
        <PanelSectionRow><div style={{
          width: "100%", overflow: "hidden", borderRadius: 14,
          background: "#070a11", boxShadow: "0 8px 24px rgba(0,0,0,.32)",
        }}>
          {!showAdjustments && (!draftPreviewKey || cropEditing) ? sourcePreview : null}
          <div style={{ padding: "10px 12px 12px" }}>
            <div style={{ fontSize: ".84em", fontWeight: 700 }}>
              {candidate.animated ? "Animated artwork" : candidate.kind === "hero" ? "Wide artwork" : "Square artwork"}
            </div>
            <div style={{ marginTop: 3, fontSize: ".72em", opacity: .65 }}>
              {candidate.width}×{candidate.height}{candidate.author ? ` · ${candidate.author}` : ""}
            </div>
          </div>
        </div></PanelSectionRow>
        <PanelSectionRow><Focusable data-artwork-focus="gallery-navigation"
          navEntryPreferPosition={NavEntryPositionPreferences.FIRST}
          style={{ display: "flex", width: "100%", gap: 10, alignItems: "center" }}>
          <DialogButton style={{ minWidth: 64, flex: "0 0 64px" }} disabled={resultIndex <= 0 || busy || jobRunning}
            onClick={() => showResult(resultIndex - 1)}>‹</DialogButton>
          <div style={{ flex: 1, textAlign: "center", fontSize: ".8em", fontWeight: 650 }}>
            {artworkResultLabel(resultIndex, results.length)}
          </div>
          <DialogButton style={{ minWidth: 64, flex: "0 0 64px" }}
            disabled={resultIndex >= results.length - 1 || busy || jobRunning}
            onClick={() => showResult(resultIndex + 1)}>›</DialogButton>
        </Focusable></PanelSectionRow>
        {previewKind === "video" && !draftPreviewKey ? <PanelSectionRow><Focusable
          data-artwork-focus="preview-playback" style={{ width: "100%" }}>
          <ButtonItem label={previewPlaying ? "Pause animation" : "Play animation"}
            description="Muted preview. This does not affect the final faceplate GIF."
            onClick={() => void togglePreview()}>{previewPlaying ? "Pause" : "Play"}</ButtonItem>
        </Focusable>
        </PanelSectionRow> : null}
        {previewError ? <PanelSectionRow><div style={{ width: "100%", fontSize: ".76em", color: "#ffcf70" }}>
          {previewError}
        </div></PanelSectionRow> : null}
      </> : null}
    </PanelSection> : null}

    {selectedAsset && selectedGame && !choosingGame ? <PanelSection title="Use on Faceplate">
      <PanelSectionRow><Focusable data-artwork-focus="adjust-image" style={{ width: "100%" }}>
        <ToggleField label="Adjust image"
          description="Optional crop, colour and brightness controls."
          disabled={busy || jobRunning}
          checked={showAdjustments} onChange={(value) => {
            setShowAdjustments(value);
            setCropEditing(value);
            restoreArtworkFocus("adjust-image");
          }} />
      </Focusable>
      </PanelSectionRow>
      {showAdjustments ? <>
        {!draftPreviewKey || cropEditing ? <PanelSectionRow><div style={{ width: "100%" }}>{sourcePreview}
          <Localized><div style={{ marginTop: 6, fontSize: ".78em" }}>
            {preparationMode === "pan" ? "Red edges show one position. The animation scans the full width."
              : "The image between the red lines will fill the 64 × 54 matrix."}
          </div></Localized>
        </div></PanelSectionRow> : null}
        <PanelSectionRow><Focusable data-artwork-focus="artwork-style" style={{ width: "100%" }}>
          <DropdownItem label="Artwork layout"
            description="Optional. The default keeps the image clean and unobstructed."
            rgOptions={FACEPLATE_ARTWORK_STYLE_OPTIONS}
            selectedOption={effectiveArtStyle}
            onChange={(option) => void setArtworkPresentation(
              "style", option.data as Status["faceplate_artwork_style"],
            ).catch(actionFailed)} />
        </Focusable></PanelSectionRow>
        {effectiveArtStyle !== "art" ? <PanelSectionRow><Focusable
          data-artwork-focus="logo-position" style={{ width: "100%" }}>
          <DropdownItem label="Logo position"
            rgOptions={FACEPLATE_LOGO_POSITION_OPTIONS}
            selectedOption={effectiveLogoPosition}
            onChange={(option) => void setArtworkPresentation(
              "position", option.data as Status["faceplate_logo_position"],
            ).catch(actionFailed)} />
        </Focusable></PanelSectionRow> : null}
        {effectiveArtStyle !== "art" ? <ArtworkLogoScale value={logoScale} disabled={busy || jobRunning}
          onChange={(value) => {
            logoScaleEdited.current = true; setLogoScale(value); setDraftPreviewKey("");
          }} /> : null}
        <PanelSectionRow><SliderField label="Horizontal crop" value={cropX} min={0} max={100} step={5}
          disabled={busy || jobRunning || preparationMode === "pan"}
          showValue valueSuffix="%" onChange={(value) => { setCropX(value); setDraftPreviewKey(""); }} /></PanelSectionRow>
        <PanelSectionRow><SliderField label="Vertical crop" value={cropY} min={0} max={100} step={5}
          disabled={busy || jobRunning}
          showValue valueSuffix="%" onChange={(value) => { setCropY(value); setDraftPreviewKey(""); }} /></PanelSectionRow>
        <PanelSectionRow><SliderField label="Saturation" value={saturation} min={50} max={180} step={5}
          disabled={busy || jobRunning}
          showValue valueSuffix="%" onChange={(value) => { setSaturation(value); setDraftPreviewKey(""); }} /></PanelSectionRow>
        <PanelSectionRow><SliderField label="Brightness" value={brightness} min={50} max={150} step={5}
          disabled={busy || jobRunning}
          showValue valueSuffix="%" onChange={(value) => { setBrightness(value); setDraftPreviewKey(""); }} /></PanelSectionRow>
        {preparationMode === "animated" ? <PanelSectionRow><Focusable
          data-artwork-focus="loop-cleanup" style={{ width: "100%" }}>
          <DropdownItem label="Loop ending cleanup"
            disabled={busy || jobRunning}
            description={loopCleanup === "no"
              ? "No cut · keeps the full animation and repairs damaged frames."
              : loopCleanup === "soft"
              ? "Soft · removes obvious defects at the end."
              : loopCleanup === "medium"
                ? "Cuts 0.1–0.5 s at the best visual join with the beginning."
                : "Cuts 0.4–1.0 s at the best visual join. May remove authored motion."}
            rgOptions={FACEPLATE_LOOP_CLEANUP_OPTIONS} selectedOption={loopCleanup}
            onChange={(option) => {
              setLoopCleanup(option.data as typeof loopCleanup);
              setDraftPreviewKey("");
              restoreArtworkFocus("loop-cleanup");
            }} />
        </Focusable></PanelSectionRow> : null}
        <PanelSectionRow><DropdownItem label="Artwork Dashboard style"
          disabled={busy || jobRunning}
          description={dashboardTreatment === "none"
            ? "Original colours. No full-image filter; only the small readability masks behind live information remain."
            : "Optional visual treatment. Prepared once; no conversion happens when the game starts."}
          rgOptions={[
            { data: "none", label: "No filter · original colours" },
            { data: "cinema", label: "Dark cinema" },
            { data: "hero-cut", label: "Hero cut" },
            { data: "palette-echo", label: "Palette echo" },
          ]}
          selectedOption={dashboardTreatment}
          onChange={(option) => { setDashboardTreatment(option.data as typeof dashboardTreatment); setDraftPreviewKey(""); }}
        /></PanelSectionRow>
        <PanelSectionRow><DropdownItem label="Dashboard compression"
          disabled={busy || jobRunning}
          description={dashboardCompression === "compatible"
            ? "Strong compression. Uses fewer colours for broad Faceplate compatibility."
            : dashboardCompression === "balanced"
              ? "Medium compression. Stable ordered dithering restores gradients without changing the hardware palette."
              : "Light compression. Full spatial error diffusion preserves the most colour nuance."}
          rgOptions={[
            { data: "compatible", label: "Strong · Compatible" },
            { data: "balanced", label: "Medium · Balanced detail" },
            { data: "fine", label: "Light · Fine detail" },
          ]}
          selectedOption={dashboardCompression}
          onChange={(option) => { setDashboardCompression(
            option.data as typeof dashboardCompression,
          ); setDraftPreviewKey(""); }}
        /></PanelSectionRow>
      </> : null}
      {STUDIO_UX ? <PanelSectionRow><DropdownItem label="Apply to"
        description="Preparing and previewing do not change either display."
        disabled={busy || jobRunning}
        rgOptions={[
          { data: "game", label: "Game · artwork only" },
          { data: "game-dashboard", label: "Game · illustrated Dashboard" },
          { data: "home", label: "Home · illustrated Dashboard" },
          { data: "both", label: "Home + game · illustrated Dashboard" },
        ]}
        selectedOption={destination}
        onChange={(option) => { setDestination(option.data as typeof destination); setPreviewTarget(option.data === "game" ? "artwork" : "dashboard"); }} /></PanelSectionRow>
        : <PanelSectionRow><DropdownItem label="Dashboard Home after preparation"
        description={useForDashboardHome
          ? "Artwork Dashboard will use this game artwork behind the live information overlay."
          : "Weather Dashboard remains active; this artwork is prepared for in-game use only."}
        rgOptions={FACEPLATE_DASHBOARD_SOURCE_OPTIONS}
        selectedOption={useForDashboardHome ? "artwork" : "weather"}
        onChange={(option) => setUseForDashboardHome(option.data === "artwork")} /></PanelSectionRow>}
      {preparationMode !== "static" || showAdjustments ? <PanelSectionRow><Focusable data-artwork-focus="use-artwork" style={{ width: "100%" }}>
        <ButtonItem label={preparationMode === "static" ? "Prepare preview" : "Prepare animation preview"}
          description={status.game.appid > 0 && artworkNeedsIdleGame(preparationMode)
            ? "Quit the running game first."
            : "Creates a local 64 × 54 preview without sending it. Apply when ready."}
          disabled={status.game.appid > 0 && artworkNeedsIdleGame(preparationMode)}
          onClick={() => void prepare()}>{jobRunning ? "Preparing…" : STUDIO_UX ? "Prepare" : "Use"}</ButtonItem>
      </Focusable>
      </PanelSectionRow> : null}
      {preparationMode === "static" ? <PanelSectionRow><Focusable data-artwork-focus={showAdjustments ? "use-static" : "use-artwork"} style={{ width: "100%" }}><ButtonItem label="Use this image"
        description="Prepares one static frame and applies your chosen display. Also works during a game."
        onClick={() => {
          if (busy || jobRunning || appliedDraftKey === `${draftPreviewKey}:${destination}`) return;
          prepareFocus.current = showAdjustments ? "use-static" : "use-artwork";
          if (draftPreviewKey && job?.state === "ready" && job.mode && draftPreviewKey === job.prepared?.sha256) {
            void activatePrepared(selectedGame.appid, job.mode, job.prepared);
          } else void prepare(true);
        }}>Use</ButtonItem></Focusable></PanelSectionRow>
        : <SettingsHelpText><PanelSectionRow><Localized><div style={{ fontSize: ".78em", lineHeight: 1.5 }}>
          Prepare animations with no game running. Then review the preview and Apply. Your current image stays visible until transfer finishes.
        </div></Localized></PanelSectionRow></SettingsHelpText>}
      {STUDIO_UX && job?.state === "ready" && job.appid === selectedGame?.appid ? <>
        {draftPreviewKey && resultPreview && !cropEditing ? <PanelSectionRow><img src={resultPreview}
          alt="Prepared Faceplate draft, not yet applied"
          style={{ display: "block", width: 256, maxWidth: "100%", imageRendering: "pixelated", aspectRatio: "64/54" }} /></PanelSectionRow> : null}
        {preparationMode !== "static" ? <PanelSectionRow><Focusable data-artwork-focus="result-preview" style={{ width: "100%" }}><ButtonItem label={destination === "game" || destination === "game-dashboard" ? "Apply to this game" : destination === "home" ? "Apply to Dashboard Home" : "Apply to both"}
          disabled={!draftPreviewKey || draftPreviewKey !== job.prepared?.sha256}
          description="Selects the requested display and sends it when its destination is active."
          onClick={() => !busy && !jobRunning && appliedDraftKey !== `${draftPreviewKey}:${destination}` && job.mode && selectedGame && void activatePrepared(selectedGame.appid, job.mode, job.prepared)}>{appliedDraftKey === `${draftPreviewKey}:${destination}` ? "Applied" : "Apply"}</ButtonItem></Focusable></PanelSectionRow> : null}
      </> : null}
      {job && ["queued", "running", "cancelling", "failed", "cancelled"].includes(job.state) ? <PanelSectionRow><div style={{ width: "100%", fontSize: ".8em", lineHeight: 1.5 }}>
        <div style={{ height: 10, borderRadius: 5, overflow: "hidden", background: "rgba(255,255,255,.12)" }}>
          <div style={{ width: `${Math.max(0, Math.min(100, job.percent || 0))}%`, height: "100%", background: "linear-gradient(90deg,#28d7ff,#ad5cff)" }} />
        </div>
        <div style={{ marginTop: 7 }}><b>{job.percent || 0}%</b> · {job.detail || job.stage}</div>
      </div></PanelSectionRow> : null}
      {jobRunning ? <PanelSectionRow><Focusable data-artwork-focus="cancel-preparation" style={{ width: "100%" }}>
        <ButtonItem label="Cancel preparation" onClick={() => {
          activateWhenReady.current = null;
          void cancelFaceplateArtwork().then((next) => setArtworkState((previous) => ({
            job: next, selected: previous?.selected ?? {}, prepared: previous?.prepared ?? {},
          }))).finally(() => restoreArtworkFocus("use-artwork"));
        }}>Cancel</ButtonItem>
      </Focusable></PanelSectionRow> : null}
      {message && (!deliveryWatch || deliveryReadError) ? <PanelSectionRow><div style={{ width: "100%", fontSize: ".78em", lineHeight: 1.45 }}>
        {message}
      </div></PanelSectionRow> : null}
      {deliveryWatch > 0 ? <PanelSectionRow><Localized><div style={{ width: "100%", fontSize: ".8em", lineHeight: 1.45 }}>
        {deliveryReadError || (deliveryStatus?.apply_deferred_reason
          ? "Saved. Display is paused; it will resume when available."
          : deliveryStatus ? faceplateUXState({ faceplate: deliveryStatus, faceplate_lab_enabled: status.faceplate_lab_enabled }).label
            : "Sending to the Faceplate…")}
      </div></Localized></PanelSectionRow> : null}
    </PanelSection> : null}

    {!STUDIO_UX && selectedGame && !choosingGame && artworkState?.selected?.asset_id
      ? <PanelSection title="Faceplate result preview">
        <PanelSectionRow><Focusable data-artwork-focus="preview-target" style={{ width: "100%" }}>
          <DropdownItem label="Preview"
            description={previewTarget === "artwork"
              ? "The exact GIF used automatically when this game starts."
              : previewTarget === "dashboard"
                ? "The same full-quality artwork with the Dashboard overlay."
                : "The current Realistic weather atmosphere with the Dashboard overlay."}
            rgOptions={FACEPLATE_RESULT_PREVIEW_OPTIONS} selectedOption={previewTarget}
            onChange={(option) => {
              setPreviewTarget(option.data as typeof previewTarget);
              restoreArtworkFocus("preview-target");
            }} />
        </Focusable></PanelSectionRow>
        {resultPreview
          ? <PanelSectionRow><div style={{
            width: "100%", background: "#05070b", borderRadius: 14,
            textAlign: "center", padding: 14,
          }}>
            <img src={resultPreview}
              alt={previewTarget === "artwork"
                ? "Artwork in-game Faceplate preview"
                : previewTarget === "dashboard"
                  ? "Artwork Dashboard Faceplate preview"
                  : "Weather Dashboard Faceplate preview"}
              style={{ display: "block", width: 256, maxWidth: "100%",
                margin: "0 auto", aspectRatio: "64/54", objectFit: "contain",
                imageRendering: "pixelated" }} />
            <div style={{ marginTop: 7, fontSize: ".74em", opacity: .7 }}>
              {previewTarget === "artwork" ? "Artwork in-game"
                : previewTarget === "dashboard" ? "Artwork Dashboard" : "Weather Dashboard"}
              {" · local preview only · nothing sent to the Faceplate"}
            </div>
          </div></PanelSectionRow> : null}
        <PanelSectionRow><Focusable data-artwork-focus="result-preview" style={{ width: "100%" }}>
          <ButtonItem label={previewTarget === "artwork"
            ? "Preview Artwork in-game"
            : previewTarget === "dashboard" ? "Preview Artwork Dashboard"
              : "Preview Weather Dashboard"}
            description={previewTarget === "dashboard"
              ? "Uses the prepared background or local Steam artwork, without a serial transfer."
              : "Renders the selected result locally without a serial transfer."}
            disabled={dashboardPreviewBusy || nativePreviewBusy || jobRunning}
            onClick={() => {
              if (previewTarget === "artwork") {
                setNativePreviewBusy(true);
                void getFaceplateArtworkPreview(selectedGame.appid)
                  .then((value) => {
                    setNativePreview(value.data_uri);
                    setMessage(value.error ? value.error : "");
                  })
                  .catch((error) => setMessage(`Preview failed: ${String(error)}`))
                  .finally(() => {
                    setNativePreviewBusy(false);
                    restoreArtworkFocus("result-preview");
                  });
              } else if (previewTarget === "dashboard") {
                setDashboardPreviewBusy(true);
                void getFaceplateArtworkDashboardPreview(selectedGame.appid, "", false, useForDashboardHome)
                  .then((value) => { setDashboardPreview(value.data_uri); setMessage(""); })
                  .catch((error) => setMessage(`Preview failed: ${String(error)}`))
                  .finally(() => {
                    setDashboardPreviewBusy(false);
                    restoreArtworkFocus("result-preview");
                  });
              } else {
                setDashboardPreviewBusy(true);
                void getFaceplateDashboardPreview(
                  weatherDashboardCondition, weatherDashboardVariant,
                  "weather-artwork-v2",
                )
                  .then((value) => {
                    setWeatherDashboardPreview(value.data_uri);
                    setMessage(value.error ? `Preview failed: ${value.error}` : "");
                  })
                  .catch((error) => setMessage(`Preview failed: ${String(error)}`))
                  .finally(() => {
                    setDashboardPreviewBusy(false);
                    restoreArtworkFocus("result-preview");
                  });
              }
            }}>{dashboardPreviewBusy || nativePreviewBusy ? "Rendering…" : "Preview"}</ButtonItem>
        </Focusable></PanelSectionRow>
      </PanelSection> : null}
  </Focusable>;
}

function QuickSettingsAction(){
  const completed=useSyncExternalStore(subscribeQuickSetup,quickSetupCompleted,quickSetupCompleted);
  return <DialogButton className="gca-quick-gear" aria-label="Settings" disabled={!completed}
    style={{ width: 30, height: 30, minWidth: 0, minHeight: 30, padding: 0,
      flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
    onClick={() => { if(!quickSetupCompleted())return;Navigation.CloseSideMenus(); Navigation.Navigate("/gabecubeaura/settings"); }}>
    <TbSettings size={19} aria-hidden="true" />
  </DialogButton>;
}

function QuickAccessContent(){
  const active=useQuickAccessVisible();
  return <Content active={active}/>;
}

function actionFailed(error: unknown) {
  publicActionError = String(error).replace(/^Error:\s*/, '');
  window.dispatchEvent(new Event('gca-action-error'));
}
let publicActionError = '';

function Content({ active=true, page: sourcePage = "quick", settingsView, initialSource, onFaceplateConnectionChange }: {
  active?: boolean; page?: Page; settingsView?: SettingsSelection;
  initialSource?: SettingsSourcePage;
  onFaceplateConnectionChange?: (connected:boolean)=>void;
}) {
  const [effect,setEffect]=useState(()=>initialSettingsEffect(initialSource,retainedStatus?.game.appid??0));
  const effectChosen=useRef(false);
  const [sync,setSync]=useState(initialSource==='audio-sync'?'audio-sync':'screen-sync');
  const [eventSource,setEventSource]=useState(initialSource==='launches'?'launches':'notification');
  const sources:Page[]=settingsView?settingsSources(settingsView,effect,sync,eventSource):[sourcePage];
  const page=sources[0];
  const [status, setStatusState] = useState<Status | null>(() => retainedStatus);
  useEffect(()=>{
    if(!effectChosen.current)setEffect(initialSettingsEffect(initialSource,status?.game.appid??0));
  },[initialSource,status?.game.appid]);
  const [hero, setHero] = useState<ArtworkPayload | null>(null);
  const [heroRequestKey, setHeroRequestKey] = useState("");
  const [launchHero, setLaunchHero] = useState<ArtworkPayload | null>(null);
  const [launchHeroRequestKey, setLaunchHeroRequestKey] = useState("");
  const artworkRequests = useRef({ artwork: 0, launch: 0 });
  const [showDebug, setShowDebug] = useState(false);
  const [actionError,setActionError]=useState('');
  useEffect(()=>{const update=()=>setActionError(publicActionError);window.addEventListener('gca-action-error',update);
    return()=>window.removeEventListener('gca-action-error',update);},[]);

  const [languageBusy, setLanguageBusy] = useState(false);
  const [languageError, setLanguageError] = useState("");
  const [configurationActionMessage, setConfigurationActionMessage] = useState("");
  const [configurationBusy, setConfigurationBusy] = useState(false);
  const [launchPreviewError, setLaunchPreviewError] = useState("");
  const [routingMessage, setRoutingMessage] = useState("");
  const [faceplateRoutingMessage, setFaceplateRoutingMessage] = useState("");
  const [update, setUpdate] = useState<UpdateStatus | null>(null);
  const [updateBusy, setUpdateBusy] = useState(false);
  const [updateInstallError, setUpdateInstallError] = useState("");
  const [, setDiagnostics] = useState<DiagnosticStatus | null>(null);
  const [diagnosticBusy, setDiagnosticBusy] = useState(false);
  const [steamGridDbKey, setSteamGridDbKey] = useState("");
  const [faceplateActionBusy, setFaceplateActionBusy] = useState(false);
  const manualTimer = useRef<number | null>(null);
  const artworkVibranceTimer = useRef<number | null>(null);
  const statusReads = useRef(statusRefreshGate());
  useEffect(()=>subscribeQuickSetup(()=>{
    if(!retainedStatus)return;
    // Setup/reset can finish on a full-screen route while this panel is hidden.
    statusReads.current.invalidate();
    setStatusState(retainedStatus);
  }),[]);
  const setStatus = (next: Status) => {
    statusReads.current.invalidate();
    retainedStatus = next;
    publishQuickSetupStatus(next);
    setUILanguage(next.ui_language);
    setStatusState(next);
    // Reuse the existing status stream: no secondary hardware polling.
    onFaceplateConnectionChange?.(next.faceplate.available===true);
  };

  useEffect(() => {
    if(!active)return;
    let alive = true;
    let timer: number | null = null;
    let delay = statusRefreshDelay(page);
    const refresh = async () => {
      const ticket = statusReads.current.ticket();
      try {
        const next = await getStatus();
        delay = statusRefreshDelay(page);
        if (alive && statusReads.current.accepts(ticket)) setStatus(next);
      } catch (error) {
        if (alive) console.warn("[GabeCubeAura] status refresh failed", error);
      } finally {
        if (alive) timer = window.setTimeout(() => void refresh(), delay);
      }
    };
    void refresh();
    return () => {
      alive = false;
      if (timer != null) window.clearTimeout(timer);
      if (manualTimer.current != null) window.clearTimeout(manualTimer.current);
      if (artworkVibranceTimer.current != null) window.clearTimeout(artworkVibranceTimer.current);
    };
  }, [page,active]);

  useEffect(() => {
    if(!active)return;
    if (page !== "quick" && page !== "updates" && page !== "advanced") return;
    let alive = true;
    const refresh = () => void getUpdateStatus()
      .then((next) => alive && setUpdate(next))
      .catch((error) => console.warn("[GabeCubeAura] update status failed", error));
    refresh();
    const timer = window.setInterval(refresh, page === "updates" ? 1000 : 30_000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [page,active]);

  useEffect(() => {
    if (page !== "advanced") return;
    let alive = true;
    void getDiagnosticStatus()
      .then((next) => { if (alive) setDiagnostics(next); })
      .catch((error) => console.warn("[GabeCubeAura] diagnostic status failed", error));
    return () => { alive = false; };
  }, [page]);


  useEffect(() => {
    setLaunchPreviewError("");
  }, [status?.game.appid]);

  const loadAndSampleArtwork = useCallback(async (
    appid: number,
    source: ArtworkSource,
    purpose: "artwork" | "launch" = "artwork",
  ) => {
    const request = ++artworkRequests.current[purpose];
    const setArtwork = purpose === "launch" ? setLaunchHero : setHero;
    const setRequestKey = purpose === "launch" ? setLaunchHeroRequestKey : setHeroRequestKey;
    if (appid <= 0) {
      setArtwork(null);
      setRequestKey("");
      return;
    }
    const current = await getStatus();
    if (request !== artworkRequests.current[purpose]) return;
    const artwork = await getArtwork(appid, source, purpose, true);
    if (request !== artworkRequests.current[purpose]) return;
    setArtwork(artwork);
    setRequestKey(`${appid}:${source}`);
    if (!artwork.found || !artwork.data_uri || !artwork.fingerprint || artwork.cached) {
      const refreshed = await getStatus();
      if (request === artworkRequests.current[purpose]) setStatus(refreshed);
      return;
    }
    const mode = current.artwork_mode;
    const manualY = current.artwork_manual_y;
    const result = await sampleArtwork(artwork.data_uri, mode, manualY);
    if (request !== artworkRequests.current[purpose]) return;
    const next = await submitArtwork(
      appid,
      artwork.fingerprint,
      result.colors,
      result.y,
      result.dominantPalettes,
      artwork.filename ?? "",
      artwork.source ?? source,
      purpose,
    );
    if (request === artworkRequests.current[purpose]) setStatus(next);
  }, []);

  const refreshArtworkAfterConfiguration = (next: Status) => {
    setHeroRequestKey("");
    setLaunchHeroRequestKey("");
    if (next.game.appid > 0) {
      void loadAndSampleArtwork(next.game.appid, next.artwork_source, "artwork")
        .then(() => loadAndSampleArtwork(
          next.game.appid, next.launch_artwork_source, "launch",
        ))
        .catch(actionFailed);
    }
  };

  const importSelectedConfiguration = async (path: string) => {
    setConfigurationBusy(true);
    setConfigurationActionMessage("");
    try {
      const next = await importConfiguration(path);
      setStatus(next);
      refreshArtworkAfterConfiguration(next);
      setConfigurationActionMessage(`Imported ${path}. Saved settings and game profiles replaced.`);
    } catch (error) {
      setConfigurationActionMessage(`Import failed; saved settings were kept. ${String(error)}`);
    } finally {
      setConfigurationBusy(false);
    }
  };

  const chooseConfigurationFile = async () => {
    try {
      const selected = await openFilePicker(0, "/home/deck/Documents", true, false,
        undefined, ["json"]);
      const path = selected?.realpath || selected?.path;
      if (!path) return;
      let modal: ReturnType<typeof showModal> | undefined;
      modal = showModal(<ConfirmModal strTitle="Import GabeCubeAura configuration?"
        strDescription="This replaces every saved setting and per-game profile. The personal timer stops."
        strOKButtonText="Import" strCancelButtonText="Cancel"
        onCancel={() => modal?.Close()}
        onOK={() => { modal?.Close(); void importSelectedConfiguration(path); }} />);
    } catch (error) {
      if (!String(error).toLowerCase().includes("cancel")) {
        setConfigurationActionMessage(`Could not open configuration picker: ${String(error)}`);
      }
    }
  };

  const confirmReset = (allData: boolean) => {
    let modal: ReturnType<typeof showModal> | undefined;
    modal = showModal(<ConfirmModal
      strTitle={allData ? "Erase all GabeCubeAura data?" : "Reset settings only?"}
      strDescription={allData
        ? "Deletes settings, per-game profiles, saved artwork, saved ambiences and the SteamGridDB key. The personal timer stops. This cannot be undone."
        : "Returns settings and per-game preferences to defaults and stops the personal timer. Your SteamGridDB key, saved artwork and saved ambiences are kept."}
      strOKButtonText={allData ? "Erase all GCA data" : "Reset settings only"}
      strCancelButtonText="Cancel" bDestructiveWarning={allData}
      onCancel={() => modal?.Close()}
      onOK={() => {
        modal?.Close();
        setConfigurationBusy(true);
        setConfigurationActionMessage("");
        const action = allData
          ? factoryResetConfiguration('delete-gca-settings-content-and-access')
          : resetSettingsOnly();
        void action.then((next) => {
          setStatus(next);
          refreshArtworkAfterConfiguration(next);
          void getUpdateStatus().then(setUpdate).catch(actionFailed);
          setConfigurationActionMessage(allData
            ? "GCA settings, saved content and local access have been erased."
            : "Settings reset. Your keys and saved content were kept.");
        }).catch((error) => {
          setConfigurationActionMessage(`Reset failed: ${String(error)}`);
        }).finally(() => setConfigurationBusy(false));
      }} />);
  };
  const confirmConfigurationReset = () => confirmReset(true);
  const confirmSettingsOnlyReset = () => confirmReset(false);

  useEffect(() => {
    if (!status) return;
    const contextualAudioPalette = ADAPTIVE_AUDIO_STYLES.includes(status.audio_sync_style)
      && ["screen-sync", "artwork"].includes(status.audio_sync_palette);
    // The quick panel has its own read-only thumbnail path. Never sample,
    // decode a source image or prepare palettes just because it is opened.
    const needsArtwork = page !== 'quick' && (page === "artwork" || page === "launches"
      || contextualAudioPalette && (page === "audio-sync" || status.current_display === "audio_sync"));
    if (!needsArtwork) {
      setHero(null);
      setHeroRequestKey("");
      setLaunchHero(null);
      setLaunchHeroRequestKey("");
      return;
    }
    const purposes: ("artwork" | "launch")[] = [page === "launches" ? "launch" : "artwork"];
    for (const purpose of purposes) {
      const source = purpose === "launch" ? status.launch_artwork_source : status.artwork_source;
      void loadAndSampleArtwork(status.game.appid, source, purpose).catch((error) => {
        console.warn("[GabeCubeAura] artwork preview failed", error);
      });
    }
  }, [page, status?.game.appid, status?.current_display, status?.artwork_source,
    status?.launch_artwork_source, status?.audio_sync_style,
    status?.audio_sync_palette, loadAndSampleArtwork]);

  if (!status) {
    return <PanelSection><PanelSectionRow>Loading GabeCubeAura…</PanelSectionRow></PanelSection>;
  }
  // The UI no longer depends on the historical renderer setting.


  const changeArtworkSetting = async (key: string, value: unknown) => {
    const next = await setArtworkSetting(status.game.appid, key, value);
    setStatus(next);
    if (key !== "vibrance" && next.game.appid > 0) {
      await loadAndSampleArtwork(next.game.appid, next.artwork_source, "artwork");
    }
  };
  const applyDisplayPreset = async (preset: string) => {
    try {
      setStatus(await setSetting("display_preset", preset));
      setRoutingMessage("");
    } catch (error) {
      setRoutingMessage(String(error).replace(/^Error:\s*/, ""));
    }
  };
  const changeFaceplateRoute = async (
    home: "weather" | "dashboard" | "artwork" | "artwork-dashboard" | "native-clock",
    game: "dashboard" | "artwork" | "artwork-dashboard" | "weather" | "player-city",
  ) => {
    setFaceplateActionBusy(true); setFaceplateRoutingMessage("");
    try {
      setStatus(await setFaceplateRouting(home, game, status.faceplate.routing.preference_revision));
    } catch (error) {
      setFaceplateRoutingMessage(`Display choice could not be saved: ${String(error)}`);
    } finally {
      setFaceplateActionBusy(false);
    }
  };
  const changeManualPosition = (value: number) => {
    setStatus({ ...status, artwork_manual_y: value });
    if (manualTimer.current != null) window.clearTimeout(manualTimer.current);
    manualTimer.current = window.setTimeout(() => {
      manualTimer.current = null;
      void changeArtworkSetting("manual_y", value);
    }, 250);
  };
  const changeArtworkVibrance = (value: number) => {
    setStatus({ ...status, artwork_vibrance: value });
    if (artworkVibranceTimer.current != null) window.clearTimeout(artworkVibranceTimer.current);
    artworkVibranceTimer.current = window.setTimeout(() => {
      artworkVibranceTimer.current = null;
      void changeArtworkSetting("vibrance", value);
    }, 120);
  };
  const chooseTemperatureColor = (
    key: "temperature_custom_cool" | "temperature_custom_middle" | "temperature_custom_hot",
    label: string,
    color: [number, number, number],
  ) => {
    chooseSettingColor(key, label, color, setStatus);
  };
  const artColors = status.artwork.colors;
  const currentArtwork = status.game.appid > 0 && heroRequestKey === `${status.game.appid}:${status.artwork_source}`
    && hero?.appid === status.game.appid && hero.found && hero.data_uri ? hero : null;
  const currentLaunchArtwork = status.game.appid > 0 && launchHeroRequestKey === `${status.game.appid}:${status.launch_artwork_source}`
    && launchHero?.appid === status.game.appid && launchHero.found && launchHero.data_uri ? launchHero : null;
  const runLaunchPreview = async () => {
    setLaunchPreviewError("");
    try {
      const started = await previewLaunchArtwork();
      const next = await getStatus();
      setStatus(next);
      if (!started) {
        setLaunchPreviewError(!next.signalbar_enabled
          ? "Enable GabeCubeAura before starting a preview."
          : "Preview could not start. Wait for the current game's artwork palette, then try again.");
      }
    } catch (error) {
      setLaunchPreviewError(`Preview failed: ${String(error)}`);
    }
  };
  const performanceColors = performancePreview(status);
  const baseShownColors = status.provider.startsWith("faceplate-extension:") ? status.faceplate_extension?.colours ?? []
    : status.provider.startsWith("launch-artwork:") ? status.launch_artwork.colors
    : status.provider.startsWith("screen-sync") ? status.screen_sync.colors
    : status.provider.startsWith("audio-sync") ? status.audio_sync.colors
    : status.provider.startsWith("customization:") ? status.customization.colors
    : status.provider.startsWith("event:") ? status.events.colors
    : status.provider.startsWith("controller:") || status.provider.startsWith("controller-") ? status.controllers.colors
    : status.provider === "countdown" ? status.countdown.colors
      : status.provider.startsWith("weather") ? status.weather.colors
      : status.provider.startsWith("artwork") ? artColors
        : status.provider.startsWith("performance") ? performanceColors : [];
  const shownColors = status.provider.endsWith("+recording")
    ? addRecordingMarker(status, baseShownColors) : baseShownColors;
  const showPage = (target: Page) => sources.includes(target);

  const runUpdateAction = async (action: () => Promise<UpdateStatus>) => {
    setUpdateBusy(true);
    setUpdateInstallError("");
    try {
      setUpdate(await action());
    } catch (error) {
      console.warn("[GabeCubeAura] update action failed", error);
      setUpdate(await getUpdateStatus());
    } finally {
      setUpdateBusy(false);
    }
  };

  const confirmUpdateInstall = (prepared: UpdateStatus | null = update) => {
    if (!prepared?.confirmation_token || !prepared.available_version) return;
    const token = prepared.confirmation_token;
    const target = prepared.available_version;
    let modal: ReturnType<typeof showModal> | undefined;
    modal = showModal(<ConfirmModal strTitle={prepared.recovery_prepared ? "Restore the previous version?" : "Update GabeCubeAura?"}
      strDescription={prepared.recovery_prepared
        ? prepared.recovery_preserves_current_settings
          ? `Return to ${target}? The pinned archive has been verified. Current settings are kept and backed up before Decky restarts.`
          : `Restore ${target} and its saved settings, preferences and artwork selections? Your current state is backed up before Decky restarts. Changes made since the backup will no longer be selected.`
        : `Update from ${prepared.installed_version} to ${target}? The downloaded package passed its checksum and package checks. ${prepared.bundle_components.length > 1 ? "GabeCubeAura, the faceplate service and Pixel Studio will be updated together with one rollback point. " : ""}Your settings and artwork cache will be kept. Decky will restart briefly.`}
      strOKButtonText={prepared.recovery_prepared ? "Restore and restart Decky" : "Update and restart Decky"} strCancelButtonText="Cancel"
      onCancel={() => modal?.Close()}
      onOK={() => {
        modal?.Close();
        setUpdateBusy(true);
        setUpdateInstallError("");
        void installPreparedUpdate(token).catch((error) => {
          console.warn("[GabeCubeAura] update installation failed", error);
          setUpdateBusy(false);
          setUpdateInstallError("Installation did not start. Review the update error below or retry.");
          void getUpdateStatus().then(setUpdate).catch(actionFailed);
        });
      }} />);
  };

  return (
    <LedPreviewActivity.Provider value={active}>
      {actionError?<PanelSectionRow><Localized><div role="alert">{actionError}</div></Localized>
        <DialogButton onClick={()=>{publicActionError='';setActionError('');}}>{translate('Close',status.ui_language)}</DialogButton></PanelSectionRow>:null}
      {settingsView?.category==='display'&&settingsView.tab==='effects'?<><PanelSectionRow><DropdownItem label="Effect to configure"
        selectedOption={effect} rgOptions={[{data:'customization',label:'Customization+'},{data:'artwork',label:'Steam artwork colours'}]}
        onChange={option=>{effectChosen.current=true;setEffect(String(option.data));}}/></PanelSectionRow>
        <PanelSectionRow><Localized><small className="gca-effect-summary">{EFFECTS_HELP}</small></Localized></PanelSectionRow></>:null}
      {settingsView?.category==='display'&&settingsView.tab==='sync'?<PanelSectionRow><DropdownItem label="Synchronization to configure"
        selectedOption={sync} rgOptions={[{data:'screen-sync',label:'Screen Sync'},{data:'audio-sync',label:'Audio Sync'}]}
        onChange={option=>setSync(String(option.data))}/></PanelSectionRow>:null}
      {settingsView?.category==='signals'&&settingsView.tab==='events'?<PanelSectionRow><DropdownItem label="Event to configure"
        selectedOption={eventSource} rgOptions={[{data:'notification',label:'Steam notification'},{data:'achievement',label:'Achievement'},{data:'screenshot',label:'Screenshot'},{data:'recording',label:'Recording'},{data:'launches',label:'Game launches'}]}
        onChange={option=>setEventSource(String(option.data))}/></PanelSectionRow>:null}
      {page === "profiles" ? <AmbienceProfilesPanel /> : null}
      {page === "quick" ? <>
        {!status.onboarding_completed ? <PanelSection title="First-time setup"><PanelSectionRow><QuickAction
          onClick={() => { Navigation.CloseSideMenus(); Navigation.Navigate("/gabecubeaura/setup"); }}>Open guided setup</QuickAction></PanelSectionRow>
          <PanelSectionRow><Localized><small role="status">Finish the guided setup to unlock the controls below.</small></Localized></PanelSectionRow></PanelSection> : null}
        <FaceplateSetupNotice status={status} onOpen={() => {
          Navigation.CloseSideMenus(); Navigation.Navigate("/gabecubeaura/setup/faceplate");
        }}/>
        <UpdateAvailableButton update={update} disabled={!status.onboarding_completed} onOpen={() => {
          if(!quickSetupCompleted())return;Navigation.CloseSideMenus(); Navigation.Navigate('/gabecubeaura/settings/updates');
        }} />
        <CompactQuickPanel active={active} status={status} setStatus={setStatus} colors={shownColors??[]}
          onMutationChange={active => statusReads.current.writing(active)}
          onOpenGame={() => { Navigation.CloseSideMenus(); Navigation.Navigate(LIGHT_BAR_ARTWORK_ROUTE); }}
          onOpenArtwork={() => { Navigation.CloseSideMenus(); Navigation.Navigate("/gabecubeaura/settings/pixel-artwork"); }}
          onOpenSettings={() => { Navigation.CloseSideMenus(); Navigation.Navigate("/gabecubeaura/settings"); }} />
      </> : null}

      {page !== "quick" && status.thermal_protection.active ? <PanelSection title="Thermal protection">
        <PanelSectionRow>
          <div style={{ width: "100%", color: "#ffcc66", fontSize: ".88em", lineHeight: 1.45 }}>
            <b>Temporarily disabled: thermal protection</b>
            <div style={{ opacity: .82 }}>
              Valve controls the light bar until CPU and GPU stay below 90°C for 30 seconds.
              {status.thermal_protection.recovery_remaining_s == null ? " Waiting for coherent sensor readings." : ` Recovery in ${Math.ceil(status.thermal_protection.recovery_remaining_s)} s.`}
            </div>
          </div>
        </PanelSectionRow>
      </PanelSection> : null}

      {showPage("routing") ? <>
        <PanelSection title={settingsView?undefined:'GabeCubeAura'}>
          {!settingsView?<PanelSectionRow><ButtonItem label="Guided setup"
            onClick={() => { Navigation.CloseSideMenus(); Navigation.Navigate("/gabecubeaura/setup"); }}>Review my setup</ButtonItem></PanelSectionRow>:null}
          <PanelSectionRow><ToggleField label="Enable GabeCubeAura"
            description="Turns off every GabeCubeAura light without deleting display routes, launch effects, or per-game choices."
            checked={status.signalbar_enabled}
            onChange={async (value) => setStatus(await setSetting("signalbar_enabled", value))} /></PanelSectionRow>
          <PanelSectionRow><DropdownItem label="Lighting preset"
            description={status.display_preset === "lights-out"
              ? <>All LEDs stay off except Steam Families. <b>Even Valve download animations are excluded.</b></>
              : DISPLAY_PRESET_DESCRIPTIONS[status.display_preset] ?? DISPLAY_PRESET_DESCRIPTIONS.custom}
            rgOptions={DISPLAY_PRESET_OPTIONS} selectedOption={status.display_preset}
            onChange={(option) => void applyDisplayPreset(String(option.data))} /></PanelSectionRow>
          {settingsView?<PanelSectionRow><Localized><small className="gca-preset-summary">{presetSummary(status.display_preset)}</small></Localized></PanelSectionRow>:null}
          {routingMessage ? <PanelSectionRow><div style={{ fontSize: ".78em", color: "#ffd27a" }}>
            {routingMessage}
          </div></PanelSectionRow> : null}
        </PanelSection>
        <PanelSection title={settingsView?'Light bar display':'Display routing'}>
          <SettingsDetails title="Steam priority and thermal protection">
          <PanelSectionRow><DropdownItem label="Steam ownership"
            description={VALVE_OWNERSHIP_DESCRIPTIONS[status.valve_ownership_policy] ?? VALVE_OWNERSHIP_DESCRIPTIONS.cooperative}
            rgOptions={VALVE_OWNERSHIP_OPTIONS} selectedOption={status.valve_ownership_policy}
            onChange={async (option) => setStatus(await setSetting("valve_ownership_policy", String(option.data)))} /></PanelSectionRow>
          <PanelSectionRow><div style={{ fontSize: ".76em", opacity: .78 }}>
            Thermal protection reads CPU and GPU temperatures independently of LED colours. At 94°C GabeCubeAura immediately returns the light bar to Valve, then waits for 30 continuous seconds below 90°C. A fixed red colour remains available for ordinary lighting.
          </div></PanelSectionRow>
          </SettingsDetails>
          <PanelSectionRow><DropdownItem label="Home display"
            description="The permanent display used when no game is running. Temporary alerts and previews may still replace it."
            rgOptions={HOME_DISPLAY_OPTIONS.filter(option=>!settingsView||status.faceplate.available||option.data!=='faceplate_extension'||status.home_display==='faceplate_extension')} selectedOption={status.home_display}
            renderButtonValue={(value) => legacyGameDisplayLabel(status.home_display, value)}
            onChange={async (option) => setStatus(await setSetting("home_display", String(option.data)))} /></PanelSectionRow>
          <PanelSectionRow><DropdownItem label="In-game display"
            description="The permanent display used by games without their own override."
            rgOptions={gameDisplayOptions(status.faceplate.available, status.game_display)} selectedOption={status.game_display}
            renderButtonValue={(value) => legacyGameDisplayLabel(status.game_display, value)}
            onChange={async (option) => setStatus(await setSetting("game_display", String(option.data)))} /></PanelSectionRow>
          <ScreensaverLightBarChoice status={status} setStatus={setStatus}/>
          {status.home_display === "faceplate_extension" || status.game_display === "faceplate_extension" || status.current_display === "faceplate_extension" || status.screensaver_light_bar_mode === "faceplate_extension" ? <>
            <PanelSectionRow><DropdownItem label="Faceplate image projection"
              description="Uses the original image before Dashboard text and its bottom row. Animations give stable average colours, not frame-synchronised motion."
              rgOptions={[{ data: "bottom", label: "Bottom edge" }, { data: "whole", label: "Whole image" }]}
              selectedOption={status.faceplate_extension_mapping ?? "bottom"}
              onChange={async (option) => setStatus(await setSetting("faceplate_extension_mapping", String(option.data)))} /></PanelSectionRow>
            <PanelSectionRow><SliderField label="Extension colour saturation"
              description="100% keeps the original colours. Higher values reduce white in tinted colours without increasing the brightest RGB channel. Pure white and grey remain neutral."
              value={status.faceplate_extension_saturation ?? 100} min={0} max={250} step={5} showValue valueSuffix="%"
              onChange={async (value) => setStatus(await setSetting("faceplate_extension_saturation", value))} /></PanelSectionRow>
            <PanelSectionRow><Localized><div style={{ fontSize: ".78em", opacity: .75 }}>
              Supports Artwork, Realistic Weather, Dashboard backgrounds and Steam Players City without its counter. When the Faceplate is unavailable, the light bar uses current-game Artwork, or returns control to Steam at Home. The saved extension resumes when the Faceplate returns. Global brightness and priority alerts are unchanged.
            </div></Localized></PanelSectionRow>
          </> : null}
          <SettingsHelpText><PanelSectionRow><div style={{ fontSize: ".78em", opacity: .75 }}>
            Light bar off keeps the Faceplate running. Light bar + Faceplate off applies only during the game. The master switch turns both displays off everywhere. Steam control is in Advanced.
          </div></PanelSectionRow></SettingsHelpText>
        </PanelSection>
        {status.game.appid > 0 ? <PanelSection title="Current game override">
          <PanelSectionRow><DropdownItem label={status.game.title || `AppID ${status.game.appid}`} untranslatedProps={["label"]}
            description="Saved for this AppID only."
            rgOptions={[{ data: "inherit", label: "Use in-game default" }, ...gameDisplayOptions(status.faceplate.available, status.display_override)]}
            renderButtonValue={(value) => legacyGameDisplayLabel(status.display_override, value)}
            selectedOption={status.display_override}
            onChange={async (option) => setStatus(await setGameDisplay(status.game.appid, String(option.data)))} /></PanelSectionRow>
        </PanelSection> : null}
        <LightBarBrightness status={status} setStatus={setStatus} />
      </> : null}

      {showPage("customization") ? <CustomizationPanel status={status} setStatus={setStatus} /> : null}

      {showPage("screen-sync") ? <ScreenSyncPanel status={status} setStatus={setStatus} /> : null}

      {showPage("audio-sync") ? <AudioSyncPanel status={status} setStatus={setStatus} /> : null}

      {showPage("artwork") ? <><PanelSection title="Artwork display">
        <PanelSectionRow>
          <DropdownItem
            label="Steam image"
            rgOptions={ARTWORK_SOURCE_OPTIONS}
            selectedOption={status.artwork_source}
            onChange={(option) => void changeArtworkSetting("source", String(option.data))}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <DropdownItem
            label="Sample row"
            rgOptions={ARTWORK_OPTIONS}
            selectedOption={status.artwork_mode}
            onChange={(option) => void changeArtworkSetting("mode", String(option.data))}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={{ fontSize: ".78em", opacity: 0.72 }}>
            {status.game.appid > 0
              ? status.artwork_custom
                ? `Saved for ${status.game.title || `AppID ${status.game.appid}`}`
                : "Using the default; your first change will be saved for this game."
              : "No game running: changes update the default for new games."}
          </div>
        </PanelSectionRow>
        {status.artwork_mode === "manual" ? (
          <PanelSectionRow>
            <SliderField
              label="Vertical position"
              value={Math.round(status.artwork_manual_y * 100)}
              min={15}
              max={90}
              step={1}
              showValue
              valueSuffix="%"
              onChange={(value) => changeManualPosition(value / 100)}
            />
          </PanelSectionRow>
        ) : null}
        <PanelSectionRow>
          <SliderField
            label="Artwork colour intensity"
            description="Adjusts perceptual vibrance while retaining lightness. 0% is greyscale, 100% preserves the current GabeCubeAura rendering and 200% is the strongest protected boost."
            value={status.artwork_vibrance}
            min={0}
            max={200}
            step={5}
            showValue
            valueSuffix="%"
            onChange={changeArtworkVibrance}
          />
        </PanelSectionRow>
        {currentArtwork ? (
          <PanelSectionRow>
            <ArtworkImage
              artwork={currentArtwork}
              title={status.game.title || "current game"}
              sampleLine={status.artwork_mode === "manual" ? status.artwork_manual_y : undefined}
            />
          </PanelSectionRow>
        ) : null}
        <PanelSectionRow>
          <div style={{ width: "100%", fontSize: ".8em", opacity: 0.86 }}>
            {status.game.title ? <span translate="no">{status.game.title}</span> : (status.game.appid > 0 ? `AppID ${status.game.appid}` : "No game selected")}
            {currentArtwork?.source_label ? ` · ${currentArtwork.source_label}` : ""}
            {status.artwork.sample_y != null ? ` · row ${Math.round(status.artwork.sample_y * 100)}%` : ""}
            <PalettePreview source="artwork" colors={artColors} />
          </div>
        </PanelSectionRow>
      </PanelSection>
        <PanelSection title="Faceplate Artwork Studio · 64 × 54">
          <PanelSectionRow><div style={{ width: "100%", fontSize: ".8em", lineHeight: 1.5 }}>
            <div><b>Dedicated faceplate path.</b> This does not change the 17-LED Artwork display above.</div>
            <div style={{ marginTop: 5, opacity: .78 }}>
              {status.faceplate.last_asset
                ? `Current matrix asset: ${status.faceplate.last_asset}`
                : "Artwork Dashboard uses local Steam artwork automatically. Use the Studio for a custom or animated background."}
            </div>
          </div></PanelSectionRow>
          <PanelSectionRow><ButtonItem
            label="Open Faceplate Artwork Studio"
            description="Native Decky workflow: choose an installed game, compare lightweight previews, generate outside gameplay, then activate explicitly."
            onClick={() => { Navigation.CloseSideMenus(); Navigation.Navigate("/gabecubeaura/settings/pixel-artwork"); }}
          >Choose artwork</ButtonItem></PanelSectionRow>
        </PanelSection>
      </> : null}

      {showPage("launches") ? <PanelSection title="Game launch animation">
        <PanelSectionRow><ToggleField
          label="Animate from game artwork"
          description="Play one sequence when GabeCubeAura detects a newly running Steam AppID. This works with every Home and in-game display; starting GabeCubeAura while a game is already running does not replay it."
          checked={status.launch_artwork_animation_enabled}
          onChange={async (value) => setStatus(await setSetting("launch_artwork_animation_enabled", value))}
        /></PanelSectionRow>
        <PanelSectionRow><div style={{ fontSize: ".8em", opacity: .82 }}>
          {status.game.appid > 0
            ? `${status.game.title || "Running game"} · AppID ${status.game.appid} · ${status.launch_artwork_palette_mode === "custom" ? "custom palette saved" : "artwork palette"}`
            : "Start a game to detect its artwork or save a palette for its AppID."}
        </div></PanelSectionRow>
        <PanelSectionRow><DropdownItem
          label="Artwork image"
          description="Uses Steam's local artwork, including custom SteamGridDB images already installed in Steam. No image is uploaded."
          rgOptions={ARTWORK_SOURCE_OPTIONS}
          selectedOption={status.launch_artwork_source}
          onChange={async (option) => {
            const next = await setSetting("launch_artwork_source", String(option.data));
            setStatus(next);
            if (next.game.appid > 0) await loadAndSampleArtwork(
              next.game.appid, next.launch_artwork_source, "launch",
            );
          }}
        /></PanelSectionRow>
        <PanelSectionRow><DropdownItem
          label="Palette source"
          description="A custom palette is saved for this AppID and reused on future launches."
          rgOptions={LAUNCH_PALETTE_MODE_OPTIONS}
          selectedOption={status.launch_artwork_palette_mode}
          disabled={status.game.appid <= 0}
          onChange={async (option) => setStatus(await setLaunchArtworkSetting(
            status.game.appid, "palette_mode", String(option.data),
          ))}
        /></PanelSectionRow>
        <PanelSectionRow><DropdownItem
          label="Number of colours"
          rgOptions={LAUNCH_ARTWORK_COLOUR_OPTIONS}
          selectedOption={status.launch_artwork_colour_count}
          onChange={async (option) => setStatus(await setSetting("launch_artwork_colour_count", Number(option.data)))}
        /></PanelSectionRow>
        {status.launch_artwork_palette_mode === "custom" && status.game.appid > 0
          ? status.launch_artwork_custom_palettes[String(status.launch_artwork_colour_count) as "2" | "3"].map((color, index) =>
            <PanelSectionRow key={`launch-custom-${status.launch_artwork_colour_count}-${index}`}>
              <PreciseColorEditor label={`Launch colour ${index + 1}`} color={color}
                onChange={(nextColor) => {
                  const palettes = {
                    "2": status.launch_artwork_custom_palettes["2"].map((entry) => [...entry] as RGB) as [RGB, RGB],
                    "3": status.launch_artwork_custom_palettes["3"].map((entry) => [...entry] as RGB) as [RGB, RGB, RGB],
                  };
                  palettes[String(status.launch_artwork_colour_count) as "2" | "3"][index] = nextColor;
                  void setLaunchArtworkSetting(status.game.appid, "custom_palettes", palettes).then(setStatus).catch(actionFailed);
                }} />
            </PanelSectionRow>) : null}
        <PanelSectionRow><DropdownItem
          label="Pattern"
          rgOptions={LAUNCH_ARTWORK_PATTERN_OPTIONS}
          selectedOption={status.launch_artwork_pattern}
          onChange={async (option) => setStatus(await setSetting("launch_artwork_pattern", String(option.data)))}
        /></PanelSectionRow>
        <PanelSectionRow><SliderField
          label="Animation duration"
          value={status.launch_artwork_duration_seconds}
          min={3}
          max={45}
          step={1}
          showValue
          valueSuffix=" s"
          onChange={async (value) => setStatus(await setSetting("launch_artwork_duration_seconds", value))}
        /></PanelSectionRow>
        <PanelSectionRow><div style={{ width: "100%", fontSize: ".8em", opacity: .86 }}>
          {status.launch_artwork_palette_mode === "custom" ? "Saved colours for this game." : "Detected colours from the complete image, independent of the permanent Artwork row."}
        </div></PanelSectionRow>
        <PanelSectionRow><ButtonItem
          label="Preview launch animation"
          description={!status.signalbar_enabled
            ? "Enable GabeCubeAura first."
            : status.game.appid > 0 && (status.launch_artwork.dominant_colors?.length ?? 0) > 0
            ? "Play the selected pattern with the current game's active palette."
            : "Start a game and wait for its palette first."}
          disabled={!status.signalbar_enabled || status.game.appid <= 0 || (status.launch_artwork.dominant_colors?.length ?? 0) === 0}
          onClick={() => void runLaunchPreview()}
        >Preview</ButtonItem></PanelSectionRow>
        <PanelSectionRow><div style={{ width: "100%", fontSize: ".78em", opacity: .82 }}>
          Live 17-LED launch preview
          <PalettePreview source="launch_artwork" colors={status.launch_artwork.colors ?? []} />
        </div></PanelSectionRow>
        <PanelSectionRow><div style={{ fontSize: ".76em", opacity: .72 }}>
          {status.launch_artwork.active
            ? `${status.launch_artwork.paused ? "Paused by a short alert" : "Playing"} · ${Math.ceil(status.launch_artwork.remaining_seconds)} s remaining`
            : status.launch_artwork.pending ? "Waiting for safe LED ownership and artwork colours…"
              : launchPreviewError || "Idle"}
        </div></PanelSectionRow>
        {currentLaunchArtwork ? <PanelSectionRow>
          <Focusable style={{ width: "100%", paddingBottom: 28, scrollMarginBottom: 24 }} aria-label="Launch artwork preview">
            <ArtworkImage artwork={currentLaunchArtwork} title={status.game.title || "current game"} />
          </Focusable>
        </PanelSectionRow> : null}
        <PanelSectionRow><ButtonItem
          label="Preview launch animation"
          description={!status.signalbar_enabled
            ? "Enable GabeCubeAura first."
            : status.game.appid > 0 && (status.launch_artwork.dominant_colors?.length ?? 0) > 0
              ? "Play the selected pattern again after reviewing the artwork."
              : "Start a game and wait for its palette first."}
          disabled={!status.signalbar_enabled || status.game.appid <= 0 || (status.launch_artwork.dominant_colors?.length ?? 0) === 0}
          onClick={() => void runLaunchPreview()}
        >Preview</ButtonItem></PanelSectionRow>
      </PanelSection> : null}

      {showPage("performance") ? <PanelSection title="Performance">
        <PanelSectionRow><div style={{ fontSize: ".78em", opacity: .75 }}>
          Sensors update every 0.5 seconds in all display modes. These settings do not switch the active display.
        </div></PanelSectionRow>
        <PanelSectionRow>
          <DropdownItem
            label="Meter"
            rgOptions={PERFORMANCE_OPTIONS}
            selectedOption={status.performance_metric}
            onChange={async (option) => setStatus(await setSetting("performance_metric", String(option.data)))}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <DropdownItem
            label="Meter response"
            rgOptions={SMOOTHING_OPTIONS}
            selectedOption={status.performance_smoothing}
            onChange={async (option) => setStatus(await setSetting("performance_smoothing", String(option.data)))}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={{ fontSize: ".78em", opacity: 0.72 }}>
            {status.performance_smoothing === "responsive"
              ? "Follows short CPU/GPU changes more closely."
              : status.performance_smoothing === "smooth"
                ? "Slow, steady movement with stronger filtering."
                : "Reduces sudden jumps while keeping sustained load changes visible."}
          </div>
        </PanelSectionRow>
        {status.performance_metric === "mixed" ? (
          <>
            <PanelSectionRow>
              <DropdownItem
                label="Fill direction"
                rgOptions={DIRECTION_OPTIONS}
                selectedOption={status.mixed_direction}
                onChange={async (option) => setStatus(await setSetting("mixed_direction", String(option.data)))}
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <div style={{ fontSize: ".78em", opacity: 0.72 }}>
                CPU uses the left 8 LEDs, GPU the right 8, with the centre LED off. Choose two left-to-right meters or the mirrored layout that grows from both edges toward the centre.
              </div>
            </PanelSectionRow>
          </>
        ) : null}
        <PanelSectionRow>
          <div style={{ width: "100%" }}>
            <PerformanceReadout status={status} />
            <PalettePreview source="performance" colors={performanceColors} />
          </div>
        </PanelSectionRow>
        <SettingsDetails title="Temperature colours and thresholds">
        <PanelSectionRow>
          <DropdownItem
            label="Temperature colours"
            rgOptions={PALETTE_OPTIONS}
            selectedOption={status.temperature_palette}
            onChange={async (option) => setStatus(await setSetting("temperature_palette", String(option.data)))}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={{ fontSize: ".78em", opacity: 0.72 }}>
            Length shows load. Colour shows temperature: the palette starts at Cool temperature and reaches its final hot colour at Hot temperature, with a continuous blend between them.
          </div>
        </PanelSectionRow>
        {status.temperature_palette === "custom" ? <>
          <PanelSectionRow>
            <ColorChoice
              label="Cool colour"
              color={status.temperature_custom_cool}
              onClick={() => chooseTemperatureColor("temperature_custom_cool", "Cool colour", status.temperature_custom_cool)}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <ColorChoice
              label="Middle colour"
              color={status.temperature_custom_middle}
              onClick={() => chooseTemperatureColor("temperature_custom_middle", "Middle colour", status.temperature_custom_middle)}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <ColorChoice
              label="Hot colour"
              color={status.temperature_custom_hot}
              onClick={() => chooseTemperatureColor("temperature_custom_hot", "Hot colour", status.temperature_custom_hot)}
            />
          </PanelSectionRow>
        </> : null}
        <PanelSectionRow>
          <SliderField
            label="Cool temperature"
            value={status.cool_temp_c}
            min={30}
            max={80}
            step={1}
            showValue
            valueSuffix="°C"
            onChange={async (value) => setStatus(await setSetting("cool_temp_c", value))}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <SliderField
            label="Hot temperature"
            value={status.hot_temp_c}
            min={60}
            max={110}
            step={1}
            showValue
            valueSuffix="°C"
            onChange={async (value) => setStatus(await setSetting("hot_temp_c", value))}
          />
        </PanelSectionRow>
        </SettingsDetails>
      </PanelSection> : null}

      {showPage("countdown") ? <CountdownPanel status={status} setStatus={setStatus} /> : null}

      {showPage("events") ? <EventsPanel status={status} setStatus={setStatus} kind={settingsView?eventSource:undefined} /> : null}

      {showPage("controllers") ? <ControllersPanel status={status} setStatus={setStatus} /> : null}

      {showPage("weather") ? <WeatherPanel status={status} setStatus={setStatus} /> : null}

      {showPage("pixel-artwork") && settingsView ? <PixelStudioArtworkPanel status={status} setStatus={setStatus} /> : null}

      {showPage("pixel-settings") ? <>
        {STUDIO_UX ? <FaceplateStatePanel status={status} /> : <PixelStudioWeatherCatalog status={status} setStatus={setStatus} />}
        <SettingsPart slot="faceplate.protection"><FlashProtectionPanel status={status} collapsible={!settingsView}
          onChange={async enabled=>setStatus(await setSetting('faceplate_flash_protection_enabled',enabled))}/></SettingsPart>
        <PanelSection title={settingsView?undefined:'Faceplate automation'}>
          <SettingsPart slot="faceplate.display">
          <PanelSectionRow><ToggleField label="Follow GabeCubeAura automatically"
            description="Uses independent Home and in-game Faceplate routes. This switch remains opt-in and never changes the 17-LED routing."
            checked={status.faceplate_lab_enabled}
            onChange={async (enabled) => setStatus(await setSetting("faceplate_lab_enabled", enabled))} /></PanelSectionRow>
          <PanelSectionRow><FaceplateBrightnessSlider status={status} setStatus={setStatus} /></PanelSectionRow>
          <PanelSectionRow><ToggleField label="Continuous screensaver return (experimental)"
            description="Keeps the current animation visible while Home loads. Requires validation on your JSAUX faceplate."
            checked={status.faceplate_continuous_home_return ?? false}
            onChange={async enabled=>setStatus(await setSetting('faceplate_continuous_home_return',enabled))}/></PanelSectionRow>
          <PanelSectionRow><DropdownItem
            label="Faceplate at Home"
            description="Choose your Home background here. Dashboard adds the information configured in the Dashboard tab."
            rgOptions={FACEPLATE_HOME_OPTIONS}
            disabled={faceplateActionBusy}
            selectedOption={homeFaceChoice(status)}
            onChange={async (option) => {
              await changeFaceplateRoute(
                option.data as "weather" | "dashboard" | "artwork" | "artwork-dashboard" | "native-clock",
                status.faceplate.routing.routes.game,
              );
            }}
          /></PanelSectionRow>
          {isDashboardChoice(homeFaceChoice(status)) ? <PanelSectionRow><Localized><div role="status" style={{color:'#ffd27a',fontSize:'.85em'}}>
            See the Dashboard tab to configure your choices.
          </div></Localized></PanelSectionRow> : null}
          {status.faceplate.routing.routes.home === "native-clock" ? <PanelSectionRow>
            <div style={{ fontSize: ".78em", lineHeight: 1.4, opacity: .8 }}>
              <div>Uses the JSAUX firmware clock instead of repeatedly uploading GIFs. The panel keeps time autonomously. Blue 24-hour display; entering the mode may still update flash settings.</div>
              <div>Native appearance cannot be customized. Firmware rotation is undocumented; disable Faceplate 180-degree rotation to use this clock.</div>
            </div>
          </PanelSectionRow> : null}
          </SettingsPart>
          <SettingsPart slot="faceplate.dashboard">
            <FaceplateDashboardSettings status={status} setStatus={setStatus} />
          </SettingsPart>
          <SettingsPart slot="faceplate.display">
          <PanelSectionRow><DropdownItem
            label="Faceplate in game"
            description="Choose your in-game background here. Dashboard adds the information configured in the Dashboard tab."
            rgOptions={FACEPLATE_GAME_OPTIONS}
            disabled={faceplateActionBusy}
            selectedOption={status.faceplate.routing.routes.game}
            onChange={async (option) => await changeFaceplateRoute(
              homeFaceChoice(status),
              option.data as "dashboard" | "artwork" | "artwork-dashboard" | "weather" | "player-city",
            )}
          /></PanelSectionRow>
          {isDashboardChoice(status.faceplate.routing.routes.game) ? <PanelSectionRow><Localized><div role="status" style={{color:'#ffd27a',fontSize:'.85em'}}>
            See the Dashboard tab to configure your choices.
          </div></Localized></PanelSectionRow> : null}
          {status.faceplate.routing.routes.game==='player-city'?<PanelSectionRow><small role="status">{playerCitySummary(status)}</small></PanelSectionRow>:null}
          {status.faceplate.routing.routes.game==='player-city'?<PlayerCityRowSettings status={status} setStatus={setStatus} disabled={faceplateActionBusy}/>:null}
          </SettingsPart>
          <SettingsPart slot="faceplate.display">
            {faceplateRoutingMessage ? <PanelSectionRow><Localized><div role="status">{faceplateRoutingMessage}</div></Localized></PanelSectionRow> : null}
          </SettingsPart>
          <SettingsPart slot="faceplate.sgdb"><Disclosure title="SteamGridDB key">
          <PanelSectionRow><ButtonItem
            label="Log in to SteamGridDB"
            description="Opens the direct Steam OpenID page in the system browser, avoiding SteamGridDB's blocked popup."
            onClick={() => openCopyCapableBrowser(STEAMGRIDDB_DIRECT_LOGIN_URL)}
          >Log in with Steam</ButtonItem></PanelSectionRow>
          <PanelSectionRow><ButtonItem
            label="Open API keys in the system browser"
            description="The full browser restores text selection, right-click and clipboard copy. Open this after logging in."
            onClick={() => openCopyCapableBrowser(STEAMGRIDDB_API_KEY_URL)}
          >Open copy-capable browser</ButtonItem></PanelSectionRow>
          <PanelSectionRow><div style={{ width: "100%", fontSize: ".76em", opacity: .76, lineHeight: 1.45 }}>
            Keyboard fallback in Steam's browser: focus the API-key field, then press <b>Ctrl+A</b> and <b>Ctrl+C</b>.
          </div></PanelSectionRow>
          <PanelSectionRow><TextField
            label="Personal API key"
            description={status.faceplate.steamgriddb.configured
              ? "Configured locally. Paste a replacement only when you want to change it."
              : "Stored only on this Steam Machine and never included in exports."}
            value={steamGridDbKey}
            onChange={(event) => setSteamGridDbKey(event.currentTarget.value)}
          /></PanelSectionRow>
          <PanelSectionRow><div style={{ width: "100%", fontSize: ".82em", lineHeight: 1.45 }}>
            SteamGridDB: <b>{steamGridDBValidationLabel(status.faceplate.steamgriddb.validation_state)}</b>
            {status.faceplate.steamgriddb.validation_detail
              ? <div style={{ marginTop: 4, color: "#ffcf8a" }}>Diagnostic: {status.faceplate.steamgriddb.validation_detail}
                {status.faceplate.steamgriddb.validation_code ? ` · ${status.faceplate.steamgriddb.validation_code}` : ""}</div>
              : null}
            {status.faceplate.steamgriddb.validated_at
              ? <div style={{ marginTop: 4, opacity: .72 }}>Last validation: {new Date(status.faceplate.steamgriddb.validated_at * 1000).toLocaleString()}</div>
              : null}
          </div></PanelSectionRow>
          <PanelSectionRow><ButtonItem
            label={status.faceplate.steamgriddb.configured ? "Replace SteamGridDB key" : "Save SteamGridDB key"}
            description="The key is used only by GabeCubeAura for faceplate artwork."
            disabled={faceplateActionBusy || steamGridDbKey.trim().length < 16}
            onClick={() => {
              setFaceplateActionBusy(true);
              void setSteamGridDBApiKey(steamGridDbKey.trim()).then((next) => {
                setStatus(next); setSteamGridDbKey("");
              }).catch(actionFailed).finally(() => setFaceplateActionBusy(false));
            }}
          >Save key</ButtonItem></PanelSectionRow>
          {status.faceplate.steamgriddb.configured ? <PanelSectionRow><ButtonItem
            label="Verify SteamGridDB key now"
            description="Performs one lightweight authenticated request. The key itself is never returned to Decky."
            disabled={faceplateActionBusy}
            onClick={() => {
              setFaceplateActionBusy(true);
              void validateSteamGridDBApiKey().then(setStatus).catch(actionFailed)
                .finally(() => setFaceplateActionBusy(false));
            }}
          >Verify</ButtonItem></PanelSectionRow> : null}
          {status.faceplate.steamgriddb.configured ? <PanelSectionRow><ButtonItem
            label="Forget SteamGridDB key"
            description="Removes the personal key; already compiled faceplate artwork remains available offline."
            disabled={faceplateActionBusy}
            onClick={() => {
              setFaceplateActionBusy(true);
              void clearSteamGridDBApiKey().then(setStatus).catch(actionFailed)
                .finally(() => setFaceplateActionBusy(false));
            }}
          >Forget</ButtonItem></PanelSectionRow> : null}
          </Disclosure></SettingsPart>
          <SettingsPart slot="faceplate.power">
          <PanelSectionRow><DropdownItem
            label="Sleep / shutdown power"
            description="Auto cancels any transfer, retries the volatile power-off before sleep/shutdown, then powers on and reapplies the current scene after resume. It never rewrites an identical GIF."
            rgOptions={FACEPLATE_POWER_OPTIONS}
            selectedOption={status.faceplate_power_mode}
            onChange={async (option) => setStatus(await setSetting("faceplate_power_mode", String(option.data)))}
          /></PanelSectionRow>
          {status.faceplate.power_recovery?.retry_pending ? <PanelSectionRow><div style={{ width: "100%", fontSize: ".78em", color: "#ffcf8a", lineHeight: 1.45 }}>
            Faceplate recovery is retrying automatically
            {status.faceplate.power_recovery.error ? ` · ${status.faceplate.power_recovery.error}` : ""}
          </div></PanelSectionRow> : null}
          <PanelSectionRow><ButtonItem
            label={status.faceplate.powered === false ? "Turn faceplate on" : "Turn faceplate off"}
            description={status.faceplate.powered === false
              ? "Restores panel power and reapplies the current brightness; the stored GIF resumes."
              : "Turns only the matrix off now. The stored GIF and flash contents are preserved."}
            disabled={faceplateActionBusy || !status.faceplate.available || status.faceplate.busy}
            onClick={() => {
              setFaceplateActionBusy(true);
              void setFaceplatePower(status.faceplate.powered === false).then(setStatus)
                .catch(actionFailed).finally(() => setFaceplateActionBusy(false));
            }}
          >{status.faceplate.powered === false ? "Power on" : "Power off"}</ButtonItem></PanelSectionRow>
          </SettingsPart>
        </PanelSection>
        {STUDIO_UX ? <PixelStudioWeatherCatalog status={status} setStatus={setStatus} /> : null}
        <SettingsHelpText><PanelSection title="How it fits together">
          <PanelSectionRow><div style={{ width: "100%", fontSize: ".78em", opacity: .8, lineHeight: 1.45 }}>
            Pixel Studio prepares your images. GabeCubeAura manages the Faceplate and light bar together, in one plugin.
          </div></PanelSectionRow>
        </PanelSection></SettingsHelpText>
      </> : null}

      {showPage("pixel-artwork") && !settingsView ? <PixelStudioArtworkPanel status={status} setStatus={setStatus} /> : null}

      {showPage("updates") && update ? <>
        <SettingsPart slot="updates.install"><PanelSection title="Software updates">
          <PanelSectionRow><div style={{ width: "100%", fontSize: ".82em", lineHeight: 1.45 }}>
            <div>Installed version: <b>{update.installed_version}</b></div>
            <div>{update.channel === "stable" ? "Latest stable version" : update.channel === "beta" ? "Latest beta or stable version" : "Latest private lab version"}: <b>{update.available_version || update.installed_version}</b></div>
            <div>Current status: <b>{updatePhaseLabel(update)}</b></div>
            {update.phase === "downloading" && update.download_total_bytes ? <div>
              <progress style={{ width: "100%" }} value={update.download_bytes ?? 0} max={update.download_total_bytes} />
              {Math.floor(100 * (update.download_bytes ?? 0) / update.download_total_bytes)}% · {((update.download_bytes ?? 0) / 1048576).toFixed(1)} / {(update.download_total_bytes / 1048576).toFixed(1)} MiB
            </div> : null}
            {updateInstallError && !update.error ? <div role="alert" style={{ color: "#ffb3b3", marginTop: 6 }}>{updateInstallError}</div> : null}
            {update.error ? <div role="alert" style={{ color: "#ffb3b3", marginTop: 6 }}>{update.error}</div> : null}
            <div>Last checked: {formatUpdateDate(update.last_checked_at)}</div>
            {update.prepared_digest ? <div>Verified SHA256: <code>{update.prepared_digest.slice(0, 12)}...</code></div> : null}
            {update.bundle_components.length ? <div>Verified bundle: <b>{update.bundle_components.map((component) => component === "plugin" ? "GabeCubeAura" : component === "faceplate-service" ? "Faceplate service" : "Pixel Studio").join(" · ")}</b></div> : null}
            {update.test_build ? <div style={{ marginTop: 6, color: "#ffd166", fontWeight: 700 }}>TEST BUILD</div> : null}
          </div></PanelSectionRow>
          <PanelSectionRow><ButtonItem label="Check for updates"
            disabled={updateBusy || ["checking", "downloading", "verifying", "preparing_install", "installing", "restart_pending"].includes(update.phase)}
            onClick={() => void runUpdateAction(checkForUpdates)}>Check now</ButtonItem></PanelSectionRow>
          {update.release_url ? <PanelSectionRow><ButtonItem label="View release notes"
            description={`Opens the selected ${update.channel === "private" ? "private Lab" : "public GabeCubeAura"} release page.`}
            onClick={() => Navigation.NavigateToExternalWeb(update.release_url)}>Open GitHub</ButtonItem></PanelSectionRow> : null}
          {update.phase === "available" ? <PanelSectionRow><ButtonItem label="Download update"
            description={update.auto_install ? "Downloads and checks the archive, then installs automatically." : "Downloads and checks the archive. Nothing is installed yet."}
            disabled={updateBusy} onClick={() => void runUpdateAction(prepareUpdate)}>Download and verify</ButtonItem></PanelSectionRow> : null}
          {["downloading", "verifying"].includes(update.phase) ? <PanelSectionRow><ButtonItem label="Cancel preparation"
            description="Keeps the installed version. Temporary download and staging files are removed."
            onClick={() => void cancelUpdatePreparation().then(setUpdate)}>Cancel download</ButtonItem></PanelSectionRow> : null}
          {update.phase === "ready" || (update.phase === "error" && update.confirmation_token) ? <PanelSectionRow><ButtonItem label={`${update.recovery_prepared ? "Restore" : "Install"} ${update.available_version}`}
            description={update.bundle_components.length > 1 ? "Updates GabeCubeAura, the faceplate service and Pixel Studio together. Settings and artwork caches are kept." : "Settings and artwork caches are kept. Decky restarts briefly."}
            disabled={updateBusy} onClick={() => confirmUpdateInstall()}>{update.recovery_prepared ? "Restore and restart Decky" : "Update and restart Decky"}</ButtonItem></PanelSectionRow> : null}
          {update.release_notes ? <PanelSectionRow><div style={{ width: "100%", fontSize: ".76em", opacity: .8, whiteSpace: "pre-wrap", maxHeight: 180, overflow: "hidden" }}>
            {update.release_notes}
          </div></PanelSectionRow> : null}
          {update.phase === "error" ? <PanelSectionRow><ButtonItem label="Dismiss update error"
            onClick={() => void runUpdateAction(dismissUpdateError)}>Dismiss</ButtonItem></PanelSectionRow> : null}
        </PanelSection></SettingsPart>

        <SettingsPart slot="updates.preferences"><PanelSection title="Automatic checks">
          <PanelSectionRow><ToggleField label="Automatically check for updates"
            description="Checks the selected channel at startup and at your chosen interval."
            checked={update.auto_check} onChange={(value) => void runUpdateAction(() => setUpdatePreferences(value, update.notifications, update.check_interval_minutes, update.channel))} /></PanelSectionRow>
          <PanelSectionRow><DropdownItem label="Check interval"
            description="How often to check for updates."
            disabled={!update.auto_check || updateBusy}
            rgOptions={UPDATE_INTERVAL_OPTIONS} selectedOption={update.check_interval_minutes}
            onChange={(option) => void runUpdateAction(() => setUpdatePreferences(update.auto_check, update.notifications, Number(option.data), update.channel))} /></PanelSectionRow>
          <PanelSectionRow><DropdownItem label="Update channel"
            description={update.channel === "stable"
              ? "Stable releases only."
              : update.channel === "beta"
                ? "Beta releases and later stable releases."
                : "Private hardware-lab releases from Alyenax/GabeCubeAura-Lab. GitHub authorization is required."}
            disabled={updateBusy || ["downloading", "verifying", "preparing_install", "installing", "restart_pending"].includes(update.phase)}
            rgOptions={UPDATE_CHANNEL_OPTIONS.filter(option => option.data !== "private" || update.private_tools)} selectedOption={update.channel}
            onChange={(option) => void runUpdateAction(() => setUpdatePreferences(update.auto_check, update.notifications, update.check_interval_minutes, String(option.data) as "stable" | "beta" | "private"))} /></PanelSectionRow>
          <PanelSectionRow><ToggleField label="Notify me when an update is available"
            description="Shows one Decky notification for each new version on the selected channel."
            checked={update.notifications} onChange={(value) => void runUpdateAction(() => setUpdatePreferences(update.auto_check, value, update.check_interval_minutes, update.channel))} /></PanelSectionRow>
        </PanelSection></SettingsPart>
        <SettingsPart slot="updates.recovery"><SettingsDetails title="Return to the previous version"><PanelSection title="Return to the previous version">

          <PanelSectionRow><div style={{ fontSize: ".8em", lineHeight: 1.45 }}>
            {update.recovery_available ? `Local backup: ${update.recovery_version}. Settings, preferences and artwork selections are included.`
              : "No previous-version backup is available. Do not rely on in-app recovery for this installation."}
            {update.recovery_error ? <div style={{ color: "#ffb3b3" }}>{update.recovery_error}</div> : null}
          </div></PanelSectionRow>
          <PanelSectionRow><ButtonItem label="Prepare previous version"
            description="Verifies the local backup without downloading. Review the restoration confirmation before applying."
            disabled={!update.recovery_available || updateBusy || ["checking", "downloading", "verifying", "ready", "preparing_install", "installing", "restart_pending"].includes(update.phase)}
            onClick={() => void runUpdateAction(preparePreviousVersion)}>Verify backup</ButtonItem></PanelSectionRow>
        </PanelSection></SettingsDetails></SettingsPart>
        <SettingsPart slot="updates.safety"><SettingsDetails title="Installation integrity and safety"><PanelSection title="Installation safety">
          <PanelSectionRow><div style={{ width: "100%", fontSize: ".78em", opacity: .82 }}>
            Updates are verified before installation. Your settings and artworks are kept. Decky restarts briefly after installation; recovery remains available in case of failure.
            {update.last_result ? <div style={{ marginTop: 7 }}>Last result: {updatePhaseLabel(update)}</div> : null}
          </div></PanelSectionRow>
          {!settingsView?<PanelSectionRow><ButtonItem label="Check again"
            description="Final focusable control for controller navigation."
            disabled={updateBusy || update.phase === "ready"} onClick={() => void runUpdateAction(checkForUpdates)}>Check for updates</ButtonItem></PanelSectionRow>:null}
        </PanelSection></SettingsDetails></SettingsPart>
      </> : null}

      {showPage("advanced") && !settingsView ? <FlashProtectionPanel status={status}
        onChange={async (enabled) => setStatus(await setSetting("faceplate_flash_protection_enabled", enabled))} /> : null}

      {showPage("advanced") ? <SettingsPart slot="advanced.diagnostics"><PanelSection title="Troubleshooting">
        <SettingsPart slot="advanced.diagnostics"><PanelSectionRow><ButtonItem label="Export a local diagnostic"
          description="Creates a redacted report on your machine. Nothing is sent automatically."
          disabled={diagnosticBusy} onClick={async () => {
            setDiagnosticBusy(true);
            try {
              const result = await exportDiagnosticReport();
              setConfigurationActionMessage(`Diagnostic saved to ${result.path}`);
            } catch (error) { setConfigurationActionMessage(`Could not export diagnostic: ${String(error)}`); }
            finally { setDiagnosticBusy(false); }
          }}>Export</ButtonItem></PanelSectionRow></SettingsPart>
        {configurationActionMessage?<SettingsPart slot="advanced.diagnostics"><PanelSectionRow><div role="status">{configurationActionMessage}</div></PanelSectionRow></SettingsPart>:null}
      </PanelSection></SettingsPart> : null}

      {showPage("advanced") ? <SettingsPart slot="advanced.support"><PanelSectionRow>
        <ButtonItem label="Capture diagnostics · 5 minutes" description="Enables temporary local capture details. Export a local diagnostic afterwards."
          onClick={() => void enableCaptureDiagnostic().then(()=>setConfigurationActionMessage('Capture details enabled for up to 5 minutes.')).catch(error=>setConfigurationActionMessage(String(error)))}>Enable</ButtonItem>
      </PanelSectionRow></SettingsPart> : null}


      {showPage("advanced") && status.faceplate.available && status.faceplate.native_clock ? <SettingsPart slot="advanced.clock"><Disclosure title="Native clock diagnostics">
        <PanelSectionRow><pre style={{ fontSize: ".72em", whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
          {JSON.stringify({ desired: status.faceplate.routing.desired_scene,
            effective: status.faceplate.routing.effective_scene,
            ...status.faceplate.native_clock }, null, 2)}
        </pre></PanelSectionRow>
      </Disclosure></SettingsPart> : null}
      {showPage("advanced") ? <SettingsPart slot={['advanced.general','advanced.data','advanced.engine']}><PanelSection title={settingsView?undefined:'Advanced'}>
          <SettingsPart slot="advanced.general">
          {settingsView?<PanelSectionRow><ButtonItem label="Guided setup"
            onClick={() => { Navigation.CloseSideMenus(); Navigation.Navigate("/gabecubeaura/setup"); }}>Review my setup</ButtonItem></PanelSectionRow>:null}
          <PanelSectionRow><ToggleField label="Steam control"
            description="On: Steam controls the light bar. Off: restore your GabeCubeAura display. Faceplate stays independent. Off display choices take priority."
            disabled={!status.signalbar_enabled}
            checked={status.steam_control_enabled === true || status.current_display === 'steam'}
            onChange={async (enabled) => setStatus(await setSteamControl(enabled))} /></PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="French interface"
            description="On: French. Off: English. The language choice is saved automatically."
            checked={status.ui_language === "fr"}
            disabled={languageBusy}
            onChange={async (value) => {
              setLanguageBusy(true);
              setLanguageError("");
              try { setStatus(await setSetting("ui_language", value ? "fr" : "en")); }
              catch (error) { setLanguageError(`Could not save the language: ${String(error)}`); }
              finally { setLanguageBusy(false); }
            }}
          />
        </PanelSectionRow>
        {languageError ? <PanelSectionRow><div role="alert">{languageError}</div></PanelSectionRow> : null}
        {!settingsView?<PanelSectionRow>
          <ToggleField
            label="Show technical details"
            checked={showDebug}
            onChange={setShowDebug}
          />
        </PanelSectionRow>:null}
          </SettingsPart>
          <SettingsPart slot="advanced.data">
            <CreationBackupSettings connected={status.faceplate.available} open={openSystemBrowser}/>

            <ConfigurationExportSettings disabled={configurationBusy} onBusyChange={setConfigurationBusy}/>
            <PanelSectionRow><ButtonItem label="Import configuration JSON"
              description="Choose a GabeCubeAura export from Documents or another location. Replaces saved settings and per-game profiles."
              disabled={configurationBusy} onClick={() => void chooseConfigurationFile()}>Import JSON</ButtonItem></PanelSectionRow>
            <PanelSectionRow><ButtonItem label="Reset to defaults"
              description="Complete reset: deletes settings, saved content and the SteamGridDB key. Confirmation required."
              disabled={configurationBusy} onClick={confirmConfigurationReset}>Reset</ButtonItem></PanelSectionRow>
            <PanelSectionRow><ButtonItem label="Reset settings only"
              description="Restore default settings and forget Faceplate setup. Your keys and saved creations are kept; reconnect the Faceplate to set it up again."
              disabled={configurationBusy} onClick={confirmSettingsOnlyReset}>Reset settings</ButtonItem></PanelSectionRow>
            <PanelSectionRow><Localized><div style={{fontSize: '.82em', lineHeight: 1.45}}>
              Settings only keeps your keys and saved creations. Reset to defaults above erases them.
            </div></Localized></PanelSectionRow>
            {configurationActionMessage ? <PanelSectionRow>
              <div style={{ width: "100%", fontSize: ".76em", overflowWrap: "anywhere" }}>
                {configurationActionMessage}
              </div>
            </PanelSectionRow> : null}
          </SettingsPart>
        {showDebug || settingsView?.category==='advanced' ? (
          <>
            <SettingsPart slot="advanced.snapshot">
            <SettingsDetails title="Saved configuration">
            <PanelSectionRow>
              <div style={{ width: "100%", padding: "8px 10px", background: "rgba(0, 0, 0, .24)", borderRadius: 6, overflowWrap: "anywhere" }}>
                <div style={{ fontSize: ".88em", fontWeight: 700 }}>Saved configuration</div>
                <div style={{ fontSize: ".68em", opacity: .7, marginBottom: 6 }}>
                  GabeCubeAura {status.version} · saved choices, including inactive options · no device IDs
                </div>
                {buildSettingsSnapshot(status).map((section) => <div key={section.title} style={{ marginTop: 7 }}>
                  <div style={{ fontSize: ".77em", fontWeight: 700, color: "#9ee8f4" }}>{section.title}</div>
                  {section.lines.map((line, index) => <div key={index} style={{ fontSize: ".72em", lineHeight: 1.25 }}>{line}</div>)}
                </div>)}
              </div>
            </PanelSectionRow>
            </SettingsDetails></SettingsPart>
            <SettingsPart slot="advanced.engine">
            <SettingsDetails title="Engine, games, controllers and weather">
            <PanelSectionRow>
              <div style={{ width: "100%", fontSize: ".76em", opacity: 0.78, overflowWrap: "anywhere" }}>
                <div>LED path: {status.debug.led_path}</div>
                <div>Last LED write: {formatAge(status.debug.last_write_age_s)}</div>
                <div>Total LED writes: {status.debug.writes}</div>
                <div>
                  Render loop: {status.debug.engine_running ? "live" : "stopped"}
                  {` · decision ${formatAge(status.debug.decision_age_s)}`}
                  {status.error ? ` · ${status.error}` : ""}
                </div>
                {status.debug.last_runtime_error ? <div style={{ color: "#ff9a9a" }}>
                  Last runtime fault ({formatAge(status.debug.last_runtime_error_age_s)}): {status.debug.last_runtime_error}
                </div> : null}
                <div>
                  Ownership guard: {status.debug.guard_state === "blocked"
                    ? `blocked · ${status.debug.guard_reason}`
                    : "ready"}
                </div>
                <div>
                  Guard timers: cooldown {status.debug.cooldown_remaining.toFixed(1)} s
                  {" · "}stability {status.debug.stable_remaining.toFixed(1)} s
                </div>
                <div>Last external LED change: {formatAge(status.debug.last_external_age_s)}</div>
                <div>
                  Steam priority: {status.debug.steam_priority
                    ? status.debug.steam_priority_reason || "active"
                    : "inactive"}
                  {status.debug.steam_lease_remaining_s > 0
                    ? ` · lease ${status.debug.steam_lease_remaining_s.toFixed(1)} s`
                    : ""}
                </div>
                <div>
                  Steam download LED mode: {status.debug.steam_led_override_state}
                </div>
                <div>
                  Ownership recovery: {status.debug.last_recovery_age_s == null
                    ? "none"
                    : `${status.debug.last_recovery_reason} · ${formatAge(status.debug.last_recovery_age_s)}`}
                </div>
                {status.debug.launch_handoff_remaining_s > 0 ? <div>
                  Waiting for Steam launch writes: {status.debug.launch_handoff_remaining_s.toFixed(1)} s
                </div> : null}
                <div>
                  Game detection: {status.debug.game_detection_source}
                  {status.debug.game_sync_ms == null ? "" : ` · backend ${Math.round(status.debug.game_sync_ms)} ms`}
                </div>
                <div>
                  Session continuity: {status.debug.game_session_state}
                  {` · retained ${status.debug.game_retained_count} time${status.debug.game_retained_count === 1 ? "" : "s"}`}
                  {status.debug.frontend_heartbeat_age_s == null
                    ? " · no frontend heartbeat"
                    : ` · heartbeat ${formatAge(status.debug.frontend_heartbeat_age_s)}`}
                </div>
                <div>
                  Steam Families callback: {status.debug.parental_callback_state === "waiting"
                    ? `waiting ${status.debug.parental_wait_s?.toFixed(1) ?? "0.0"} s`
                    : status.debug.parental_callback_state === "received"
                      ? `received after ${Math.round(status.debug.parental_callback_delay_ms ?? 0)} ms`
                      : status.debug.parental_callback_state}
                </div>
                <div>
                  Controller data: {status.debug.controller_callback_source}
                  {status.debug.controller_last_update_age_s == null
                    ? " · no reading yet"
                    : ` · ${formatAge(status.debug.controller_last_update_age_s)}`}
                </div>
                <div>Weather: {status.weather.phase} · {status.weather.location?.name ?? "no city"}
                  {status.weather.age_s == null ? "" : ` · updated ${formatAge(status.weather.age_s)}`}
                  {status.weather.error ? ` · ${status.weather.error}` : ""}
                </div>
                <div>
                  SteamInputManager: {status.debug.controller_telemetry?.phase ?? "starting"}
                  {` · hooks ${status.debug.controller_telemetry?.hooks ?? 0}/3 · queries ${status.debug.controller_telemetry?.queries ?? 0} · events ${status.debug.controller_telemetry?.events ?? 0}`}
                  {` · devices ${status.debug.controller_telemetry?.raw_count ?? 0} · query ${status.debug.controller_telemetry?.query_ms ?? "?"} ms`}
                </div>
                {status.debug.controller_telemetry?.devices?.map((device) => <div key={device.index}>
                  {device.name} · input {device.index}: list {device.list_percent ?? "?"}% / SteamUI {device.store_percent ?? "?"}% / event {device.event_percent ?? "?"}%
                  {` → ${device.effective_percent ?? "?"}% · ${device.source}`}
                  {device.event_age_s != null ? ` (${formatAge(device.event_age_s)})` : ""}
                </div>)}
              </div>
            </PanelSectionRow>
            </SettingsDetails></SettingsPart>
            <SettingsPart slot="advanced.general">
            <PanelSectionRow>
              <ToggleField
                label="Reverse physical LED order"
                description="Enabled for the official Steam Machine orientation. Previews stay left-to-right."
                checked={status.reverse_led_order}
                onChange={async (value) => setStatus(await setSetting("reverse_led_order", value))}
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <SliderField
                label="Extra dark LEDs"
                description={status.countdown.active && !status.countdown.alerting
                  ? `Countdown · ${status.countdown.logical_lit} shown in preview → ${status.countdown.physical_lit} lit on hardware.`
                  : status.mode === "performance"
                    ? `Performance · ${status.performance.logical_lit} shown in preview → ${status.performance.physical_lit} lit on hardware.`
                    : "Countdown and Performance only. Artwork is unchanged. Previews keep the logical LED count."}
                value={status.countdown_dark_edge_compensation}
                min={0}
                max={6}
                step={1}
                showValue
                valueSuffix=""
                onChange={async (value) => setStatus(await setSetting("countdown_dark_edge_compensation", value))}
              />
            </PanelSectionRow>
            </SettingsPart>
          </>
        ) : null}
      </PanelSection></SettingsPart> : null}



      {!settingsView && page !== "quick" && page !== "audio-sync" ? <SettingsPageEnd page={page} setStatus={setStatus} /> : null}

    </LedPreviewActivity.Provider>
  );
}

function FaceplateStatePanel({ status }: { status: Status }) {
  const compact=useSettingsPresentation();
  const state = faceplateUXState(status);
  const weather = status.weather;
  return <SettingsPart slot="faceplate.status"><PanelSection title="JSAUX matrix · 64 × 54">
    <PanelSectionRow><div style={{ width: "100%", padding: "10px 12px", borderRadius: 10,
      background: compact ? 'transparent' : state.tone === "good" ? "rgba(71,222,145,.1)" : "rgba(255,190,80,.1)", fontSize: ".84em", lineHeight: 1.5 }}>
      <b>{state.label}</b><div>{state.detail}</div>
      <div style={{ marginTop: 5 }}>Saved at Home: {status.faceplate.routing.routes.home} · In game: {status.faceplate.routing.routes.game}</div>
      {weather.faceplate_weather_state !== "fresh" ? <div>Weather: {weather.faceplate_weather_state === "cached"
        ? `last known · ${formatAge(weather.age_s)}` : weather.faceplate_weather_state === "background-only"
          ? "last known background; readings unavailable" : "readings unavailable"}</div> : null}
    </div></PanelSectionRow>
  </PanelSection></SettingsPart>;
}

function GabeCubeAuraSettings({initialPage}:{initialPage?:SettingsSourcePage}={}) {
  const params=useParams<{source?:string}>();
  const source=initialPage??(params.source&&params.source in SETTINGS_ALIASES?params.source as SettingsSourcePage:undefined);
  const [faceplateConnected,setFaceplateConnected]=useState(()=>retainedStatus?.faceplate.available===true);
  return <SimpleSettings initialSource={source} initial={source?SETTINGS_ALIASES[source]:undefined}
    faceplateConnected={faceplateConnected}
    renderContent={(selection)=><Content key={selection.category} settingsView={selection}
      initialSource={source}
      onFaceplateConnectionChange={setFaceplateConnected}/>}/>;
}

// Existing notifications/bookmarks resolve to the same new interface, never a parallel legacy UI.

export default definePlugin(() => {
  void getStatus().then((status) => setUILanguage(status.ui_language)).catch(actionFailed);
  // Decky invokes this initializer once when it loads the frontend bundle.
  // Runtime signals must start here, not when the user first opens the panel.
  void reportRuntimeDiagnostic("frontend_mounted", 0, "definePlugin", 0)
    .catch(() => undefined);
  const runtime = startGabeCubeAuraRuntime();
  const timerActions = startTimerActions();
  const weatherTopBar = startWeatherTopBar();
  const updateNotifications = startUpdateNotifications();
  routerHook.addRoute(SETTINGS_ROUTE_PATTERN, GabeCubeAuraSettings, {exact:true});
  routerHook.addRoute("/gabecubeaura/setup", FirstRunSetupRoute, { exact: true });
  routerHook.addRoute("/gabecubeaura/setup/faceplate", ()=><FirstRunSetupRoute faceplateOnly/>, {exact:true});
  return {
    name: "GabeCubeAura",
    titleView: <div className={[staticClasses?.Title,'gca-compact-title'].filter(Boolean).join(' ')} style={{ display: 'flex', alignItems: 'center',
      justifyContent: 'space-between', gap: 8, width: '100%', minWidth: 0 }}>
      <style>{QUICK_CONTROL_CSS}</style>
      <span>GabeCubeAura</span>
      <QuickSettingsAction />
    </div>,
    alwaysRender: true,
    content: <QuickAccessContent />,
    icon: <TbCubeSpark />,
    onDismount() {
      void reportRuntimeDiagnostic("frontend_unmounted", 0, "Decky dismount", 0)
        .catch(() => undefined);
      runtime.stop();
      timerActions.stop();
      weatherTopBar.stop();
      updateNotifications.stop();
      routerHook.removeRoute(SETTINGS_ROUTE_PATTERN);
      routerHook.removeRoute("/gabecubeaura/setup");
      routerHook.removeRoute("/gabecubeaura/setup/faceplate");
    },
  };
});
