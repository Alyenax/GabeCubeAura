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
  if (panel.power_recovery?.manual_off) return {label:'Faceplate off by your choice',
    detail:'The Faceplate stays off after sleep. Weather can still refresh. Use Power on when you want to turn it on.',tone:'waiting'};
  if (panel.restoration?.stored_picture_resumed) return {label:'Power restored; image not confirmed',
    detail:'Stored playback was requested without uploading another image. The requested replacement is still unconfirmed.',tone:'waiting'};
  if (panel.restoration?.recovery_available) return {label:'Image update failed; Faceplate held off',
    detail:'Automatic recovery stopped. Use Resume stored picture below to restore power without uploading another image.',tone:'error'};
  if (panel.restoration?.held_dark && (panel.error || ['error','failed','unconfirmed'].includes(router.preparation.state)
      || ['exhausted','unconfirmed','failed'].includes(panel.power_recovery?.route_state??'')))
    return {label:'Display recovery needs attention',detail:'The image was not confirmed. Automatic attempts are limited; check the recovery action below.',tone:'error'};
  if (panel.restoration?.held_dark) return {label:'Restoring the Faceplate display',
    detail:'The Faceplate is temporarily off while its replacement image is checked. A failed attempt will show an error and a recovery action.',tone:'waiting'};
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
