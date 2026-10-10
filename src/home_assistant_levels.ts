// What Home Assistant may do, per device. No Decky imports, so the rules can be unit tested.
// The values match signalbar/mqtt/config.py LEVELS and are only ever appended to.
export type MqttLevel = "report" | "settings" | "drive";

export const LEVEL_OPTIONS: { data: MqttLevel; label: string }[] = [
  { data: "report", label: "Report only" },
  { data: "settings", label: "Home Assistant controls settings" },
  { data: "drive", label: "Home Assistant drives it" },
];

// The faceplate has nothing Home Assistant could drive yet.
export const FACEPLATE_LEVEL_OPTIONS = LEVEL_OPTIONS.filter((option) => option.data !== "drive");

export const HOME_ASSISTANT_DISPLAY = { data: "home_assistant", label: "Home Assistant" } as const;

export const DRIVE_NOTE = "With \"Home Assistant drives it\" Home Assistant also gets a light and alert "
  + "buttons for the light bar. Turning the light on selects the Home Assistant display for Home or the "
  + "current game, which switches to the Custom preset, and turning it off puts your display back. "
  + "Thermal protection, Steam, controller alerts and playtime countdowns still come first.";

/** Home and in-game display choices. "Home Assistant" is listed while Home Assistant drives the light
 * bar, and while it is selected, so the dropdown never shows a blank choice. */
export function withHomeAssistantDisplay<T extends { data: string; label: string }>(
  options: readonly T[], offered: boolean, selected: string,
): (T | typeof HOME_ASSISTANT_DISPLAY)[] {
  return offered || selected === HOME_ASSISTANT_DISPLAY.data ? [...options, HOME_ASSISTANT_DISPLAY] : [...options];
}

export const PRESET_NOTE = "When Home Assistant changes a setting that a display preset controls, such as "
  + "the Home display or Light Events, GabeCubeAura switches to the Custom preset, the same as when you "
  + "change it on the Steam Machine.";

export interface LevelStatus {
  connected: boolean;
  connected_with_current_settings: boolean;
  faceplate_controls: boolean;
}

export interface LevelRows {
  // True once the bridge has connected with the current broker settings.
  visible: boolean;
  // True while the connection is down; note then says why.
  disabled: boolean;
  note: string;
  // True only in builds whose faceplate has settings to offer.
  faceplate: boolean;
}

export function levelRows(status: LevelStatus): LevelRows {
  return {
    visible: status.connected_with_current_settings,
    disabled: !status.connected,
    note: status.connected ? "" : "Reconnecting…",
    faceplate: status.faceplate_controls,
  };
}
