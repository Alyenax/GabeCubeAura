import {
  ButtonItem,
  ConfirmModal,
  DropdownItem,
  Focusable,
  PanelSection,
  PanelSectionRow,
  Navigation,
  SidebarNavigation,
  SliderField,
  TextField,
  showModal,
  ToggleField,
  staticClasses,
} from "@decky/ui";
import { definePlugin, openFilePicker, routerHook } from "@decky/api";
import { useCallback, useEffect, useRef, useState } from "react";
import { TbCubeSpark } from "react-icons/tb";

import {
  exportConfiguration,
  exportUpdateTestReport,
  checkForUpdates,
  dismissUpdateError,
  disconnectPrivateUpdateAuthorization,
  importConfiguration,
  getArtwork,
  getStatus,
  getUpdateStatus,
  installPreparedUpdate,
  previewCountdown,
  previewCustomization,
  previewLightCalibration,
  previewLaunchArtwork,
  previewAudioSync,
  previewScreenSync,
  previewController,
  previewWeather,
  prepareUpdate,
  pollPrivateUpdateAuthorization,
  resetConfiguration,
  runUpdateLabScenario,
  searchWeatherCities,
  setArtworkSetting,
  setLaunchArtworkSetting,
  setGameDisplay,
  setSetting,
  setUpdatePreferences,
  startPrivateUpdateAuthorization,
  startFreeTimer,
  stopFreeTimer,
  submitArtwork,
  triggerEvent,
} from "./api";
import { sampleArtwork } from "./artwork";
import { PalettePreview } from "./components/PalettePreview";
import { CUSTOMIZATION_PATTERN_OPTIONS, LAUNCH_ARTWORK_PATTERN_OPTIONS, customizationPatternLabel } from "./customization_catalog";
import { CONTROLLER_VARIANTS } from "./controller_variants";
import { EVENT_VARIANTS } from "./event_variants";
import { hslStringToRgb, performancePreview, rgbToHsl } from "./performance";
import { startGabeCubeAuraRuntime } from "./runtime";
import { startUpdateNotifications } from "./update_notifications";
import { buildSettingsSnapshot } from "./settings_snapshot";
import { WEATHER_CONDITIONS, WEATHER_VARIANTS } from "./weather_variants";
import { WEATHER_ICON_STYLE_OPTIONS, weatherIconSvg } from "./weather_icon_sets";
import { startWeatherTopBar } from "./weather_topbar";
import type { ArtworkPayload, ArtworkSource, CompanionPriority, GameDisplay, HomeDisplay, RGB, Status, UpdateLabResult, UpdateStatus, WeatherCondition, WeatherIconStyle, WeatherLocation } from "./types";

const HOME_DISPLAY_OPTIONS: { data: HomeDisplay; label: string }[] = [
  { data: "steam", label: "GabeCubeAura Off" },
  { data: "blackout", label: "Blackout (held off)" },
  { data: "customization", label: "Customization+" },
  { data: "performance", label: "Performance" },
  { data: "audio_sync", label: "Audio Sync" },
  { data: "weather", label: "Weather" },
  { data: "controller", label: "Controller status" },
];

const GAME_DISPLAY_OPTIONS: { data: GameDisplay; label: string }[] = [
  { data: "steam", label: "GabeCubeAura Off" },
  { data: "blackout", label: "Blackout (held off)" },
  { data: "customization", label: "Customization+" },
  { data: "artwork", label: "Artwork" },
  { data: "performance", label: "Performance" },
  { data: "screen_sync", label: "Screen Sync" },
  { data: "audio_sync", label: "Audio Sync" },
  { data: "weather", label: "Weather" },
  { data: "controller", label: "Controller status" },
];

const DISPLAY_PRESET_OPTIONS = [
  { data: "custom", label: "Custom" },
  { data: "lights-out", label: "Lights out" },
  { data: "focus", label: "Focus" },
  { data: "essential", label: "Essential" },
  { data: "moderate", label: "Moderate" },
  { data: "atmosphere", label: "Atmosphere" },
  { data: "signals", label: "Signals" },
  { data: "immersive", label: "Immersive" },
  { data: "immersive-plus", label: "Immersive+" },
  { data: "festive", label: "Festive" },
];

const DISPLAY_PRESET_DESCRIPTIONS: Record<string, string> = {
  custom: "Your detailed routing and animation settings.",
  "lights-out": "Hold all 17 LEDs off except for the Steam Families limit and critical red safety pattern.",
  focus: "Use only Customization+ with the Steam Families limit and critical red safety pattern.",
  essential: "Stay black except for Steam Families, confirmed downloads and the critical red safety pattern.",
  moderate: "Customization+ at Home, Artwork in games, Game launches, Light Events, brief controller alerts and Screen Sync during the Steam screensaver.",
  atmosphere: "Slow Prism with the Screen Sync palette at Home, Artwork in games, Game launches, Light Events, brief controller alerts and Screen Sync during the Steam screensaver.",
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
  downloads: "Keep GabeCubeAura in control except for confirmed Steam downloads and the critical red safety pattern. A reversible Steam LED manager request holds the native Download mode until each transfer ends.",
  critical: "Keep GabeCubeAura in control except for the critical red safety pattern. During confirmed downloads, a reversible Steam LED manager override prevents Download mode from starting when this Steam build exposes the required private service.",
};

const LED_OUTPUT_CALIBRATION_OPTIONS = [
  { data: "consistent", label: "Consistent output (Recommended)" },
  { data: "follow", label: "Follow Steam brightness" },
];

const UPDATE_INTERVAL_OPTIONS = [
  { data: 15, label: "15 minutes" },
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
const COMPANION_PRIORITY_OPTIONS = [
  { data: "stripmine", label: "StripMine while the game is active" },
  { data: "signalbar", label: "GabeCubeAura" },
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
    case "ready": return `Ready to install ${update.available_version}.`;
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
  return <div style={{ width: "100%", display: "flex", justifyContent: "center" }}>
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
  </div>;
}

function PerformanceReadout({ status }: { status: Status }) {
  return <div style={{ width: "100%", fontSize: ".84em" }}>
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
  </div>;
}

function OpaqueColorPickerModal({ title, color, closeModal, onConfirm }: {
  title: string;
  color: RGB;
  closeModal: () => void;
  onConfirm: (color: RGB) => void;
}) {
  const [initialHue, initialSaturation, initialLightness] = rgbToHsl(color);
  const [hue, setHue] = useState(initialHue);
  const [saturation, setSaturation] = useState(initialSaturation);
  const [lightness, setLightness] = useState(initialLightness);
  const selected = hslStringToRgb(`hsl(${hue}, ${saturation}%, ${lightness}%)`) ?? color;
  const canonicalHex = `#${selected.map((channel) => channel.toString(16).padStart(2, "0")).join("").toUpperCase()}`;
  const [hexText, setHexText] = useState(canonicalHex);
  useEffect(() => setHexText(canonicalHex), [canonicalHex]);
  return <ConfirmModal strTitle={title} strOKButtonText="Use colour" strCancelButtonText="Cancel"
    onCancel={closeModal} onOK={() => { onConfirm(selected); closeModal(); }}>
    <div style={{ width: "100%" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <span style={{ width: 38, height: 38, borderRadius: 5,
          background: `rgb(${selected.join(", ")})`, boxShadow: "0 0 0 1px rgba(255,255,255,.45)" }} />
        <span style={{ opacity: .78, fontSize: ".8em" }}>Opaque RGB colour · no alpha channel on the LED hardware.</span>
      </div>
      <TextField label="Hex" value={hexText} description="Exact #RRGGBB colour"
        onChange={(event) => {
          const next = event.currentTarget.value.toUpperCase();
          setHexText(next);
          const match = /^#?([0-9A-F]{6})$/.exec(next);
          if (!match) return;
          const rgb: RGB = [
            parseInt(match[1].slice(0, 2), 16),
            parseInt(match[1].slice(2, 4), 16),
            parseInt(match[1].slice(4, 6), 16),
          ];
          const [nextHue, nextSaturation, nextLightness] = rgbToHsl(rgb);
          setHue(nextHue);
          setSaturation(nextSaturation);
          setLightness(nextLightness);
        }} />
      <SliderField label="Hue" value={hue} min={0} max={360} step={1} showValue
        onChange={setHue} />
      <SliderField label="Saturation" value={saturation} min={0} max={100} step={1} showValue valueSuffix="%"
        onChange={setSaturation} />
      <SliderField label="Lightness" value={lightness} min={0} max={100} step={1} showValue valueSuffix="%"
        onChange={setLightness} />
    </div>
  </ConfirmModal>;
}

function chooseSettingColor(key: string, label: string, color: [number, number, number], setStatus: (value: Status) => void) {
  let modal: ReturnType<typeof showModal> | undefined;
  modal = showModal(<OpaqueColorPickerModal title={label} color={color}
    closeModal={() => modal?.Close()}
    onConfirm={(nextColor) => void setSetting(key, nextColor).then(setStatus).catch(console.warn)} />);
}

function ColorChoice({ label, color, onClick }: {
  label: string;
  color: [number, number, number];
  onClick: () => void;
}) {
  const cssColor = `rgb(${color.join(", ")})`;
  const hexColor = `#${color.map((channel) => channel.toString(16).padStart(2, "0")).join("").toUpperCase()}`;
  return <ButtonItem label={label} description={hexColor} onClick={onClick}>
    <span style={{
      display: "inline-block",
      width: 28,
      height: 28,
      borderRadius: 5,
      background: cssColor,
      boxShadow: "0 0 0 1px rgba(255,255,255,.45)",
    }} />
  </ButtonItem>;
}

function PreciseColorEditor({ label, color, onChange }: {
  label: string;
  color: RGB;
  onChange: (color: RGB) => void;
}) {
  const choose = () => {
    let modal: ReturnType<typeof showModal> | undefined;
    modal = showModal(<OpaqueColorPickerModal title={label} color={color}
      closeModal={() => modal?.Close()} onConfirm={onChange} />);
  };
  return <ColorChoice label={label} color={color} onClick={choose} />;
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
  return <div style={{ width: "100%", fontSize: ".78em", opacity: .84 }}>
    <div>{visible ? `Playing: ${status.events.variant}` : recordingPreview ? "Recording marker active" : "Preview appears here"}</div>
    <PalettePreview colors={visible ? status.events.colors : recordingPreview ? recordingFrame : []} />
  </div>;
}

function CountdownPanel({
  status,
  setStatus,
}: {
  status: Status;
  setStatus: (next: Status) => void;
}) {
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
            <PalettePreview colors={status.countdown.colors} />
            <div style={{ opacity: .7 }}>Live 17-LED countdown preview</div>
          </div>
        </PanelSectionRow>
      </PanelSection> : null}
      <PanelSection title="Playtime countdown">
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
          min={5}
          max={240}
          step={5}
          showValue
          valueSuffix=" min"
          onChange={async (value) => setStatus(await setSetting("free_timer_minutes", value))}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          label="Personal limit"
          description="The timer keeps running when this Decky panel is closed."
          onClick={() => void startFreeTimer(status.free_timer_minutes).then(setStatus).catch(console.warn)}
        >
          Start / restart
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          label="Stop personal limit"
          onClick={() => void stopFreeTimer().then(setStatus).catch(console.warn)}
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
          onClick={() => void previewCountdown().then(setStatus).catch(console.warn)}
        >
          Preview
        </ButtonItem>
      </PanelSectionRow>
      </PanelSection>
    </>
  );
}

function EventsPanel({ status, setStatus }: { status: Status; setStatus: (next: Status) => void }) {
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
      {categories.map(([kind, label, enabledKey, variantKey]) => {
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
                onClick={() => void preview(kind, selected).catch(console.warn)}>Play selected</ButtonItem>
            </PanelSectionRow>
          </PanelSection>
        );
      })}
      <PanelSection title="Recording">
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
          <ButtonItem label={`Preview ${label}`} onClick={() => void preview(kind).catch(console.warn)}>Play</ButtonItem>
        </PanelSectionRow>
      ))}
      </PanelSection>
    </>
  );
}

function ControllersPanel({ status, setStatus }: { status: Status; setStatus: (next: Status) => void }) {
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
      <PanelSectionRow><div style={{ fontSize: ".78em", opacity: .75 }}>
        Select <b>Controller status</b> for Home or In game on the Display routing page to use the permanent gauge. Brief alerts remain independent.
      </div></PanelSectionRow>
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
      <PanelSectionRow><div style={{ fontSize: ".78em", opacity: .75 }}>
        Each detected controller keeps a fixed seat. Two and four controllers use mirrored seats. Three controllers use three left-to-right zones. Separators remain dark and fixed white endpoints appear after the introduction.
      </div></PanelSectionRow>
    </PanelSection>
    <PanelSection title="Controller colours">
      <PanelSectionRow><div style={{ fontSize: ".8em", opacity: .8 }}>
        Automatic uses battery status colours with one controller, then fixed P1 to P4 colours from two controllers. Battery level still controls the length of every gauge. Low-battery and charging signals keep their warning colours, and white highlights stay white.
      </div></PanelSectionRow>
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
    </PanelSection>
    <PanelSection title="Preview setup">
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
    </PanelSection>
    {groups.map(([kind, title, enabledKey, variantKey]) => {
      const selected = status[variantKey];
      const options = CONTROLLER_VARIANTS[kind];
      const detail = options.find((item) => item.data === selected)?.detail ?? "";
      return <PanelSection key={kind} title={title}>
        {kind === "charging" ? <PanelSectionRow><div style={{ fontSize: ".78em", opacity: .78 }}>
          This style is used for the brief signal or the repeating animation, depending on Charging behavior. Preview shows one cycle only.
        </div></PanelSectionRow> : null}
        {enabledKey ? <PanelSectionRow><ToggleField label={`Show ${title.toLowerCase()}`}
          checked={status[enabledKey]}
          onChange={async (value) => setStatus(await setSetting(enabledKey, value))} /></PanelSectionRow> : null}
        <PanelSectionRow><DropdownItem label="Visual style" rgOptions={[...options]}
          selectedOption={selected}
          onChange={async (option) => setStatus(await setSetting(variantKey, String(option.data)))} /></PanelSectionRow>
        <PanelSectionRow><div style={{ fontSize: ".8em", opacity: .78 }}>{detail}</div></PanelSectionRow>
        <PanelSectionRow><div style={{ width: "100%", fontSize: ".78em", opacity: .8 }}>
          {status.controllers.active && status.controllers.kind === kind ? `Playing: ${status.controllers.variant}` : "No preview playing"}
          <PalettePreview colors={status.controllers.active && status.controllers.kind === kind ? status.controllers.colors : []} />
        </div></PanelSectionRow>
        <PanelSectionRow><ButtonItem label={`Preview ${title.toLowerCase()}`}
          description="Uses sample battery data; it does not verify Steam detection. Disabled mode, countdown priority and Steam ownership can prevent LED output."
          onClick={() => void preview(kind, selected).catch(console.warn)}>Play selected</ButtonItem></PanelSectionRow>
      </PanelSection>;
    })}
  </>;
}

function WeatherIconSetPreview({ style }: { style: WeatherIconStyle }) {
  return <div style={{ width: "100%" }}>
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
  </div>;
}

function WeatherPanel({ status, setStatus }: { status: Status; setStatus: (next: Status) => void }) {
  const [cityQuery, setCityQuery] = useState("");
  const [countryQuery, setCountryQuery] = useState("");
  const [cityResults, setCityResults] = useState<WeatherLocation[]>([]);
  const [searching, setSearching] = useState(false);
  const [message, setMessage] = useState("");
  const [previewCondition, setPreviewCondition] = useState<WeatherCondition>("clear_day");
  const variantKey = `weather_${previewCondition}_variant` as keyof Status;
  const selectedVariant = Number(status[variantKey]);
  const currentLabel = WEATHER_CONDITIONS.find((item) => item.data === status.weather.condition)?.label ?? "Unknown";
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
  const playPreview = async (condition: WeatherCondition = previewCondition) => {
    try {
      const variant = Number(status[`weather_${condition}_variant`]);
      const played = await previewWeather(condition, variant);
      setMessage(played ? "One cycle requested. Preview still follows countdown and Steam LED ownership."
        : "Preview unavailable in Disabled mode or during the final five minutes of a countdown.");
      setStatus(await getStatus());
    } catch (error) { setMessage(`Preview failed: ${String(error)}`); }
  };
  return <>
    <PanelSection title="Local weather">
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
        <ButtonItem label={`${city.name}, ${city.country}`} onClick={() => void chooseCity(city)}>Use this city</ButtonItem>
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
      <PanelSectionRow><DropdownItem label="Top-bar temperature unit"
        description="Applies to the number beside the SteamOS clock only, not the LED animations."
        rgOptions={WEATHER_TEMPERATURE_UNITS} selectedOption={status.weather_temperature_unit}
        onChange={async (option) => setStatus(await setSetting("weather_temperature_unit", String(option.data)))} /></PanelSectionRow>
      <PanelSectionRow><div style={{ fontSize: ".78em", opacity: .75 }}>
        Select <b>Weather</b> for Home, In game, or a game override on the Display routing page. Brief alerts and playtime warnings remain independent.
      </div></PanelSectionRow>
      <PanelSectionRow><div style={{ fontSize: ".76em", opacity: .72 }}>
        Current conditions refresh about every 15 minutes. The last reading can be reused for up to one hour; then weather yields the bar. No city, no network request. Data by <a href="https://open-meteo.com/" target="_blank" rel="noreferrer">Open-Meteo</a>.
      </div></PanelSectionRow>
    </PanelSection>
    <PanelSection title="Weather animations">
      <PanelSectionRow><DropdownItem label="Condition to configure" rgOptions={WEATHER_CONDITIONS}
        selectedOption={previewCondition} onChange={(option) => setPreviewCondition(option.data as WeatherCondition)} /></PanelSectionRow>
      <PanelSectionRow><DropdownItem label="Animation" rgOptions={WEATHER_VARIANTS[previewCondition].map((item, index) => ({ data: index, label: item.label }))}
        selectedOption={selectedVariant}
        onChange={async (option) => setStatus(await setSetting(variantKey, Number(option.data)))} /></PanelSectionRow>
      <PanelSectionRow><div style={{ fontSize: ".78em", opacity: .78 }}>
        {WEATHER_VARIANTS[previewCondition][selectedVariant]?.detail}
      </div></PanelSectionRow>
      <PanelSectionRow><ButtonItem label="Preview this animation"
        description="Plays one weather cycle with the selected condition, even before you choose a city. This does not test the weather connection."
        onClick={() => void playPreview()}>Play preview</ButtonItem></PanelSectionRow>
      <PanelSectionRow><div style={{ width: "100%", fontSize: ".78em", opacity: .8 }}>
        {status.weather.preview_active ? "Preview playing" : status.weather.active_here ? "Live weather signal available here" : "No weather signal playing here"}
        <PalettePreview colors={status.weather.colors} />
      </div></PanelSectionRow>
    </PanelSection>
    <PanelSection title="Weather brightness">
      <PanelSectionRow><div style={{ fontSize: ".78em", opacity: .78 }}>
        Brightness scales RGB linearly for all weather animations. Use 100% with cutoff 0 for the unprocessed animation. These controls affect Weather only, not Steam's master LED brightness or other GabeCubeAura modes.
      </div></PanelSectionRow>
      <PanelSectionRow><SliderField label="Weather LED brightness" min={10} max={100} step={5}
        showValue valueSuffix="%" value={status.weather_brightness}
        onChange={async (value) => setStatus(await setSetting("weather_brightness", value))} /></PanelSectionRow>
      <PanelSectionRow><SliderField label="Turn faint LEDs off" min={0} max={60} step={5}
        showValue value={status.weather_shadow_cutoff}
        onChange={async (value) => setStatus(await setSetting("weather_shadow_cutoff", value))} /></PanelSectionRow>
      <PanelSectionRow><div style={{ fontSize: ".76em", opacity: .72 }}>
        Cutoff turns a pixel fully off when its strongest RGB channel is at or below this value (scale from 0 to 255). It does not dim the remaining pixels further. A high cutoff can make transitions more abrupt. These are brightness controls, not measured hardware colour calibration.
      </div></PanelSectionRow>
      <PanelSectionRow><ButtonItem label="Preview night colours"
        description="Play the selected moon-and-stars loop to check the white glow on the physical bar."
        onClick={() => void playPreview("clear_night")}>Play night</ButtonItem></PanelSectionRow>
      <PanelSectionRow><ButtonItem label="Preview warm colours"
        description="Play the selected clear-day loop to check gold and pale sunlight."
        onClick={() => void playPreview("clear_day")}>Play daylight</ButtonItem></PanelSectionRow>
    </PanelSection>
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
          onChange={(color) => void setSetting(key, color).then(setStatus).catch(console.warn)} />
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
      onClick={() => void preview().catch(console.warn)}>Preview</ButtonItem></PanelSectionRow>
    <PanelSectionRow><div style={{ width: "100%", fontSize: ".78em", opacity: .82 }}>
      {status.customization.preview_active ? "Preview playing" : "Live 17-LED preview"}
      <PalettePreview colors={status.customization.colors} />
    </div></PanelSectionRow>
  </PanelSection>;
}

function LightBarCalibration({ status, setStatus }: {
  status: Status;
  setStatus: (next: Status) => void;
}) {
  const calibration = status.led_output_calibration;
  const consistent = status.led_output_calibration_mode === "consistent";
  const detected = calibration.detected_brightness == null
    ? "Waiting for hardware"
    : `${calibration.detected_brightness} / 255`;
  const stage = {
    idle: "Idle",
    "colour-separation": "Colour separation",
    "white-balance": "White balance",
    "motion-contrast": "Motion and contrast",
  }[status.customization.calibration_stage];
  return <PanelSection title="Light bar calibration · Lab">
    <PanelSectionRow><div style={{ fontSize: ".78em", opacity: .82 }}>
      Normalises Valve's global hardware brightness while GabeCubeAura owns the light bar. Pattern brightness remains independent.
    </div></PanelSectionRow>
    <PanelSectionRow><DropdownItem
      label="Output mode"
      description={consistent
        ? "Temporarily uses the GabeCubeAura reference gain, then restores the saved Steam value before Valve takes over."
        : "Keeps Steam's current global brightness. Colours, white balance and contrast may differ from the reference tuning."}
      rgOptions={LED_OUTPUT_CALIBRATION_OPTIONS}
      selectedOption={status.led_output_calibration_mode}
      onChange={async (option) => setStatus(await setSetting("led_output_calibration_mode", String(option.data)))}
    /></PanelSectionRow>
    <PanelSectionRow><div style={{ width: "100%", fontSize: ".77em", lineHeight: 1.45, opacity: .82 }}>
      <div>Steam brightness detected: <b>{detected}</b></div>
      <div>GabeCubeAura Lab reference: <b>{calibration.reference_brightness} / 255</b></div>
      <div>Restored when Steam takes over: <b>Yes</b></div>
      {calibration.saved_steam_brightness != null
        ? <div>Saved Steam brightness: <b>{calibration.saved_steam_brightness} / 255</b></div>
        : null}
      {!calibration.supported && status.available
        ? <div style={{ color: "#ffd27a" }}>This SteamOS LED driver does not expose brightness_scale.</div>
        : null}
      {calibration.startup_recovered
        ? <div style={{ color: "#93f7a7" }}>A brightness value left by an interrupted session was restored safely.</div>
        : null}
    </div></PanelSectionRow>
    <PanelSectionRow><ButtonItem
      label={consistent ? "Preview calibrated output" : "Preview current Steam brightness"}
      description="Runs a 10-second colour separation, white balance and centre-out motion check using the current Audio Sync brightness."
      disabled={!status.signalbar_enabled || !calibration.supported}
      onClick={() => void previewLightCalibration().then(setStatus).catch(console.warn)}>
      Preview for 10 seconds
    </ButtonItem></PanelSectionRow>
    {status.customization.calibration_preview_active ? <PanelSectionRow><div style={{ width: "100%", fontSize: ".78em" }}>
      <div><b>{stage}</b> · {Math.ceil(status.customization.calibration_remaining_s)} s remaining</div>
      <PalettePreview colors={status.customization.colors} />
    </div></PanelSectionRow> : null}
    <PanelSectionRow><div style={{ fontSize: ".73em", opacity: .68 }}>
      Reference {calibration.reference_brightness} is experimental and based on the current physical Steam Machine calibration. Follow Steam brightness remains the default in this Lab.
    </div></PanelSectionRow>
  </PanelSection>;
}

function ScreenSyncPanel({ status, setStatus }: { status: Status; setStatus: (next: Status) => void }) {
  const [showLiveDiagnostics, setShowLiveDiagnostics] = useState(false);
  const activation = status.screen_sync.activation;
  const directGamescopeSelector = status.screen_sync.node_id === null
    && status.screen_sync.capture_selector.includes("Gamescope name");
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
        ? `Capture closed, waiting to rediscover Gamescope${status.screen_sync.error ? `: ${status.screen_sync.error}` : ""}`
      : status.screen_sync.phase === "error"
        ? `Unavailable: ${status.screen_sync.error}`
        : status.current_display === "screen_sync" && status.game.appid > 0
          ? "Waiting for safe LED ownership"
          : "Select Screen Sync as the in-game display or for the current game";
  return <>
    <PanelSection title="Screen Sync">
      <PanelSectionRow><div style={{ fontSize: ".8em", opacity: .82 }}>
        Matches the visible Gamescope picture to the 17-pixel light bar. Frames stay in memory and are never saved or sent over the network.
      </div></PanelSectionRow>
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
        <PalettePreview colors={status.screen_sync.colors} />
      </div></PanelSectionRow> : null}
    </PanelSection>
    <PanelSection title="Activation">
      <PanelSectionRow><ToggleField
        label="Use during Steam screensaver"
        description="Temporarily follows the colours shown by Steam's screensaver. Your Home and in-game displays return when it closes."
        checked={status.screen_sync_screensaver_enabled}
        onChange={async (value) => setStatus(await setSetting("screen_sync_screensaver_enabled", value))} />
      </PanelSectionRow>
      <PanelSectionRow><div style={{ width: "100%", fontSize: ".78em", opacity: .78 }}>
        {showLiveDiagnostics ? <div>{activationLabel}</div> : null}
        <div>In-game default: {displayLabel(status.game_display)}</div>
        {status.display_override !== "inherit" && status.game.appid > 0
          ? <div>Current game override: {displayLabel(status.display_override)}</div>
          : null}
      </div></PanelSectionRow>
      <PanelSectionRow><ButtonItem
        label="Preview Screen Sync"
        description="Uses the real capture and rendering path for 15 seconds without changing Display routing."
        onClick={() => void previewScreenSync().then(setStatus).catch(console.warn)}>
        Preview for 15 seconds
      </ButtonItem></PanelSectionRow>
    </PanelSection>
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
    <PanelSection title="Capture fallback">
      <PanelSectionRow><div style={{ fontSize: ".76em", opacity: .76 }}>
        When Screen Sync pauses for Steam Game Recording or another capture consumer, Customization+ takes over automatically. The centre LED remains red while recording.
      </div></PanelSectionRow>
      {showLiveDiagnostics && status.screen_sync.fallback_active ? <PanelSectionRow><div style={{ fontSize: ".78em" }}>
        Active: {status.screen_sync.fallback_reason}
      </div></PanelSectionRow> : null}
    </PanelSection>
    <PanelSection title="Capture safety">
      <PanelSectionRow>
        <div style={{ fontSize: ".76em", opacity: .74, paddingBottom: 8 }}>
          Screen Sync uses the local Gamescope PipeWire video source at 34 by 18 pixels and 10 frames per second. If Steam Game Recording, screen sharing, or another Gamescope capture consumer is active, capture stops and the fallback is used instead of competing for the stream.
        </div>
      </PanelSectionRow>
    </PanelSection>
  </>;
}

function HifiCrestLab({ status, setStatus, quick = false }: {
  status: Status;
  setStatus: (next: Status) => void;
  quick?: boolean;
}) {
  const [showQuickDiagnostics, setShowQuickDiagnostics] = useState(false);
  return <PanelSection title={quick ? "Hi-Fi Crest Lab" : "Hi-Fi Crest Lab · temporary"}>
    <PanelSectionRow><div style={{ fontSize: ".78em", opacity: .82 }}>
      Live physical calibration. Changes apply immediately. 100% on all three controls reproduces the reference engine.
    </div></PanelSectionRow>
    {quick ? <PanelSectionRow><ToggleField
      label="Show live diagnostics"
      description="Shows Audio Sync timing, latency and analysis queue details. Intended for troubleshooting."
      checked={showQuickDiagnostics}
      onChange={setShowQuickDiagnostics} />
    </PanelSectionRow> : null}
    {quick && showQuickDiagnostics ? <AudioTimingReadout status={status} /> : null}
    <PanelSectionRow><SliderField label="Crest strength"
      description="Controls only the centre-out travelling wave. 0% disables it; 100% is the reference renderer."
      value={status.audio_sync_lab_crest_strength} min={0} max={250} step={5} showValue valueSuffix="%"
      onChange={async (value) => setStatus(await setSetting("audio_sync_lab_crest_strength", value))} /></PanelSectionRow>
    <PanelSectionRow><SliderField label="Edge reach"
      description="Controls how much energy remains when the crest reaches the outer LEDs without changing its travel speed."
      value={status.audio_sync_lab_edge_reach} min={50} max={200} step={5} showValue valueSuffix="%"
      onChange={async (value) => setStatus(await setSetting("audio_sync_lab_edge_reach", value))} /></PanelSectionRow>
    <PanelSectionRow><SliderField label="Background level"
      description="Controls the permanent bass, mid and high visualizer under the crest."
      value={status.audio_sync_lab_background} min={0} max={150} step={5} showValue valueSuffix="%"
      onChange={async (value) => setStatus(await setSetting("audio_sync_lab_background", value))} /></PanelSectionRow>
    {quick ? <PanelSectionRow><ButtonItem label="Preview Audio Sync"
      description="Starts the real system audio path for 15 seconds without changing Display routing."
      onClick={() => void previewAudioSync().then(setStatus).catch(console.warn)}>
      Preview for 15 seconds
    </ButtonItem></PanelSectionRow> : null}
  </PanelSection>;
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
        onChange={(color) => void setSetting(key, color).then(setStatus).catch(console.warn)} />
    </PanelSectionRow>) : null}
    <PanelSectionRow><div style={{ fontSize: ".76em", opacity: .78 }}>
      <b>Recommended shared tuning:</b> {recommended.reactivity[0].toUpperCase() + recommended.reactivity.slice(1)} · Brightness {recommended.brightness} / 255<br />
      {recommended.note}
    </div></PanelSectionRow>
    <PanelSectionRow><ButtonItem label="Apply recommended shared tuning"
      description="Loads the Steam Machine reference response for this pattern. It changes shared reactivity and brightness, but not either context palette."
      onClick={() => void setSetting(styleKey, style).then(setStatus).catch(console.warn)}>
      Apply
    </ButtonItem></PanelSectionRow>
    {palette === "screen-sync" ? <PanelSectionRow><div style={{ fontSize: ".76em", opacity: .74 }}>
      Screen Sync extracts three coherent colours from live Gamescope. Artwork is used when live capture is unavailable. During session changes, the last stable palette is held until a new contextual palette is ready.
    </div></PanelSectionRow> : null}
    {palette === "artwork" ? <PanelSectionRow><div style={{ fontSize: ".76em", opacity: .74 }}>
      Artwork uses the current game's three-colour artwork palette. During session changes, the last stable palette is held until the new artwork palette is ready.
    </div></PanelSectionRow> : null}
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
      Lab renderer: 60 ms quantized frames · physical-bar optical encoder active
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
  const hifiCrestUsed = status.audio_sync_home_style === "hifi-crest" || status.audio_sync_game_style === "hifi-crest";
  return <>
    <PanelSection title="Audio Sync">
      <PanelSectionRow><div style={{ fontSize: ".8em", opacity: .84 }}>
        Turns the mixed system output into a responsive 17-pixel display. Capture and analysis stay local in memory. Audio is never saved or sent over the network.
      </div></PanelSectionRow>
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
        <PalettePreview colors={status.audio_sync.colors} />
        {ADAPTIVE_AUDIO_STYLES.includes(status.audio_sync_style) ? <div>
          Impact {Math.round(status.audio_sync.hifi_metrics.impact * 100)}% · Attack {Math.round(status.audio_sync.hifi_metrics.attack * 100)}% · Texture {Math.round(status.audio_sync.hifi_metrics.texture * 100)}% · Stereo {Math.round(status.audio_sync.hifi_metrics.stereo * 100)}% · Window {status.audio_sync.hifi_metrics.window_s.toFixed(1)} s
        </div> : null}
      </div></PanelSectionRow> : null}
      {showLiveDiagnostics ? <AudioTimingReadout status={status} /> : null}
      <PanelSectionRow><ButtonItem label="Preview Audio Sync"
        description="Uses the real system audio path for 15 seconds without changing Display routing."
        onClick={() => void previewAudioSync().then(setStatus).catch(console.warn)}>
        Preview for 15 seconds
      </ButtonItem></PanelSectionRow>
    </PanelSection>
    <AudioContextMapping context="home" status={status} setStatus={setStatus} />
    <AudioContextMapping context="game" status={status} setStatus={setStatus} />
    <PanelSection title="Shared response">
      <PanelSectionRow><div style={{ fontSize: ".76em", opacity: .78 }}>
        Reactivity and brightness are shared by Home and in-game patterns. Automatic source-level matching stays active for every pattern.
      </div></PanelSectionRow>
      <PanelSectionRow><DropdownItem label="Reactivity" rgOptions={AUDIO_SYNC_REACTIVITY_OPTIONS}
        selectedOption={status.audio_sync_reactivity}
        onChange={async (option) => setStatus(await setSetting("audio_sync_reactivity", String(option.data)))} /></PanelSectionRow>
      <PanelSectionRow><SliderField label="Brightness"
        description="34 is the minimum retained because lower values switch the physical light bar off."
        value={status.audio_sync_brightness} min={34} max={255} step={1} showValue valueSuffix=" / 255"
        onChange={async (value) => setStatus(await setSetting("audio_sync_brightness", value))} /></PanelSectionRow>
    </PanelSection>
    {status.audio_sync_hifi_lab_enabled && hifiCrestUsed
      ? <HifiCrestLab status={status} setStatus={setStatus} />
      : null}
    <PanelSection title="Priority and recovery">
      <PanelSectionRow><ToggleField
        label="Let Steam screensaver take over"
        description="Uses Screen Sync while Steam's screensaver is active, then restores Audio Sync automatically. This is the same option shown on the Screen Sync page."
        checked={status.screen_sync_screensaver_enabled}
        onChange={async (value) => setStatus(await setSetting("screen_sync_screensaver_enabled", value))} />
      </PanelSectionRow>
      <PanelSectionRow><div style={{ fontSize: ".77em", opacity: .8 }}>
        Steam and temporary alerts keep priority. Screensaver Screen Sync pauses Audio Sync, which resumes automatically afterward.
      </div></PanelSectionRow>
      {status.audio_sync_style === "audio-pulse" ? <PanelSectionRow><div style={{ fontSize: ".76em", opacity: .74 }}>
        Audio Pulse applies one global audio envelope to a mirrored three-colour gradient from the selected palette.
      </div></PanelSectionRow> : null}
      {status.audio_sync_style === "bass" ? <PanelSectionRow><div style={{ fontSize: ".76em", opacity: .74 }}>
        Bass pulse mirrors the selected three-colour palette as an edge, shoulder, centre, shoulder, edge gradient. Low-frequency energy remains strongest at the centre and softer toward both edges.
      </div></PanelSectionRow> : null}
      {status.audio_sync_style === "hifi-crest" ? <PanelSectionRow><div style={{ fontSize: ".76em", opacity: .74 }}>
        Hi-Fi Crest places bass impact at the centre, mid attack on both shoulders and high texture at the edges. Stereo balance weights each side, while strong bass onsets launch a restrained centre-out crest.
      </div></PanelSectionRow> : null}
      {EXPERIMENTAL_AUDIO_DESCRIPTIONS[status.audio_sync_style] ? <PanelSectionRow><div style={{ fontSize: ".76em", opacity: .74 }}>
        <b>Experimental optical pattern.</b> {EXPERIMENTAL_AUDIO_DESCRIPTIONS[status.audio_sync_style]}
      </div></PanelSectionRow> : null}
    </PanelSection>
  </>;
}

function CompatibilityPanel({ status, setStatus }: { status: Status; setStatus: (next: Status) => void }) {
  const priorities = ([
    ["Artwork", "stripmine_priority_artwork", "The sampled game artwork display."],
    ["Performance", "stripmine_priority_performance", "CPU, GPU and mixed performance displays."],
    ["Weather", "stripmine_priority_weather", "Permanent and preview weather animations."],
    ["Controller displays", "stripmine_priority_controller", "Battery gauges, connection and charging displays."],
    ["Game launches", "stripmine_priority_game_launches", "Temporary animations using colours from the launched game's artwork."],
    ["Customization+", "stripmine_priority_customization", "The persistent user-authored display."],
    ["Screen Sync", "stripmine_priority_screen_sync", "Live colours captured from the running game."],
    ["Audio Sync", "stripmine_priority_audio_sync", "Live colours driven by the mixed system audio output."],
    ["Light Events", "stripmine_priority_light_events", "Notifications, achievements, screenshots and recording cues."],
  ] as const);
  return <>
    <PanelSection title="TW3-SteamRGB compatibility">
      <PanelSectionRow>
        <ToggleField
          label="Yield to TW3-SteamRGB HUD"
          description="While The Witcher 3 is running, pause GabeCubeAura permanent displays only when TW3-SteamRGB publishes a fresh ownership claim."
          checked={status.tw3_steamrgb_integration_enabled}
          onChange={async (value) => setStatus(await setSetting("tw3_steamrgb_integration_enabled", value))}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <div style={{ width: "100%", fontSize: ".82em", opacity: .86 }}>
          {status.tw3_steamrgb_detected
            ? status.tw3_steamrgb_active
              ? "A live TW3-SteamRGB claim is active. GabeCubeAura keeps temporary alerts available but yields its permanent display."
              : "A live TW3-SteamRGB claim was detected but is being ignored by this setting."
            : status.game.appid === 292030
              ? "The Witcher 3 is running, but no live TW3-SteamRGB claim is detected. GabeCubeAura keeps control."
              : "No live TW3-SteamRGB claim is detected."}
          <div style={{ marginTop: 6, opacity: .72 }}>
            Disable this only when TW3-SteamRGB is absent or for troubleshooting. If another plugin is physically writing to the bar, GabeCubeAura can still yield through its normal Valve and external-owner safety guard.
          </div>
        </div>
      </PanelSectionRow>
    </PanelSection>
    <PanelSection title="StripMine compatibility">
      <PanelSectionRow>
        <ToggleField
          label="Coordinate LED ownership"
          description="GabeCubeAura and StripMine exchange a short local lease before either writes. Unknown applications are still treated as conflicts."
          checked={status.stripmine_integration_enabled}
          onChange={async (value) => setStatus(await setSetting("stripmine_integration_enabled", value))}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <div style={{ width: "100%", fontSize: ".82em", opacity: .86 }}>
          {status.stripmine_detected
            ? "StripMine is active and the ownership link is live."
            : "StripMine is not currently claiming the light bar."}
          <div style={{ marginTop: 6, opacity: .72 }}>
            The selected owner keeps the bar until its output ends. Transfers wait for an acknowledgement, so intentional takeovers do not appear as external conflicts.
          </div>
        </div>
      </PanelSectionRow>
    </PanelSection>
    <PanelSection title="Priority while StripMine is active">
      {priorities.map(([label, key, description]) => <PanelSectionRow key={key}>
        <DropdownItem
          label={label}
          description={description}
          rgOptions={COMPANION_PRIORITY_OPTIONS}
          selectedOption={status[key]}
          onChange={async (option) => setStatus(await setSetting(key, option.data as CompanionPriority))}
        />
      </PanelSectionRow>)}
      <PanelSectionRow>
        <div style={{ width: "100%", fontSize: ".78em", opacity: .75 }}>
          Playtime countdowns and their critical alerts always remain GabeCubeAura priorities. If coordination is disabled, both plugins fall back to their independent ownership guards.
        </div>
      </PanelSectionRow>
    </PanelSection>
  </>;
}

type Page = "quick" | "routing" | "customization" | "artwork" | "performance" | "screen-sync" | "audio-sync" | "launches" | "countdown" | "events" | "controllers" | "weather" | "updates" | "advanced";

const PAGE_END_LABELS: Record<Exclude<Page, "quick">, string> = {
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
      onClick={() => void getStatus().then(setStatus).catch(console.warn)}>
      Refresh status
    </ButtonItem></PanelSectionRow>
  </PanelSection>;
}

function Content({ page = "quick" }: { page?: Page }) {
  const [status, setStatusState] = useState<Status | null>(null);
  const [hero, setHero] = useState<ArtworkPayload | null>(null);
  const [heroRequestKey, setHeroRequestKey] = useState("");
  const [launchHero, setLaunchHero] = useState<ArtworkPayload | null>(null);
  const [launchHeroRequestKey, setLaunchHeroRequestKey] = useState("");
  const artworkRequests = useRef({ artwork: 0, launch: 0 });
  const [showDebug, setShowDebug] = useState(false);
  const [configurationExportPath, setConfigurationExportPath] = useState("");
  const [configurationExportError, setConfigurationExportError] = useState("");
  const [configurationActionMessage, setConfigurationActionMessage] = useState("");
  const [configurationBusy, setConfigurationBusy] = useState(false);
  const [launchPreviewError, setLaunchPreviewError] = useState("");
  const [routingMessage, setRoutingMessage] = useState("");
  const [update, setUpdate] = useState<UpdateStatus | null>(null);
  const [updateBusy, setUpdateBusy] = useState(false);
  const [updateLabResult, setUpdateLabResult] = useState<UpdateLabResult | null>(null);
  const [updateLabReportPath, setUpdateLabReportPath] = useState("");
  const manualTimer = useRef<number | null>(null);
  const artworkVibranceTimer = useRef<number | null>(null);
  const setStatus = (next: Status) => {
    setStatusState(next);
  };

  useEffect(() => {
    let alive = true;
    void getStatus().then((next) => alive && setStatus(next)).catch(console.warn);
    const timer = window.setInterval(() => {
      void getStatus().then((next) => alive && setStatus(next)).catch(() => undefined);
    }, page === "events" || page === "controllers" || page === "weather"
      || page === "launches" ? 100
      : page === "screen-sync" || page === "audio-sync" ? 250 : 1000);
    return () => {
      alive = false;
      window.clearInterval(timer);
      if (manualTimer.current != null) window.clearTimeout(manualTimer.current);
      if (artworkVibranceTimer.current != null) window.clearTimeout(artworkVibranceTimer.current);
    };
  }, [page]);

  useEffect(() => {
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
  }, [page]);

  useEffect(() => {
    if (page !== "updates" || update?.private_auth_state !== "pending") return;
    let alive = true;
    let inFlight = false;
    const poll = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const next = await pollPrivateUpdateAuthorization();
        if (alive) setUpdate(next);
      } catch (error) {
        console.warn("[GabeCubeAura] private authorization poll failed", error);
      } finally {
        inFlight = false;
      }
    };
    const timer = window.setInterval(() => void poll(), 5000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [page, update?.private_auth_state]);

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
    const artwork = await getArtwork(appid, source, purpose);
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
      void Promise.all([
        loadAndSampleArtwork(next.game.appid, next.artwork_source, "artwork"),
        loadAndSampleArtwork(next.game.appid, next.launch_artwork_source, "launch"),
      ]).catch(console.warn);
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

  const confirmConfigurationReset = () => {
    let modal: ReturnType<typeof showModal> | undefined;
    modal = showModal(<ConfirmModal strTitle="Reset GabeCubeAura settings?"
      strDescription="All saved settings and per-game profiles will return to the shipped defaults. The personal timer stops. Export a JSON backup first if you want to restore them later."
      strOKButtonText="Reset settings" strCancelButtonText="Cancel" bDestructiveWarning
      onCancel={() => modal?.Close()}
      onOK={() => {
        modal?.Close();
        setConfigurationBusy(true);
        setConfigurationActionMessage("");
        void resetConfiguration().then((next) => {
          setStatus(next);
          refreshArtworkAfterConfiguration(next);
          setConfigurationActionMessage("Settings and per-game profiles reset to GabeCubeAura defaults.");
        }).catch((error) => {
          setConfigurationActionMessage(`Reset failed: ${String(error)}`);
        }).finally(() => setConfigurationBusy(false));
      }} />);
  };

  useEffect(() => {
    if (!status) return;
    const contextualAudioPalette = ADAPTIVE_AUDIO_STYLES.includes(status.audio_sync_style)
      && ["screen-sync", "artwork"].includes(status.audio_sync_palette);
    const needsArtwork = page === "artwork" || page === "launches"
      || (page === "quick" && status.current_display === "artwork")
      || contextualAudioPalette && (page === "audio-sync" || status.current_display === "audio_sync");
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
  if (!status.available) {
    return (
      <PanelSection title="GabeCubeAura">
        <PanelSectionRow>
          <div style={{ fontSize: ".88em", opacity: 0.82 }}>
            No 17-pixel <code>valve-leds</code> light bar was found. GabeCubeAura is idle and has made no hardware changes.
            {status.error ? <div style={{ marginTop: 6 }}>{status.error}</div> : null}
          </div>
        </PanelSectionRow>
      </PanelSection>
    );
  }

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
  const baseShownColors = status.provider.startsWith("launch-artwork:") ? status.launch_artwork.colors
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
  const shownLabel = status.provider.startsWith("launch-artwork:")
    ? `Game launch · ${LAUNCH_ARTWORK_PATTERN_OPTIONS.find((item) => item.data === status.launch_artwork_pattern)?.label ?? status.launch_artwork_pattern}`
    : status.provider.startsWith("screen-sync") ? "Screen Sync"
    : status.provider.startsWith("audio-sync") ? "Audio Sync"
    : status.provider.startsWith("customization:") ? `Customization+ · ${customizationPatternLabel(status.customization_pattern)}`
    : status.provider.startsWith("event:") ? status.events.variant
    : status.provider.startsWith("controller:") ? `Controller · ${status.controllers.variant}`
      : status.provider === "controller-battery" ? "Controller battery"
      : status.provider === "controller-charging" ? "Controller charging"
      : status.provider === "controller-charge-complete" ? "Controller fully charged"
      : status.provider.startsWith("weather") ? `Weather · ${status.weather.location?.name ?? "preview"}`
    : status.provider === "countdown" ? status.countdown.label
      : status.provider === "blackout" ? "Blackout · LEDs held off"
      : status.provider === "valve" ? "Steam / another app"
        : status.provider === "none" ? "No GabeCubeAura output" : status.provider;
  const showPage = (target: Page) => page === target;

  const runUpdateAction = async (action: () => Promise<UpdateStatus>) => {
    setUpdateBusy(true);
    try {
      setUpdate(await action());
    } catch (error) {
      console.warn("[GabeCubeAura] update action failed", error);
      setUpdate(await getUpdateStatus());
    } finally {
      setUpdateBusy(false);
    }
  };

  const confirmUpdateInstall = () => {
    if (!update?.confirmation_token || !update.available_version) return;
    const token = update.confirmation_token;
    const target = update.available_version;
    let modal: ReturnType<typeof showModal> | undefined;
    modal = showModal(<ConfirmModal strTitle="Update GabeCubeAura?"
      strDescription={`Update from ${update.installed_version} to ${target}? The downloaded package passed its checksum and package checks. Your settings and artwork cache will be kept. Decky will restart briefly.`}
      strOKButtonText="Update and restart Decky" strCancelButtonText="Cancel"
      onCancel={() => modal?.Close()}
      onOK={() => {
        modal?.Close();
        setUpdateBusy(true);
        void installPreparedUpdate(token).catch((error) => {
          console.warn("[GabeCubeAura] update installation failed", error);
          setUpdateBusy(false);
          void getUpdateStatus().then(setUpdate).catch(console.warn);
        });
      }} />);
  };

  const runUpdateLab = async (scenario: UpdateLabResult["scenario"]) => {
    setUpdateBusy(true);
    setUpdateLabReportPath("");
    try {
      setUpdateLabResult(await runUpdateLabScenario(scenario));
    } catch (error) {
      setUpdateLabResult({
        scenario,
        passed: false,
        started_at: 0,
        finished_at: 0,
        details: String(error),
        report_available: false,
      });
    } finally {
      setUpdateBusy(false);
    }
  };

  return (
    <>
      {page === "quick" ? <PanelSection title="Status">
        <PanelSectionRow>
          <div style={{ width: "100%", fontSize: ".88em", lineHeight: 1.45 }}>
            <div><b>{status.active ? "Active" : "Suspended"}</b> · owner: {status.owner}</div>
            <div>Provider: {status.provider}</div>
            {status.game.appid > 0 || status.game.title ? (
              <div>{status.game.title || "Running game"} · AppID {status.game.appid || "unknown"}</div>
            ) : <div>No game running</div>}
            {status.suspension_reason ? <div style={{ opacity: 0.72 }}>{status.suspension_reason}</div> : null}
          </div>
        </PanelSectionRow>
      </PanelSection> : null}

      {page === "quick" && update?.phase === "available" ? <PanelSection title="Software update">
        <PanelSectionRow>
          <ButtonItem label={`Update available: ${update.available_version}`}
            description="Review the release notes and package checks before installing."
            onClick={() => { Navigation.CloseSideMenus(); Navigation.Navigate("/gabecubeaura/settings/updates"); }}>
            Review update
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection> : null}

      {page === "quick" ? <PanelSection title="Permanent displays">
        <PanelSectionRow><ToggleField label="Enable GabeCubeAura"
          checked={status.signalbar_enabled}
          onChange={async (value) => setStatus(await setSetting("signalbar_enabled", value))} /></PanelSectionRow>
        {status.game.appid > 0 ? <>
          <PanelSectionRow><DropdownItem label="Display for this game"
            description={`Saved for ${status.game.title || `AppID ${status.game.appid}`}. Does not change other games.`}
            rgOptions={[{ data: "inherit", label: "Use in-game default" }, ...GAME_DISPLAY_OPTIONS]}
            selectedOption={status.display_override}
            onChange={async (option) => setStatus(await setGameDisplay(status.game.appid, String(option.data)))} /></PanelSectionRow>
          <PanelSectionRow><div style={{ fontSize: ".78em", opacity: .75 }}>
            {!status.signalbar_enabled ? "GabeCubeAura is disabled. The saved game choice will apply when re-enabled."
              : `Active display: ${displayLabel(status.current_display)}${status.display_override === "inherit" ? " (in-game default)" : " (game profile)"}. Temporary signals keep their own priority.`}
          </div></PanelSectionRow>
        </> : null}
      </PanelSection> : null}

      {page === "quick" ? <PanelSection title="Now showing">
        <PanelSectionRow>
          <div style={{ width: "100%", fontSize: ".84em" }}>
            <div><b>{shownLabel}</b></div>
            {status.game.title ? <div>{status.game.title}</div> : null}
            {status.provider.startsWith("controller") && status.controllers.controllers.length ? <div style={{ marginTop: 5 }}>
              {status.controllers.controllers.map((controller) =>
                `${controller.name} ${controllerChargeLabel(controller)}`).join(" · ")}
            </div> : null}
            {status.provider.startsWith("weather") ? <div style={{ marginTop: 5 }}>
              {WEATHER_CONDITIONS.find((item) => item.data === status.weather.condition)?.label ?? "Current weather"}
            </div> : null}
            {status.provider.startsWith("performance") ? <div style={{ marginTop: 7 }}>
              <div style={{ marginBottom: 4, fontSize: ".92em", opacity: .72 }}>Performance sensors</div>
              <PerformanceReadout status={status} />
            </div> : null}
            {status.provider.startsWith("artwork") && status.game.appid > 0 ? <div style={{ marginTop: 8 }}>
              <div style={{ marginBottom: 6, opacity: .76 }}>
                Game artwork{currentArtwork?.source_label ? ` · ${currentArtwork.source_label}` : ""}
              </div>
              {currentArtwork ? <ArtworkImage artwork={currentArtwork} title={status.game.title || "current game"} compact />
                : <div style={{ opacity: .65 }}>No game artwork available yet.</div>}
            </div> : null}
            <PalettePreview colors={shownColors} />
            <div style={{ opacity: .65 }}>17-LED logical preview</div>
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem label="Detailed settings" onClick={() => { Navigation.CloseSideMenus(); Navigation.Navigate("/gabecubeaura/settings"); }}>
            Open settings
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection> : null}

      {page === "quick" && status.audio_sync_hifi_lab_enabled && status.audio_sync_style === "hifi-crest"
        ? <HifiCrestLab status={status} setStatus={setStatus} quick />
        : null}

      {showPage("routing") ? <>
        <PanelSection title="Display routing">
          <PanelSectionRow><ToggleField label="Enable GabeCubeAura"
            description="Turns off every GabeCubeAura light without deleting display routes, launch effects, or per-game choices."
            checked={status.signalbar_enabled}
            onChange={async (value) => setStatus(await setSetting("signalbar_enabled", value))} /></PanelSectionRow>
          <PanelSectionRow><DropdownItem label="Lighting preset"
            description={DISPLAY_PRESET_DESCRIPTIONS[status.display_preset] ?? DISPLAY_PRESET_DESCRIPTIONS.custom}
            rgOptions={DISPLAY_PRESET_OPTIONS} selectedOption={status.display_preset}
            onChange={(option) => void applyDisplayPreset(String(option.data))} /></PanelSectionRow>
          {routingMessage ? <PanelSectionRow><div style={{ fontSize: ".78em", color: "#ffd27a" }}>
            {routingMessage}
          </div></PanelSectionRow> : null}
          <PanelSectionRow><DropdownItem label="Steam ownership"
            description={VALVE_OWNERSHIP_DESCRIPTIONS[status.valve_ownership_policy] ?? VALVE_OWNERSHIP_DESCRIPTIONS.cooperative}
            rgOptions={VALVE_OWNERSHIP_OPTIONS} selectedOption={status.valve_ownership_policy}
            onChange={async (option) => setStatus(await setSetting("valve_ownership_policy", String(option.data)))} /></PanelSectionRow>
          <PanelSectionRow><div style={{ fontSize: ".76em", opacity: .78 }}>
            The critical red exception is detected from the physical LED pattern because Steam exposes no public semantic thermal-warning signal. It is a conservative best-effort safeguard, not a guaranteed source identification.
          </div></PanelSectionRow>
          <PanelSectionRow><DropdownItem label="Home display"
            description="The permanent display used when no game is running. Temporary alerts and previews may still replace it."
            rgOptions={HOME_DISPLAY_OPTIONS} selectedOption={status.home_display}
            onChange={async (option) => setStatus(await setSetting("home_display", String(option.data)))} /></PanelSectionRow>
          <PanelSectionRow><DropdownItem label="In-game display"
            description="The permanent display used by games without their own override."
            rgOptions={GAME_DISPLAY_OPTIONS} selectedOption={status.game_display}
            onChange={async (option) => setStatus(await setSetting("game_display", String(option.data)))} /></PanelSectionRow>
          <PanelSectionRow><div style={{ fontSize: ".78em", opacity: .75 }}>
            <b>GabeCubeAura Off</b> releases the permanent display to Steam. <b>Blackout</b> actively holds all 17 LEDs off while keeping GabeCubeAura ownership. Temporary GabeCubeAura layers still follow the selected preset. The master switch releases everything. Weather requires a city.
          </div></PanelSectionRow>
        </PanelSection>
        <LightBarCalibration status={status} setStatus={setStatus} />
        {status.game.appid > 0 ? <PanelSection title="Current game override">
          <PanelSectionRow><DropdownItem label={status.game.title || `AppID ${status.game.appid}`}
            description="Saved for this AppID only."
            rgOptions={[{ data: "inherit", label: "Use in-game default" }, ...GAME_DISPLAY_OPTIONS]}
            selectedOption={status.display_override}
            onChange={async (option) => setStatus(await setGameDisplay(status.game.appid, String(option.data)))} /></PanelSectionRow>
        </PanelSection> : null}
      </> : null}

      {showPage("customization") ? <CustomizationPanel status={status} setStatus={setStatus} /> : null}

      {showPage("screen-sync") ? <ScreenSyncPanel status={status} setStatus={setStatus} /> : null}

      {showPage("audio-sync") ? <AudioSyncPanel status={status} setStatus={setStatus} /> : null}

      {showPage("artwork") ? <PanelSection title="Artwork display">
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
            {status.game.title || (status.game.appid > 0 ? `AppID ${status.game.appid}` : "No game selected")}
            {currentArtwork?.source_label ? ` · ${currentArtwork.source_label}` : ""}
            {status.artwork.sample_y != null ? ` · row ${Math.round(status.artwork.sample_y * 100)}%` : ""}
            <PalettePreview colors={artColors} />
          </div>
        </PanelSectionRow>
      </PanelSection> : null}

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
                  void setLaunchArtworkSetting(status.game.appid, "custom_palettes", palettes).then(setStatus).catch(console.warn);
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
          <PalettePreview colors={status.launch_artwork.colors ?? []} />
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
            <PalettePreview colors={performanceColors} />
          </div>
        </PanelSectionRow>
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
      </PanelSection> : null}

      {showPage("countdown") ? <CountdownPanel status={status} setStatus={setStatus} /> : null}

      {showPage("events") ? <EventsPanel status={status} setStatus={setStatus} /> : null}

      {showPage("controllers") ? <ControllersPanel status={status} setStatus={setStatus} /> : null}

      {showPage("weather") ? <WeatherPanel status={status} setStatus={setStatus} /> : null}

      {showPage("updates") && update ? <>
        <PanelSection title="Software updates">
          <PanelSectionRow><div style={{ width: "100%", fontSize: ".82em", lineHeight: 1.45 }}>
            <div>Installed version: <b>{update.installed_version}</b></div>
            <div>{update.channel === "stable" ? "Latest stable version" : update.channel === "beta" ? "Latest beta or stable version" : "Latest private lab version"}: <b>{update.available_version || update.installed_version}</b></div>
            <div>Current status: <b>{updatePhaseLabel(update)}</b></div>
            <div>Last checked: {formatUpdateDate(update.last_checked_at)}</div>
            {update.prepared_digest ? <div>Verified SHA256: <code>{update.prepared_digest.slice(0, 12)}...</code></div> : null}
            {update.test_build ? <div style={{ marginTop: 6, color: "#ffd166", fontWeight: 700 }}>TEST BUILD</div> : null}
          </div></PanelSectionRow>
          <PanelSectionRow><ButtonItem label="Check for updates"
            disabled={updateBusy || ["checking", "downloading", "verifying", "ready", "installing", "restart_pending"].includes(update.phase)}
            onClick={() => void runUpdateAction(checkForUpdates)}>Check now</ButtonItem></PanelSectionRow>
          {update.release_url ? <PanelSectionRow><ButtonItem label="View release notes"
            description={`Opens the selected ${update.channel === "private" ? "private Lab" : "public GabeCubeAura"} release page.`}
            onClick={() => Navigation.NavigateToExternalWeb(update.release_url)}>Open GitHub</ButtonItem></PanelSectionRow> : null}
          {update.phase === "available" ? <PanelSectionRow><ButtonItem label="Download update"
            description="Downloads and checks the archive. Nothing is installed yet."
            disabled={updateBusy} onClick={() => void runUpdateAction(prepareUpdate)}>Download and verify</ButtonItem></PanelSectionRow> : null}
          {update.phase === "ready" ? <PanelSectionRow><ButtonItem label={`Install ${update.available_version}`}
            description="Settings and artwork caches are kept. Decky restarts briefly."
            disabled={updateBusy} onClick={confirmUpdateInstall}>Update and restart Decky</ButtonItem></PanelSectionRow> : null}
          {update.release_notes ? <PanelSectionRow><div style={{ width: "100%", fontSize: ".76em", opacity: .8, whiteSpace: "pre-wrap", maxHeight: 180, overflow: "hidden" }}>
            {update.release_notes}
          </div></PanelSectionRow> : null}
          {update.phase === "error" ? <PanelSectionRow><ButtonItem label="Dismiss update error"
            onClick={() => void runUpdateAction(dismissUpdateError)}>Dismiss</ButtonItem></PanelSectionRow> : null}
        </PanelSection>
        {update.channel === "private" ? <PanelSection title="Private Lab access">
          <PanelSectionRow><div style={{ width: "100%", fontSize: ".78em", opacity: .84, lineHeight: 1.45 }}>
            <div>Repository: <b>{update.private_repository}</b></div>
            <div>GitHub access: <b>{update.private_auth_state === "connected" ? "Connected" : update.private_auth_state === "pending" ? "Waiting for authorization" : "Not connected"}</b></div>
            <div style={{ marginTop: 5 }}>The plugin requests read-only access through a GitHub device code. No password or client secret is stored in GabeCubeAura.</div>
          </div></PanelSectionRow>
          {update.private_auth_state !== "connected" && update.private_auth_state !== "pending" ? <PanelSectionRow><ButtonItem
            label="Connect GitHub"
            description="Creates a short-lived code for github.com/login/device."
            disabled={updateBusy || !update.private_auth_configured}
            onClick={() => void runUpdateAction(startPrivateUpdateAuthorization)}>
            Generate code
          </ButtonItem></PanelSectionRow> : null}
          {update.private_auth_state === "pending" ? <>
            <PanelSectionRow><div style={{ width: "100%", padding: "8px 0", textAlign: "center" }}>
              <div style={{ fontSize: ".75em", opacity: .72 }}>Enter this code on GitHub</div>
              <div style={{ fontSize: "1.45em", fontWeight: 800, letterSpacing: ".14em", marginTop: 4 }}>{update.private_user_code}</div>
              <div style={{ fontSize: ".72em", opacity: .66, marginTop: 4 }}>Expires {formatUpdateDate(update.private_auth_expires_at)}</div>
            </div></PanelSectionRow>
            <PanelSectionRow><ButtonItem label="Open GitHub device authorization"
              description="Opens GitHub in the browser. Enter the code shown above."
              onClick={() => Navigation.NavigateToExternalWeb(update.private_verification_uri || "https://github.com/login/device")}>Open GitHub</ButtonItem></PanelSectionRow>
            <PanelSectionRow><ButtonItem label="I authorized this device"
              description="Detection is automatic. Use this to check immediately."
              disabled={updateBusy}
              onClick={() => void runUpdateAction(pollPrivateUpdateAuthorization)}>Finish connection</ButtonItem></PanelSectionRow>
          </> : null}
          {update.private_auth_state === "connected" ? <PanelSectionRow><ButtonItem
            label="Disconnect Private Lab"
            description="Deletes the locally stored GitHub access and refresh tokens."
            disabled={updateBusy}
            onClick={() => void runUpdateAction(disconnectPrivateUpdateAuthorization)}>
            Disconnect
          </ButtonItem></PanelSectionRow> : null}
          {!update.private_auth_configured ? <PanelSectionRow><div style={{ fontSize: ".76em", color: "#ffb3b3" }}>
            This build does not yet contain the GitHub App client ID.
          </div></PanelSectionRow> : null}
        </PanelSection> : null}
        <PanelSection title="Automatic checks">
          <PanelSectionRow><ToggleField label="Automatically check for updates"
            description="Checks the selected Alyenax release channel at this interval. Nothing is installed without your confirmation."
            checked={update.auto_check} onChange={(value) => void runUpdateAction(() => setUpdatePreferences(value, update.notifications, update.check_interval_minutes, update.channel))} /></PanelSectionRow>
          <PanelSectionRow><DropdownItem label="Check interval"
            description="How often GabeCubeAura checks automatically. Manual checks remain available."
            disabled={!update.auto_check || updateBusy}
            rgOptions={UPDATE_INTERVAL_OPTIONS} selectedOption={update.check_interval_minutes}
            onChange={(option) => void runUpdateAction(() => setUpdatePreferences(update.auto_check, update.notifications, Number(option.data), update.channel))} /></PanelSectionRow>
          <PanelSectionRow><DropdownItem label="Update channel"
            description={update.channel === "stable"
              ? "Stable releases only."
              : update.channel === "beta"
                ? "Beta releases and later stable releases. Installation still requires confirmation."
                : "Private hardware-lab releases from Alyenax/GabeCubeAura-Lab. GitHub authorization is required."}
            disabled={updateBusy || ["downloading", "verifying", "ready", "installing", "restart_pending"].includes(update.phase)}
            rgOptions={UPDATE_CHANNEL_OPTIONS} selectedOption={update.channel}
            onChange={(option) => void runUpdateAction(() => setUpdatePreferences(update.auto_check, update.notifications, update.check_interval_minutes, String(option.data) as "stable" | "beta" | "private"))} /></PanelSectionRow>
          <PanelSectionRow><ToggleField label="Notify me when an update is available"
            description="Shows one Decky notification for each new version on the selected channel."
            checked={update.notifications} onChange={(value) => void runUpdateAction(() => setUpdatePreferences(update.auto_check, value, update.check_interval_minutes, update.channel))} /></PanelSectionRow>
        </PanelSection>
        <PanelSection title="Installation safety">
          <PanelSectionRow><div style={{ width: "100%", fontSize: ".78em", opacity: .82 }}>
            Updates are downloaded from the selected Alyenax repository and checked before installation. Private Lab credentials are stored separately from exported settings. Settings and artwork caches are kept. Decky restarts briefly after an update.
            {update.last_result ? <div style={{ marginTop: 7 }}>Last result: {updatePhaseLabel(update)}</div> : null}
          </div></PanelSectionRow>
          <PanelSectionRow><ButtonItem label="Check again"
            description="Final focusable control for controller navigation."
            disabled={updateBusy || update.phase === "ready"} onClick={() => void runUpdateAction(checkForUpdates)}>Check for updates</ButtonItem></PanelSectionRow>
        </PanelSection>
      </> : null}

      {showPage("advanced") ? <CompatibilityPanel status={status} setStatus={setStatus} /> : null}

      {showPage("advanced") ? <PanelSection title="Advanced / debug">
        <PanelSectionRow>
          <ToggleField
            label="Show Hi-Fi Crest Lab"
            description="Shows the physical calibration controls in the Decky tab and Audio Sync settings when Hi-Fi Crest is selected."
            checked={status.audio_sync_hifi_lab_enabled}
            onChange={async (value) => setStatus(await setSetting("audio_sync_hifi_lab_enabled", value))}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="Show debug details"
            checked={showDebug}
            onChange={setShowDebug}
          />
        </PanelSectionRow>
        {showDebug ? (
          <>
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
            <PanelSectionRow>
              <ButtonItem
                label="Export configuration JSON"
                description={configurationExportPath
                  ? `Saved to ${configurationExportPath}`
                  : "Write a readable copy to Documents when available; the exact path appears here."}
                onClick={() => void exportConfiguration()
                  .then((result) => {
                    setConfigurationExportPath(result.path);
                    setConfigurationExportError("");
                  })
                  .catch((error) => {
                    console.warn("[GabeCubeAura] configuration export failed", error);
                    setConfigurationExportError(error instanceof Error ? error.message : String(error));
                  })}
              >Export JSON</ButtonItem>
            </PanelSectionRow>
            {configurationExportError ? <PanelSectionRow>
              <div style={{ width: "100%", fontSize: ".76em", color: "#ff9e9e", overflowWrap: "anywhere" }}>
                Export failed: {configurationExportError}
              </div>
            </PanelSectionRow> : null}
            <PanelSectionRow><ButtonItem label="Import configuration JSON"
              description="Choose a GabeCubeAura export from Documents or another location. Replaces saved settings and per-game profiles."
              disabled={configurationBusy} onClick={() => void chooseConfigurationFile()}>Import JSON</ButtonItem></PanelSectionRow>
            <PanelSectionRow><ButtonItem label="Reset to defaults"
              description="Return to the shipped settings, clear per-game profiles and stop the personal timer. Confirmation required."
              disabled={configurationBusy} onClick={confirmConfigurationReset}>Reset</ButtonItem></PanelSectionRow>
            {configurationActionMessage ? <PanelSectionRow>
              <div style={{ width: "100%", fontSize: ".76em", overflowWrap: "anywhere" }}>
                {configurationActionMessage}
              </div>
            </PanelSectionRow> : null}
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
          </>
        ) : null}
      </PanelSection> : null}

      {showPage("advanced") && update?.test_build ? <PanelSection title="Update lab · TEST BUILD">
        <PanelSectionRow><div style={{ width: "100%", fontSize: ".78em", opacity: .84 }}>
          These fixtures use isolated directories. They never replace the installed plugin or restart the real Decky service.
        </div></PanelSectionRow>
        <PanelSectionRow><ButtonItem label="Valid package"
          description="Build and validate a fixed local GabeCubeAura 1.1.0 fixture."
          disabled={updateBusy} onClick={() => void runUpdateLab("valid-package")}>Run validation only</ButtonItem></PanelSectionRow>
        <PanelSectionRow><ButtonItem label="Checksum mismatch"
          description="Confirm that a wrong SHA256 is rejected before staging."
          disabled={updateBusy} onClick={() => void runUpdateLab("checksum-mismatch")}>Run rejection test</ButtonItem></PanelSectionRow>
        <PanelSectionRow><ButtonItem label="Rollback rehearsal"
          description="Install a broken fixture in isolated directories and restore the previous fixture."
          disabled={updateBusy} onClick={() => void runUpdateLab("rollback")}>Rehearse rollback</ButtonItem></PanelSectionRow>
        {updateLabResult ? <PanelSectionRow><div style={{ width: "100%", fontSize: ".78em", color: updateLabResult.passed ? "#9ee8b0" : "#ff9e9e" }}>
          <b>{updateLabResult.passed ? "Passed" : "Failed"}: {updateLabResult.scenario}</b>
          <div style={{ marginTop: 4, opacity: .86 }}>{updateLabResult.details}</div>
        </div></PanelSectionRow> : null}
        <PanelSectionRow><ButtonItem label="Export test report"
          description={updateLabReportPath || "Writes the bounded fixture report to Documents."}
          disabled={updateBusy || !updateLabResult?.report_available}
          onClick={() => void exportUpdateTestReport().then((result) => setUpdateLabReportPath(result.path)).catch((error) => setUpdateLabReportPath(String(error)))}>
          Export JSON
        </ButtonItem></PanelSectionRow>
      </PanelSection> : null}

      {page !== "quick" && page !== "audio-sync" ? <SettingsPageEnd page={page} setStatus={setStatus} /> : null}

    </>
  );
}

function GabeCubeAuraSettings() {
  return <SidebarNavigation title="GabeCubeAura settings" pages={[
    { title: "Display routing", route: "/gabecubeaura/settings/routing", content: <Content page="routing" /> },
    { title: "Customization+", route: "/gabecubeaura/settings/customization", content: <Content page="customization" /> },
    { title: "Artwork", route: "/gabecubeaura/settings/artwork", content: <Content page="artwork" /> },
    { title: "Performance", route: "/gabecubeaura/settings/performance", content: <Content page="performance" /> },
    { title: "Game launches", route: "/gabecubeaura/settings/launches", content: <Content page="launches" /> },
    { title: "Playtime", route: "/gabecubeaura/settings/countdown", content: <Content page="countdown" /> },
    { title: "Light events", route: "/gabecubeaura/settings/events", content: <Content page="events" /> },
    { title: "Controllers", route: "/gabecubeaura/settings/controllers", content: <Content page="controllers" /> },
    { title: "Weather", route: "/gabecubeaura/settings/weather", content: <Content page="weather" /> },
    { title: "Screen Sync", route: "/gabecubeaura/settings/screen-sync", content: <Content page="screen-sync" /> },
    { title: "Audio Sync", route: "/gabecubeaura/settings/audio-sync", content: <Content page="audio-sync" /> },
    { title: "Updates", route: "/gabecubeaura/settings/updates", content: <Content page="updates" /> },
    "separator",
    { title: "Advanced / debug", route: "/gabecubeaura/settings/advanced", content: <Content page="advanced" /> },
  ]} />;
}

export default definePlugin(() => {
  // Decky invokes this initializer once when it loads the frontend bundle.
  // Runtime signals must start here, not when the user first opens the panel.
  const runtime = startGabeCubeAuraRuntime();
  const weatherTopBar = startWeatherTopBar();
  const updateNotifications = startUpdateNotifications();
  routerHook.addRoute("/gabecubeaura/settings", GabeCubeAuraSettings);
  return {
    name: "GabeCubeAura",
    titleView: <div className={staticClasses.Title}>GabeCubeAura</div>,
    content: <Content />,
    icon: <TbCubeSpark />,
    alwaysRender: true,
    onDismount() {
      runtime.stop();
      weatherTopBar.stop();
      updateNotifications.stop();
      routerHook.removeRoute("/gabecubeaura/settings");
    },
  };
});
