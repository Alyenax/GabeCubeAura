import { ButtonItem, DialogButton, DropdownItem, Focusable, PanelSection, PanelSectionRow, SliderField, TextField, ToggleField } from "@decky/ui";
import { useEffect, useState } from "react";
import {
  roomLightsScan, roomLightsSetLight, roomLightsSetOptions, roomLightsStatus,
  type RoomLight, type RoomLightsStatus,
} from "./api";

const ROLE_LABELS: Record<string, string> = {
  "off": "Off",
  "key-art": "Key art (slow ambient)",
  "screen": "Screen (real time)",
};

const IDLE_LABELS: Record<string, string> = {
  "leave": "Leave lights alone",
  "warm": "Warm white",
  "off": "Turn off",
};

const note = { fontSize: ".78em", opacity: .78 };

// The screen as a rectangle: cells along each edge, the middle is the whole
// picture. Tap the cells a light should show.
function ZonePicker({ across, down, picked, taken, onToggle }: {
  across: number;
  down: number;
  picked: string[];
  taken: string[];
  onToggle: (zone: string) => void;
}) {
  const cell = (zone: string, column: string, row: string, label = "") => {
    const on = picked.includes(zone);
    return <DialogButton key={zone} onClick={() => onToggle(zone)} style={{
      gridColumn: column, gridRow: row, minWidth: 0, padding: 0, height: "100%",
      fontSize: ".7em", borderRadius: 3,
      background: on ? "#1a9fff" : taken.includes(zone) ? "#3d4450" : "#23262e",
      color: on ? "#fff" : "#8b929a",
    }}>{label}</DialogButton>;
  };
  const cells = [];
  for (let i = 1; i <= across; i++) {
    cells.push(cell(`top-${i}`, `${i + 1}`, "1"));
    cells.push(cell(`bottom-${i}`, `${i + 1}`, `${down + 2}`));
  }
  for (let i = 1; i <= down; i++) {
    cells.push(cell(`left-${i}`, "1", `${i + 1}`));
    cells.push(cell(`right-${i}`, `${across + 2}`, `${i + 1}`));
  }
  cells.push(cell("whole", `2 / ${across + 2}`, `2 / ${down + 2}`, "Whole picture"));
  return <Focusable style={{
    display: "grid", gap: 3, width: "100%", aspectRatio: "16 / 9",
    gridTemplateColumns: `1fr repeat(${across}, 2fr) 1fr`,
    gridTemplateRows: `1fr repeat(${down}, 1.4fr) 1fr`,
  }}>{cells}</Focusable>;
}

export function RoomLightsPanel() {
  const [state, setState] = useState<RoomLightsStatus | null>(null);
  const [scanning, setScanning] = useState(false);
  const [extraIp, setExtraIp] = useState("");

  useEffect(() => { roomLightsStatus().then(setState); }, []);

  const scan = async () => {
    setScanning(true);
    try {
      setState(await roomLightsScan(extraIp.trim() ? [extraIp.trim()] : []));
      setExtraIp("");
    } finally {
      setScanning(false);
    }
  };

  if (!state) return null;
  const options = async (changes: Partial<RoomLightsStatus>) => setState(await roomLightsSetOptions(changes));
  const saved = (light: RoomLight) => state.lights[light.id];
  const zonesTakenBy = (id: string) => Object.entries(state.lights)
    .filter(([other, light]) => other !== id && light.role === "screen")
    .flatMap(([, light]) => light.zones);
  const toggleZone = async (light: RoomLight, zone: string) => {
    const current = saved(light)?.zones ?? [];
    // "Whole picture" and edge cells don't mix: picking one clears the other.
    const next = zone === "whole" ? ["whole"]
      : current.includes(zone) ? current.filter((z) => z !== zone)
        : [...current.filter((z) => z !== "whole"), zone];
    setState(await roomLightsSetLight(light.id, light.ip, light.model, "screen", next.length ? next : ["whole"], null));
  };

  return <>
    <PanelSection title="Room lights">
      <PanelSectionRow><div style={note}>
        Puts the game on the lights around your room. Key art lights share a slow ring of the
        game's artwork colours. Screen lights follow the parts of the picture you pick for them,
        in real time. Mix them however you like.
      </div></PanelSectionRow>
      <PanelSectionRow>
        <ToggleField label="Room lights" checked={state.enabled} onChange={(enabled) => options({ enabled })} />
      </PanelSectionRow>
      <PanelSectionRow>
        <SliderField label="Brightness while playing" value={state.brightness} min={5} max={100} step={5}
          showValue onChange={(brightness) => options({ brightness })} />
      </PanelSectionRow>
      <PanelSectionRow>
        <DropdownItem label="When no game is running"
          rgOptions={state.idle_modes.map((mode) => ({ data: mode, label: IDLE_LABELS[mode] ?? mode }))}
          selectedOption={state.idle} onChange={(option) => options({ idle: option.data as string })} />
      </PanelSectionRow>
      {state.idle === "warm" ? <>
        <PanelSectionRow>
          <SliderField label="Warm white colour (K)" value={state.idle_kelvin} min={2000} max={6500} step={100}
            showValue onChange={(idle_kelvin) => options({ idle_kelvin })} />
        </PanelSectionRow>
        <PanelSectionRow>
          <SliderField label="Warm white brightness" value={state.idle_brightness} min={5} max={100} step={5}
            showValue onChange={(idle_brightness) => options({ idle_brightness })} />
        </PanelSectionRow>
      </> : null}
    </PanelSection>
    <PanelSection title="Govee lights">
      <PanelSectionRow><div style={note}>
        Turn on LAN Control for each light in the Govee app, then scan. No account or key needed.
        Lights are remembered by their device, so it's fine if your router hands them a new IP.
        If your lights are on a different network or VLAN the scan can't see them; type a light's
        IP address below instead (lights added that way can't be found again if their IP changes).
      </div></PanelSectionRow>
      <PanelSectionRow>
        <TextField label="Add a light by IP (optional)" value={extraIp}
          onChange={(event) => setExtraIp(event.target.value)} />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={scanning} onClick={scan}>
          {scanning ? "Scanning..." : "Scan for lights"}
        </ButtonItem>
      </PanelSectionRow>
      {state.found.length === 0 ? <PanelSectionRow><div style={note}>No lights yet.</div></PanelSectionRow> : null}
      {state.found.map((light) => {
        const config = saved(light);
        const role = config?.role ?? "off";
        return <div key={light.id}>
          <PanelSectionRow>
            <DropdownItem label={`${light.model} · ${light.ip}`}
              rgOptions={state.roles.map((value) => ({ data: value, label: ROLE_LABELS[value] ?? value }))}
              selectedOption={role}
              onChange={async (option) => setState(
                await roomLightsSetLight(light.id, light.ip, light.model, option.data as string, null, null))} />
          </PanelSectionRow>
          {role === "screen" && config ? <>
            <PanelSectionRow>
              <ZonePicker across={state.across} down={state.down} picked={config.zones}
                taken={zonesTakenBy(light.id)} onToggle={(zone) => toggleZone(light, zone)} />
            </PanelSectionRow>
            <PanelSectionRow>
              <ToggleField label="Reverse direction" description="If the colours run the wrong way along this light."
                checked={config.reverse}
                onChange={async (reverse) => setState(
                  await roomLightsSetLight(light.id, light.ip, light.model, "screen", null, reverse))} />
            </PanelSectionRow>
          </> : null}
        </div>;
      })}
    </PanelSection>
  </>;
}
