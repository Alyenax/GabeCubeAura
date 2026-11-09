import {useRef, useState} from "react";
import {callable} from "@decky/api";
import {ButtonItem, DropdownItem, Localized, PanelSectionRow} from "../localized_ui";

const sizes = [1, 4, 32, 56, 64, 80];
const messages: Record<string, string> = {
  confirmed: "Faceplate confirmed the new GIF.",
  "already-stored": "This GIF was already stored. No new write was confirmed.",
  "begin-refused": "The Faceplate refused the transfer before any image data.",
  "begin-timeout": "The Faceplate did not reply before the transfer could start.",
  unconfirmed: "The GIF was sent, but the final confirmation was missing.",
  "flash-protection": "Flash protection paused the test. Stop here and export the diagnostic.",
  unavailable: "Connect the Faceplate and leave its display enabled in GabeCubeAura.",
  busy: "The Faceplate is busy. Wait for the current operation and try once more.",
  cancelled: "The test stopped because the display state changed.",
  timeout: "The test timed out. Export the diagnostic.",
  failed: "The test could not finish. Export the diagnostic.",
};
type Result = {state: string; size_bytes?: number};
const send = callable<[sizeKiB: number], Result>("run_faceplate_gif_size_test");

export function FaceplateGifSizeTest() {
  const [open, setOpen] = useState(false);
  const [size, setSize] = useState(sizes[0]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const inFlight = useRef(false);
  const run = async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setResult(null);
    try { setResult(await send(size)); }
    catch { setResult({state: "failed"}); }
    finally { inFlight.current = false; setBusy(false); }
  };
  return <>
    <PanelSectionRow><ButtonItem label="Faceplate GIF transfer test" onClick={() => setOpen(!open)}>
      {open ? "Hide" : "Test"}
    </ButtonItem></PanelSectionRow>
    {open ? <>
      <PanelSectionRow><Localized>
        Start with the smallest size. Each send may briefly replace the picture with a dim test pattern. Try one larger size if requested, then export one local diagnostic.
      </Localized></PanelSectionRow>
      <PanelSectionRow><DropdownItem label="Approximate GIF size" selectedOption={size} disabled={busy}
        rgOptions={sizes.map(value => ({data: value, label: String(value) + " KiB"}))}
        onChange={option => {setSize(Number(option.data)); setResult(null);}}/></PanelSectionRow>
      <PanelSectionRow><ButtonItem label="Send one test GIF" onClick={() => void run()} disabled={busy}>
        {busy ? "Sending test GIF…" : "Send"}
      </ButtonItem></PanelSectionRow>
      {result ? <PanelSectionRow><div role="status">
        <Localized>{messages[result.state] ?? messages.failed}</Localized>
        {result.size_bytes ? <div><Localized>GIF size in bytes</Localized>: {result.size_bytes}</div> : null}
      </div></PanelSectionRow> : null}
    </> : null}
  </>;
}
