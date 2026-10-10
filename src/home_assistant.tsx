import { ButtonItem, DropdownItem, Field, PanelSection, PanelSectionRow, TextField, ToggleField } from "@decky/ui";
import { useEffect, useRef, useState } from "react";

import { getMqttStatus, setMqttConfig, type MqttState } from "./api";
import { LEVEL_OPTIONS, PRESET_NOTE, levelRows, type MqttLevel } from "./home_assistant_levels";

const POLL_MS = 2000;

export function HomeAssistantPanel() {
  const [state, setState] = useState<MqttState | null>(null);
  const [draft, setDraft] = useState({ host: "", port: "1883", username: "", prefix: "homeassistant" });
  const [password, setPassword] = useState("");
  // A failed save stays visible; a successful poll only clears its own error.
  const [error, setError] = useState("");
  const [pollError, setPollError] = useState("");
  // Typed input is seeded from the backend once; later polls must not overwrite it.
  const seeded = useRef(false);

  useEffect(() => {
    let cancelled = false;
    const refresh = () => getMqttStatus()
      .then((next) => {
        if (cancelled) return;
        setState(next);
        setPollError("");
        if (!seeded.current) {
          seeded.current = true;
          setDraft({ host: next.config.host, port: String(next.config.port), username: next.config.username,
            prefix: next.config.discovery_prefix });
        }
      })
      .catch((e) => { if (!cancelled) setPollError(String(e)); });
    void refresh();
    const timer = window.setInterval(refresh, POLL_MS);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);

  const save = async (changes: Parameters<typeof setMqttConfig>[0], newPassword: string | null) => {
    try {
      setState(await setMqttConfig(changes, newPassword));
      setError("");
      if (newPassword !== null) setPassword("");
    } catch (e) {
      setError(String(e));
    }
  };

  if (!state) {
    const message = error || pollError;
    return <PanelSection title="Home Assistant">
      <PanelSectionRow><Field label={message ? `Backend error: ${message}` : "Loading..."} focusable={false} /></PanelSectionRow>
    </PanelSection>;
  }

  const { config, status } = state;
  const port = Number.parseInt(draft.port, 10);
  const statusLine = !config.enabled ? "Off"
    : status.connected ? "Connected"
    : status.last_error ? `Not connected: ${status.last_error}` : "Connecting...";
  // Hidden until connected with these broker settings, greyed while reconnecting; saved levels are
  // never reset by hiding (they live in mqtt.json).
  const rows = levelRows(status);
  const shownError = error || pollError || config.load_error;

  return <>
    <PanelSection title="Home Assistant (MQTT)">
      <PanelSectionRow>
        <div style={{ width: "100%", fontSize: ".78em", opacity: .75 }}>
          Publishes GabeCubeAura's state, game and events to your MQTT broker so Home Assistant can show them.
          Nothing is sent anywhere until you turn this on.
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <TextField label="Broker host" value={draft.host}
          onChange={(event) => setDraft({ ...draft, host: event.currentTarget.value })} />
      </PanelSectionRow>
      <PanelSectionRow>
        <TextField label="Port" value={draft.port}
          onChange={(event) => setDraft({ ...draft, port: event.currentTarget.value })} />
      </PanelSectionRow>
      <PanelSectionRow>
        <TextField label="Username" value={draft.username}
          onChange={(event) => setDraft({ ...draft, username: event.currentTarget.value })} />
      </PanelSectionRow>
      <PanelSectionRow>
        <TextField label={config.has_password ? "Password (saved; type to replace)" : "Password"} value={password}
          bIsPassword onChange={(event) => setPassword(event.currentTarget.value)} />
      </PanelSectionRow>
      <PanelSectionRow>
        <TextField label="Discovery prefix" value={draft.prefix}
          onChange={(event) => setDraft({ ...draft, prefix: event.currentTarget.value })} />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField label="Use TLS" checked={config.tls} onChange={(value) => void save({ tls: value }, null)} />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={!draft.host.trim() || !Number.isFinite(port)}
          onClick={() => void save({ host: draft.host.trim(), port, username: draft.username,
            discovery_prefix: draft.prefix.trim() }, password ? password : null)}>
          Save connection
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField label="Connect to Home Assistant" checked={config.enabled}
          onChange={(value) => void save({ enabled: value }, null)} />
      </PanelSectionRow>
      <PanelSectionRow>
        <Field label="Status" description={statusLine} focusable={false}>
          {status.connected ? `${status.messages_out} sent` : ""}
        </Field>
      </PanelSectionRow>
      {shownError && <PanelSectionRow>
        <Field label="Error" description={shownError} focusable={false} />
      </PanelSectionRow>}
    </PanelSection>

    {rows.visible && <PanelSection title="What Home Assistant can do">
      <PanelSectionRow>
        <DropdownItem label="Light bar" rgOptions={LEVEL_OPTIONS} selectedOption={config.light_bar_level}
          disabled={rows.disabled} description={rows.note || undefined}
          onChange={(option) => void save({ light_bar_level: option.data as MqttLevel }, null)} />
      </PanelSectionRow>
      {rows.faceplate && <PanelSectionRow>
        <DropdownItem label="Faceplate" rgOptions={LEVEL_OPTIONS} selectedOption={config.faceplate_level}
          disabled={rows.disabled} description={rows.note || undefined}
          onChange={(option) => void save({ faceplate_level: option.data as MqttLevel }, null)} />
      </PanelSectionRow>}
      <PanelSectionRow>
        <div style={{ width: "100%", fontSize: ".78em", opacity: .75 }}>
          Home Assistant always sees everything here. With "Home Assistant controls settings" it can also
          change that device's settings, with the same checks as this page. {PRESET_NOTE}
        </div>
      </PanelSectionRow>
      {status.command_error && <PanelSectionRow>
        <Field label="Last refused change" description={status.command_error} focusable={false} />
      </PanelSectionRow>}
      <PanelSectionRow>
        <ToggleField label="Turbo mode" checked={config.turbo}
          description={"By default GabeCubeAura sends updates often enough for automations and Home Assistant "
            + "control, but not so often that it bloats your Home Assistant database. Turbo mode sends "
            + "everything in real time. Only turn it on if you have a reason to and have set up Home "
            + "Assistant's recorder to cope with these sensors."}
          onChange={(value) => void save({ turbo: value }, null)} />
      </PanelSectionRow>
    </PanelSection>}

    <PanelSection>
      <PanelSectionRow><ButtonItem label="End of Home Assistant settings"
        description="This final row keeps the complete page reachable with controller navigation."
        onClick={() => void getMqttStatus().then(setState).catch(console.warn)}>
        Refresh status
      </ButtonItem></PanelSectionRow>
    </PanelSection>
  </>;
}
