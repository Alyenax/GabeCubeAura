// How much Home Assistant may do, per device. No Decky imports, so the rules can be unit tested.
// The numbers and names match signalbar/mqtt/config.py TIER_NAMES.
export type MqttTier = 1 | 2 | 3 | 4 | 5;

export const TIER_OPTIONS: { data: MqttTier; label: string }[] = [
  { data: 1, label: "Watch only" },
  { data: 2, label: "Help out" },
  { data: 3, label: "Take the lead" },
  { data: 4, label: "In control" },
  { data: 5, label: "Full control" },
];

// The faceplate has nothing Home Assistant can show yet.
export const FACEPLATE_TIER_OPTIONS = TIER_OPTIONS.filter((option) => option.data <= 2);

// One line under each dropdown, enough to predict what the bar will do.
export const TIER_EXPLAINERS: Record<MqttTier, string> = {
  1: "Home Assistant sees what GabeCubeAura is doing and changes nothing.",
  2: "Home Assistant can change settings, send alerts and light the bar. GabeCubeAura's own events and signals "
    + "still win.",
  3: "Home Assistant's light and alerts beat everything except urgent warnings. When it's quiet, GabeCubeAura's "
    + "displays come back.",
  4: "Only Home Assistant and urgent warnings, like overheating, use the bar. When it's quiet, Steam has it.",
  5: "Home Assistant has the bar to itself, overheating and playtime warnings included. Steam still shows its own "
    + "animations, like downloads, and has the bar when Home Assistant is quiet.",
};

export const FACEPLATE_EXPLAINERS: Record<1 | 2, string> = {
  1: "Home Assistant sees the faceplate and changes nothing.",
  2: "Home Assistant can change the faceplate's settings.",
};

export const FALLBACK_LABEL = "When Home Assistant is unreachable, let GabeCubeAura take over";
export const FALLBACK_NOTE = "After 30 seconds without Home Assistant the light bar works as it does at Help out, "
  + "until Home Assistant is back.";
export const FULL_CONTROL_CONFIRM = "Home Assistant takes over everything, including overheating and playtime "
  + "warnings. Continue?";

export const HOME_ASSISTANT_DISPLAY = { data: "home_assistant", label: "Home Assistant" } as const;

/** The fallback only matters where Home Assistant can push GabeCubeAura aside. */
export function showsFallback(tier: MqttTier): boolean {
  return tier >= 3;
}

/** What choosing a light bar tier saves, and the question to ask first, if any. Full control turns the
 * fallback off in the same save, unless it is already off; the user can turn it back on. */
export function lightBarTierChange(tier: MqttTier, haFallback: boolean): {
  changes: { light_bar_tier: MqttTier; ha_fallback?: boolean }; confirm: string;
} {
  if (tier !== 5) return { changes: { light_bar_tier: tier }, confirm: "" };
  return {
    changes: haFallback ? { light_bar_tier: 5, ha_fallback: false } : { light_bar_tier: 5 },
    confirm: FULL_CONTROL_CONFIRM,
  };
}

/** What Home Assistant's light does to the selected display at this tier. */
export function lightNote(tier: MqttTier): string {
  if (tier === 1) return "";
  if (tier === 2) {
    return "Turning Home Assistant's light on selects the Home Assistant display for Home or the current game, "
      + "which switches to the Custom preset. Turning it off puts your display back.";
  }
  return "Home Assistant's light never changes your Home or game display.";
}

/** The line under the light bar dropdown. A dropped connection and a takeover can both be true, so both show. */
export function tierDescription(note: string, fallback: string, tier: MqttTier): string {
  return [note, fallback].filter(Boolean).join(" ") || TIER_EXPLAINERS[tier];
}

export function fallbackLine(status: { falling_back: boolean }): string {
  return status.falling_back ? "Home Assistant is unreachable, so GabeCubeAura has taken over for now." : "";
}

/** Home and in-game display choices. "Home Assistant" is listed at Help out, and while it is selected,
 * so the dropdown never shows a blank choice. */
export function withHomeAssistantDisplay<T extends { data: string; label: string }>(
  options: readonly T[], offered: boolean, selected: string,
): (T | typeof HOME_ASSISTANT_DISPLAY)[] {
  return offered || selected === HOME_ASSISTANT_DISPLAY.data ? [...options, HOME_ASSISTANT_DISPLAY] : [...options];
}

export const PRESET_NOTE = "When Home Assistant changes a setting that a display preset controls, such as "
  + "the Home display or Light Events, GabeCubeAura switches to the Custom preset, the same as when you "
  + "change it on the Steam Machine.";

export interface TierStatus {
  connected: boolean;
  connected_with_current_settings: boolean;
  faceplate_controls: boolean;
}

export interface TierRows {
  // True once the bridge has connected with the current broker settings.
  visible: boolean;
  // True while the connection is down; note then says why.
  disabled: boolean;
  note: string;
  // True only in builds whose faceplate has settings to offer.
  faceplate: boolean;
}

export function tierRows(status: TierStatus): TierRows {
  return {
    visible: status.connected_with_current_settings,
    disabled: !status.connected,
    note: status.connected ? "" : "Reconnecting…",
    faceplate: status.faceplate_controls,
  };
}
