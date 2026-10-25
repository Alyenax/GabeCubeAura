import type { Status } from "./types";

export type FaceplateUXState = { label: string; detail: string; tone: "good" | "waiting" | "error" };

function failureState(error: string): FaceplateUXState {
  return {label: /no reply|serial|refused (?:stored )?GIF|native clock|0x05 ACK/i.test(error)
    ? 'Transfer not confirmed' : 'Preparation failed', detail: error, tone: 'error'};
}

export function faceplateUXState(status: Pick<Status, "faceplate" | "faceplate_lab_enabled">): FaceplateUXState {
  const panel = status.faceplate;
  const router = panel.routing;
  if (!panel.available) return { label: "Faceplate not detected", detail: "Connect the JSAUX matrix to use automatic displays.", tone: "waiting" };
  if (panel.busy) return { label: "Faceplate in use", detail: "Another application holds the matrix. Your choice is saved.", tone: "waiting" };
  if (panel.powered === false) return { label: "Faceplate powered off", detail: "Your display choice is saved for when the matrix is switched on.", tone: "waiting" };
  if (!status.faceplate_lab_enabled) return { label: "Automation off", detail: "The last saved image may remain on the matrix.", tone: "waiting" };
  if (panel.automation.busy && (/^(?:external|gabe):/.test(panel.automation.active_scene||'')))
    return {label: 'Temporary display active', detail: 'Your normal display returns when the temporary display ends.', tone: 'waiting'};
  // A previous worker error is historical while a new request is in flight.
  // Never turn it into a permanent failure of the new requested scene.
  const error = router.preparation.error;
  if (panel.delivery?.state === 'deferred' && error.startsWith('Flash protection:')) return {
    label: 'Refresh delayed by protection',
    detail: 'The latest requested scene is retained for retry. The previous clock, timer or statistics may be out of date; the native LED timer is independent.',
    tone: 'waiting',
  };
  if (router.preparation.state === 'unconfirmed') return {
    label: 'Sent · confirmation unavailable',
    detail: router.desired_scene === 'native-clock'
      ? 'Native clock acknowledgement unavailable. No automatic repeat or GIF fallback; the physical mode is unknown.'
      : panel.last_transfer?.already_stored
      ? 'Stored GIF recognized; display activation acknowledgement is unavailable. No new GIF body was sent.'
      : 'All GIF data was acknowledged; final USB confirmation is unavailable. The matrix may already be playing it.',
    tone: 'waiting',
  };
  if (error) return failureState(error);
  if (panel.automation.busy || panel.automation.queued || ["pending", "preparing"].includes(router.preparation.state)) {
    return { label: "Applying display…", detail: `Requested: ${router.desired_scene || "saved scene"}. The previous image can remain during transfer.`, tone: "waiting" };
  }
  if (panel.automation.last_error) return failureState(panel.automation.last_error);
  if (!router.effective_scene || !router.effective_content_key || router.effective_content_key !== router.desired_content_key) {
    return { label: "Waiting for display confirmation", detail: `Saved choice: ${router.desired_scene || "automatic"}.`, tone: "waiting" };
  }
  if (router.effective_scene === 'native-clock') return {
    label: 'Native clock synchronized',
    detail: 'USB acknowledgement received. The MCU keeps time autonomously; visible playback requires a hardware check.',
    tone: 'good',
  };
  return { label: `Acknowledged ${router.effective_scene}`, detail: panel.automation.last_result?.fallback
    ? `Fallback: ${panel.automation.last_result.fallback}. Visible playback is not confirmed.` : "Last USB transaction acknowledged. Visible playback cannot be confirmed by the software.", tone: "good" };
}

export function installedGameChoices<T extends { name: string }>(games: T[], query: string, limit = 12): T[] {
  const search = query.trim().toLocaleLowerCase();
  return games.filter((game) => !search || game.name.toLocaleLowerCase().includes(search)).slice(0, limit);
}
