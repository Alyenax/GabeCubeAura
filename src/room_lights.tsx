import { ButtonItem, DropdownItem, Focusable, PanelSection, PanelSectionRow, SliderField, TextField, ToggleField } from "@decky/ui";
import { type ReactNode, useEffect, useState } from "react";
import {
  roomLightsIdentify, roomLightsScan, roomLightsSetLight, roomLightsSetOptions, roomLightsStatus,
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

// The screen as a small rectangle: cells around the edge (corners included),
// the middle is the whole picture. Built from rows of Focusables so the D-pad
// moves between cells the way it does everywhere else in Steam; A or a tap
// adds or removes a cell.
function ZonePicker({ across, down, picked, taken, onToggle }: {
  across: number;
  down: number;
  picked: string[];
  taken: string[];
  onToggle: (zone: string) => void;
}) {
  const [focused, setFocused] = useState("");
  const cell = (zone: string, grow = 1, label = "") => {
    const on = picked.includes(zone);
    return <Focusable key={zone} onActivate={() => onToggle(zone)} onClick={() => onToggle(zone)}
      onGamepadFocus={() => setFocused(zone)} onGamepadBlur={() => setFocused((z) => (z === zone ? "" : z))}
      noFocusRing style={{
        flex: grow, height: "100%", borderRadius: 3, boxSizing: "border-box",
        display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11,
        background: on ? "#1a9fff" : taken.includes(zone) ? "#3d4450" : "#23262e",
        color: on ? "#fff" : "#8b929a",
        outline: focused === zone ? "2px solid #fff" : "none", outlineOffset: 1,
      }}>{label}</Focusable>;
  };
  const row = (key: string, height: number, cells: ReactNode[]) =>
    <Focusable key={key} flow-children="row" style={{ display: "flex", gap: 3, height }}>{cells}</Focusable>;
  const side = (name: string) => <Focusable key={name} flow-children="column"
    style={{ flex: 1, display: "flex", flexDirection: "column", gap: 3 }}>
    {Array.from({ length: down }, (_, i) => cell(`${name}-${i + 1}`))}
  </Focusable>;
  const edge = (name: string) => Array.from({ length: across }, (_, i) => cell(`${name}-${i + 1}`, 2));
  return <Focusable flow-children="column" style={{
    display: "flex", flexDirection: "column", gap: 3, width: 320, margin: "4px auto 8px",
  }}>
    {row("top", 24, [cell("top-left"), ...edge("top"), cell("top-right")])}
    {row("middle", 120, [side("left"), cell("whole", across * 2, "Whole picture"), side("right")])}
    {row("bottom", 24, [cell("bottom-left"), ...edge("bottom"), cell("bottom-right")])}
  </Focusable>;
}

export function RoomLightsPanel() {
  const [state, setState] = useState<RoomLightsStatus | null>(null);
  const [scanning, setScanning] = useState(false);
  const [extraIp, setExtraIp] = useState("");
  const [blinking, setBlinking] = useState("");

  useEffect(() => {
    // Saved lights show at once; a quiet scan then adds anything new.
    roomLightsStatus().then(setState);
    roomLightsScan([]).then(setState).catch(() => undefined);
  }, []);

  const scan = async () => {
    setScanning(true);
    try {
      setState(await roomLightsScan(extraIp.trim() ? [extraIp.trim()] : []));
      setExtraIp("");
    } catch (error) {
      console.warn("[GabeCubeAura] smart lighting scan failed", error);
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

  const brands = state.brands ?? [];
  const toggleBrand = (brand: string, on: boolean) =>
    options({ brands: on ? [...brands.filter((b) => b !== brand), brand] : brands.filter((b) => b !== brand) });

  return <>
    <PanelSection title="Smart lighting">
      <PanelSectionRow><div style={note}>
        Puts the game on the smart lights around your room. Key art lights share a slow ring of the
        game's artwork colours. Screen lights follow the parts of the picture you pick for them,
        in real time. Mix them however you like.
      </div></PanelSectionRow>
      <PanelSectionRow>
        <ToggleField label="Turn on smart lighting" checked={state.enabled} onChange={(enabled) => options({ enabled })} />
      </PanelSectionRow>
      {state.last_error ? <PanelSectionRow><div style={{ ...note, color: "#ff8080" }}>
        Last problem: {state.last_error}
      </div></PanelSectionRow> : null}
    </PanelSection>
    <PanelSection title="Which smart lights do you have?">
      <PanelSectionRow>
        <ToggleField label="Govee" description="Wi-Fi lights with LAN Control. Found on your network, no account needed."
          checked={brands.includes("govee")} onChange={(on) => toggleBrand("govee", on)} />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField label="Philips Hue" disabled checked={false} onChange={() => undefined}
          description="Not available yet. Hue streams through its bridge over an encrypted connection this plugin can't make yet." />
      </PanelSectionRow>
    </PanelSection>
    {brands.includes("govee") ? <PanelSection title="Govee lights">
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
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={blinking === light.ip} onClick={async () => {
              setBlinking(light.ip);
              try { setState(await roomLightsIdentify(light.ip)); } finally { setBlinking(""); }
            }}>{blinking === light.ip ? "Blinking..." : "Identify (blink this light)"}</ButtonItem>
          </PanelSectionRow>
          {role === "screen" && config ? <>
            <PanelSectionRow><div style={note}>
              Pick the parts of the screen this light shows. Each cell is one colour; the light
              spreads them across its own colour zones, lowest end first. A lamp or strip with
              several zones looks best with a few cells in a row; a plain bulb with one.
            </div></PanelSectionRow>
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
    </PanelSection> : null}
    <PanelSection title="Behaviour">
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
  </>;
}
