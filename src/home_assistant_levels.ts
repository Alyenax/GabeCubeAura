// What Home Assistant may do, per device. Kept free of Decky imports so the rules are unit-tested.
// Phase 3 appends "drive" here and in signalbar/mqtt/config.py LEVELS; never reorder or rename.
export type MqttLevel = "report" | "settings";

export const LEVEL_OPTIONS: { data: MqttLevel; label: string }[] = [
  { data: "report", label: "Report only" },
  { data: "settings", label: "Home Assistant controls settings" },
];

export const PRESET_NOTE = "Changing a display setting from Home Assistant (Home or in-game display, "
  + "Light Events, controller alerts and the other settings a display preset sets) switches "
  + "GabeCubeAura to the Custom preset, as changing it here does.";

export interface LevelStatus {
  connected: boolean;
  connected_with_current_settings: boolean;
  faceplate_controls: boolean;
}

export interface LevelRows {
  // The selectors exist only once the bridge has connected with the current broker settings.
  visible: boolean;
  // While the connection is down they stay visible, greyed, with this note.
  disabled: boolean;
  note: string;
  // The faceplate selector only when the faceplate has settings to offer (a faceplate build).
  faceplate: boolean;
}

export function levelRows(status: LevelStatus): LevelRows {
  return {
    visible: status.connected_with_current_settings,
    disabled: !status.connected,
    note: status.connected ? "" : "Reconnecting...",
    faceplate: status.faceplate_controls,
  };
}
