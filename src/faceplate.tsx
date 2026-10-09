import {
  ButtonItem,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  SliderField,
  ToggleField,
} from "@decky/ui";
import { FileSelectionType, openFilePicker } from "@decky/api";
import { useEffect, useRef, useState } from "react";

import {
  getFaceplateStatus,
  setFaceplateGameSettings,
  setFaceplateSetting,
  type FaceplateArtStyle,
  type FaceplateGameProfile,
  type FaceplateLogoPosition,
  type FaceplateSettings,
  type FaceplateStatus,
} from "./api";

const POLL_MS = 1000;
// Brightness reaches the panel once the slider settles, not at every step.
const SLIDER_SETTLE_MS = 400;

const MODES = [
  { data: "off", label: "Off (leave the panel alone)" },
  { data: "artwork", label: "Game artwork" },
  { data: "clock", label: "Clock" },
  { data: "aura", label: "Light bar glow" },
  { data: "image", label: "Custom image" },
];

const ART_STYLES: { data: FaceplateArtStyle; label: string }[] = [
  { data: "logo_dim", label: "Artwork + logo, shaded behind logo" },
  { data: "logo", label: "Artwork + logo" },
  { data: "art", label: "Artwork only" },
  { data: "logo_only", label: "Logo only" },
];

const LOGO_POSITIONS: { data: FaceplateLogoPosition; label: string }[] = [
  { data: "top", label: "Top" },
  { data: "centre", label: "Centre" },
  { data: "bottom", label: "Bottom" },
];

const IDLE_CHOICES = [
  { data: "steam", label: "Steam logo" },
  { data: "clock", label: "Clock" },
  { data: "keep", label: "Keep the last game's picture" },
];

const SLEEP_ACTIONS = [
  { data: "off", label: "Turn the screen off" },
  { data: "dim", label: "Dim it" },
  { data: "keep", label: "Keep the picture" },
];

const CLOCK_COLOURS = [
  { data: "#ff8c14", label: "Amber" },
  { data: "#ffffff", label: "White" },
  { data: "#1a9fff", label: "Steam blue" },
  { data: "#40ff60", label: "Green" },
  { data: "#ff3050", label: "Red" },
];

function gameTitle(appid: number): string {
  const store = (window as unknown as {
    appStore?: { GetAppOverviewByAppID?: (id: number) => { display_name?: string } | null };
  }).appStore;
  try {
    return store?.GetAppOverviewByAppID?.(appid)?.display_name || "this game";
  } catch {
    return "this game";
  }
}

export function FaceplatePanel() {
  const [status, setStatus] = useState<FaceplateStatus | null>(null);
  // A failed save stays visible; a successful poll only clears its own error.
  const [error, setError] = useState("");
  const [pollError, setPollError] = useState("");
  const [brightness, setBrightness] = useState<number | null>(null);
  const brightnessTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    const refresh = () => getFaceplateStatus()
      .then((next) => { if (!cancelled) { setStatus(next); setPollError(""); } })
      .catch((e) => { if (!cancelled) setPollError(String(e)); });
    void refresh();
    const timer = window.setInterval(refresh, POLL_MS);
    return () => { cancelled = true; window.clearInterval(timer); window.clearTimeout(brightnessTimer.current); };
  }, []);

  const apply = async (call: () => Promise<FaceplateStatus>) => {
    try {
      setStatus(await call());
      setError("");
    } catch (e) {
      setError(String(e));
    }
  };
  const save = <K extends keyof FaceplateSettings>(key: K, value: FaceplateSettings[K]) =>
    apply(() => setFaceplateSetting(key, value));
  const saveGame = (appid: number, changes: Partial<FaceplateGameProfile> | null) =>
    apply(() => setFaceplateGameSettings(appid, changes));

  if (!status) {
    return <PanelSection title="Faceplate">
      <PanelSectionRow><Field label={error || pollError ? `Backend error: ${error || pollError}` : "Loading..."} focusable={false} /></PanelSectionRow>
    </PanelSection>;
  }

  const s = status.settings;
  const appid = status.appid;
  const profile = appid ? s.game_profiles[String(appid)] : undefined;
  // What the running game shows: its own choices if it has them, else the global ones.
  const art = profile ?? s;
  const saveArt = (changes: Partial<FaceplateGameProfile>) => profile
    ? saveGame(appid, changes)
    : apply(async () => {
      let next = status;
      for (const [key, value] of Object.entries(changes)) {
        next = await setFaceplateSetting(key as keyof FaceplateGameProfile, value);
      }
      return next;
    });
  const pickImage = async () => {
    try {
      const picked = await openFilePicker(FileSelectionType.FILE, s.image_path || "/home/deck/Pictures",
        true, true, undefined, ["png", "jpg", "jpeg", "gif", "bmp"]);
      await save("image_path", picked.realpath || picked.path);
      await save("mode", "image");
    } catch (e) {
      // Closing the picker rejects; that is not an error worth showing.
      if (String(e).trim()) setError(String(e));
    }
  };

  return <>
    <PanelSection title="JSAUX Pixel Matrix Faceplate">
      <PanelSectionRow>
        <div style={{ width: "100%", fontSize: ".78em", opacity: .75 }}>
          The 64x54 RGB faceplate, driven over its USB cable. It stores every picture in its own flash, so
          a picture is sent only when it changes.
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <DropdownItem label="Mode" rgOptions={MODES} selectedOption={s.mode}
          onChange={(option) => void save("mode", option.data)} />
      </PanelSectionRow>
      <PanelSectionRow>
        <SliderField label="Brightness" value={brightness ?? s.brightness} min={0} max={100} step={5} showValue
          onChange={(value) => {
            setBrightness(value);
            window.clearTimeout(brightnessTimer.current);
            brightnessTimer.current = window.setTimeout(
              () => void save("brightness", value).finally(() => setBrightness(null)), SLIDER_SETTLE_MS);
          }} />
      </PanelSectionRow>
      {status.brightness_applied !== null && status.brightness_applied < s.brightness && <PanelSectionRow>
        <Field label={`Running at ${status.brightness_applied}%`}
          description="This picture is bright enough that full brightness can overload the USB port, so it is capped."
          focusable={false} />
      </PanelSectionRow>}
    </PanelSection>

    {s.mode === "artwork" && <PanelSection title="Game artwork">
      {appid > 0 && <PanelSectionRow>
        <ToggleField label={`Just for ${gameTitle(appid)}`}
          description={profile
            ? "Style and logo position below apply to this game only."
            : "Off: this game uses the same style as every other game."}
          checked={Boolean(profile)} onChange={(value) => void saveGame(appid, value ? {} : null)} />
      </PanelSectionRow>}
      <PanelSectionRow>
        <DropdownItem label="Artwork style" rgOptions={ART_STYLES} selectedOption={art.art_style}
          description={art.art_style === "logo_only" ? "Games without a logo show their artwork instead." : undefined}
          onChange={(option) => void saveArt({ art_style: option.data as FaceplateArtStyle })} />
      </PanelSectionRow>
      {art.art_style !== "art" && <PanelSectionRow>
        <DropdownItem label="Logo position" rgOptions={LOGO_POSITIONS} selectedOption={art.logo_position}
          onChange={(option) => void saveArt({ logo_position: option.data as FaceplateLogoPosition })} />
      </PanelSectionRow>}
      <PanelSectionRow>
        <DropdownItem label="Between games" rgOptions={IDLE_CHOICES} selectedOption={s.artwork_idle}
          description={s.artwork_idle === "clock" ? "The clock writes to the panel's flash once a minute." : undefined}
          onChange={(option) => void save("artwork_idle", option.data)} />
      </PanelSectionRow>
    </PanelSection>}

    {(s.mode === "clock" || (s.mode === "artwork" && s.artwork_idle === "clock")) && <PanelSection title="Clock">
      <PanelSectionRow>
        <DropdownItem label="Clock colour" rgOptions={CLOCK_COLOURS} selectedOption={s.clock_colour}
          onChange={(option) => void save("clock_colour", option.data)} />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField label="24-hour clock" checked={s.clock_24h} onChange={(value) => void save("clock_24h", value)} />
      </PanelSectionRow>
    </PanelSection>}

    {s.mode === "aura" && <PanelSection title="Light bar glow">
      <PanelSectionRow>
        <SliderField label="Check every (seconds)" value={s.aura_interval} min={30} max={600} step={30} showValue
          description="Copies the light bar's colours as a soft glow; only visible changes are sent."
          onChange={(value) => void save("aura_interval", value)} />
      </PanelSectionRow>
    </PanelSection>}

    {s.mode === "image" && <PanelSection title="Custom image">
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => void pickImage()} description={s.image_path || "No image chosen"}>
          Choose image...
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>}

    {s.mode !== "off" && <PanelSection title="Mounting">
      <PanelSectionRow>
        <ToggleField label="Upside down (cable on the right)" checked={s.rotate}
          description="Flips the picture for a faceplate mounted with its cable out of the right side. The included cable is too short for that side."
          onChange={(value) => void save("rotate", value)} />
      </PanelSectionRow>
    </PanelSection>}

    {s.mode !== "off" && <PanelSection title="Sleep and shutdown">
      <PanelSectionRow>
        <DropdownItem label="When the Steam Machine sleeps" rgOptions={SLEEP_ACTIONS} selectedOption={s.sleep_action}
          description="USB stays powered during sleep, so the panel stays lit unless it is told otherwise."
          onChange={(option) => void save("sleep_action", option.data)} />
      </PanelSectionRow>
      <PanelSectionRow>
        <DropdownItem label="When it shuts down" rgOptions={SLEEP_ACTIONS} selectedOption={s.shutdown_action}
          onChange={(option) => void save("shutdown_action", option.data)} />
      </PanelSectionRow>
    </PanelSection>}

    <PanelSection title="Faceplate status">
      <PanelSectionRow>
        <Field label={status.connected ? "Connected" : status.port ? "Not connected" : "Faceplate not found"} focusable={false}>
          {status.port}
        </Field>
      </PanelSectionRow>
      <PanelSectionRow>
        <Field label={status.phase.charAt(0).toUpperCase() + status.phase.slice(1)} description={status.detail} focusable={false} />
      </PanelSectionRow>
      <PanelSectionRow>
        <Field label="Flash writes" description="Every picture is stored in the panel's flash. This session / all time." focusable={false}>
          {status.uploads} / {status.lifetime_uploads}
        </Field>
      </PanelSectionRow>
      {(error || pollError || status.last_error) && <PanelSectionRow>
        <Field label="Error" description={error || pollError || status.last_error} focusable={false} />
      </PanelSectionRow>}
      <PanelSectionRow>
        <ButtonItem label="End of Faceplate settings"
          description="This final row keeps the complete page reachable with controller navigation."
          onClick={() => void getFaceplateStatus().then(setStatus).catch(console.warn)}>
          Refresh status
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  </>;
}
