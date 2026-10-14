import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow, SliderField, TextField, ToggleField } from "@decky/ui";
import { useEffect, useState } from "react";
import {
  roomLightsScan, roomLightsSetBrightness, roomLightsSetEnabled, roomLightsSetRole, roomLightsStatus,
  type RoomLight, type RoomLightsStatus,
} from "./api";

const ROLE_LABELS: Record<string, string> = {
  "off": "Off",
  "key-art": "Key art (slow ambient)",
  "screen-left": "Screen: left edge",
  "screen-right": "Screen: right edge",
  "screen-top": "Screen: top edge",
  "screen-bottom": "Screen: bottom edge",
  "screen-whole": "Screen: whole picture",
};

const note = { fontSize: ".78em", opacity: .78 };

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
  const roleOf = (light: RoomLight) => state.lights[light.id]?.role ?? "off";

  return <>
    <PanelSection title="Room lights">
      <PanelSectionRow><div style={note}>
        Puts the game on the lights around your room. Lights on the key art role share a slow
        ring of the game's artwork colours. Screen roles follow one edge of the picture in real
        time, like a sync box. Mix them however you like.
      </div></PanelSectionRow>
      <PanelSectionRow>
        <ToggleField label="Room lights" checked={state.enabled}
          onChange={async (value) => setState(await roomLightsSetEnabled(value))} />
      </PanelSectionRow>
      <PanelSectionRow>
        <SliderField label="Light brightness" value={state.brightness} min={5} max={100} step={5}
          showValue onChange={async (value) => setState(await roomLightsSetBrightness(value))} />
      </PanelSectionRow>
    </PanelSection>
    <PanelSection title="Govee lights">
      <PanelSectionRow><div style={note}>
        Turn on LAN Control for each light in the Govee app, then scan. No account or key needed.
        If your lights are on a different network or VLAN the scan can't see them; type a light's
        IP address below instead.
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
      {state.found.map((light) => <PanelSectionRow key={light.id}>
        <DropdownItem label={`${light.model} · ${light.ip}`}
          rgOptions={state.roles.map((role) => ({ data: role, label: ROLE_LABELS[role] ?? role }))}
          selectedOption={roleOf(light)}
          onChange={async (option) => setState(
            await roomLightsSetRole(light.id, light.ip, light.model, option.data as string))} />
      </PanelSectionRow>)}
    </PanelSection>
  </>;
}
