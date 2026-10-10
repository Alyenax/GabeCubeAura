import { ButtonItem, DropdownItem, Field, PanelSection, PanelSectionRow, TextField, ToggleField } from "@decky/ui";
import { useEffect, useRef, useState } from "react";

import { getMqttStatus, setMqttConfig, setSetting, type MqttBridgeStatus, type MqttState } from "./api";
import {
  DRIVE_NOTE, FACEPLATE_LEVEL_OPTIONS, LEVEL_OPTIONS, PRESET_NOTE, levelRows, type MqttLevel,
} from "./home_assistant_levels";
import { connectionLine } from "./home_assistant_status";

const POLL_MS = 2000;

// Ticks once a second while a retry countdown shows, so only this row redraws between polls.
function StatusRow({ enabled, status, receivedAt }: { enabled: boolean; status: MqttBridgeStatus; receivedAt: number }) {
  const [, setTick] = useState(0);
  const waiting = status.phase === "waiting_retry";
  useEffect(() => {
    if (!waiting) return undefined;
    const timer = window.setInterval(() => setTick((tick) => tick + 1), 1000);
    return () => window.clearInterval(timer);
  }, [waiting]);
  return <PanelSectionRow>
    <Field label="Status" description={connectionLine(enabled, status, (Date.now() - receivedAt) / 1000)}
      focusable={false}>
      {status.connected ? `${status.messages_out} sent` : ""}
    </Field>
  </PanelSectionRow>;
}

export function HomeAssistantPanel() {
  // Keeping the arrival time with the status stops the countdown lagging a render behind.
  const [received, setReceived] = useState<{ state: MqttState; at: number } | null>(null);
  const state = received?.state ?? null;
  const setState = (next: MqttState) => setReceived({ state: next, at: Date.now() });
  const [draft, setDraft] = useState({ host: "", port: "1883", username: "", prefix: "homeassistant" });
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [pollError, setPollError] = useState("");
  // The text fields are filled from the backend once, so polls never overwrite typing.
  const seeded = useRef(false);
  // Counts changes that have landed, so a poll sent before one cannot bring back the old value.
  const changes = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const refresh = () => {
      const started = changes.current;
      return getMqttStatus().then((next) => {
        if (cancelled || started !== changes.current) return;
        setState(next);
        setPollError("");
        if (!seeded.current) {
          seeded.current = true;
          setDraft({ host: next.config.host, port: String(next.config.port), username: next.config.username,
            prefix: next.config.discovery_prefix });
        }
      }).catch((e) => { if (!cancelled) setPollError(String(e)); });
    };
    void refresh();
    const timer = window.setInterval(refresh, POLL_MS);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);

  const save = async (update: Parameters<typeof setMqttConfig>[0], newPassword: string | null) => {
    try {
      const next = await setMqttConfig(update, newPassword);
      changes.current += 1;
      setState(next);
      setError("");
      if (newPassword !== null) setPassword("");
    } catch (e) {
      setError(String(e));
    }
  };

  const setAlerts = async (enabled: boolean) => {
    try {
      await setSetting("ha_alerts_enabled", enabled);
      changes.current += 1;
      setState(await getMqttStatus());
    } catch (e) {
      setError(String(e));
    }
  };

  if (!state) {
    const message = error || pollError;
    return <PanelSection title="Home Assistant">
      <PanelSectionRow><Field label={message ? `Backend error: ${message}` : "Loading…"} focusable={false} /></PanelSectionRow>
    </PanelSection>;
  }

  const { config, status } = state;
  const port = Number.parseInt(draft.port, 10);
  const rows = levelRows(status);
  const shownError = error || pollError || config.load_error;

  return <>
    <PanelSection title="Home Assistant (MQTT)">
      <PanelSectionRow>
        <div style={{ width: "100%", fontSize: ".78em", opacity: .75 }}>
          Sends GabeCubeAura's state, the current game and events to your MQTT broker for Home Assistant.
          Nothing leaves the Steam Machine until Connect to Home Assistant is on.
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
        <TextField label={config.has_password ? "Password (saved, type to replace)" : "Password"} value={password}
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
      <StatusRow enabled={config.enabled} status={status} receivedAt={received?.at ?? Date.now()} />
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
        <DropdownItem label="Faceplate" rgOptions={FACEPLATE_LEVEL_OPTIONS} selectedOption={config.faceplate_level}
          disabled={rows.disabled}
          onChange={(option) => void save({ faceplate_level: option.data as MqttLevel }, null)} />
      </PanelSectionRow>}
      <PanelSectionRow>
        <div style={{ width: "100%", fontSize: ".78em", opacity: .75 }}>
          Home Assistant always receives GabeCubeAura's state. With "Home Assistant controls settings" it can
          also change those settings, checked the same way as on this page. {PRESET_NOTE}
          {config.light_bar_level === "drive" ? ` ${DRIVE_NOTE}` : ""}
        </div>
      </PanelSectionRow>
      {config.light_bar_level === "drive" && <PanelSectionRow>
        <ToggleField label="Home Assistant alerts" checked={state.ha_alerts_enabled} disabled={rows.disabled}
          description={"Short flashes, pulses and sweeps in a colour Home Assistant picks. They interrupt the "
            + "display like Steam notifications and need Light Events on. Only this page can turn them on."}
          onChange={(value) => void setAlerts(value)} />
      </PanelSectionRow>}
      {status.command_error && <PanelSectionRow>
        <Field label="Last refused change" description={status.command_error} focusable={false} />
      </PanelSectionRow>}
      <PanelSectionRow>
        <ToggleField label="Turbo mode" checked={config.turbo}
          description={"Normally GabeCubeAura sends updates often enough for automations without filling "
            + "Home Assistant's database. Turbo mode sends every change, up to once a second. Only turn it "
            + "on if you need it and have set up Home Assistant's recorder for these sensors."}
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
