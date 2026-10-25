import type { Status } from './types';
import { faceplateUXState } from './faceplate_ux';

export function quickOwnerLabel(status: Pick<Status, 'available' | 'owner'> & Partial<Pick<Status, 'signalbar_enabled' | 'debug'>>): string {
  if (status.signalbar_enabled === false) return 'Displays off';
  if (status.debug?.engine_running === false) return 'Display engine stopped';
  if (!status.available) return 'Light bar not detected';
  return status.owner === 'GabeCubeAura' ? 'GabeCubeAura in control' : 'Steam in control';
}

export function quickFaceplateState(status: Pick<Status, 'faceplate' | 'faceplate_lab_enabled'> & Partial<Pick<Status, 'signalbar_enabled' | 'current_display'>>): {label: string; tone: 'good' | 'waiting' | 'error'; confirmed: boolean; hint?: string} {
  if ((status.signalbar_enabled === false || status.current_display === 'displays_off') && status.faceplate.available && status.faceplate.powered !== false)
    return {label: 'Turning displays off…', tone: 'waiting' as const, confirmed: false};
  const state = faceplateUXState(status);
  const label = state.tone === 'good' ? status.faceplate.routing.effective_scene
    : state.label === 'Display could not be applied' ? 'Preparation failed'
    : state.label === 'Waiting for display confirmation' ? 'Waiting for confirmation'
    : state.label;
  // Never turn a requested scene into a claimed confirmed display.
  return { label, tone: state.tone, confirmed: state.tone === 'good',
    ...(state.tone === 'error' ? {hint: /no reply/i.test(state.detail)
      ? 'No USB confirmation' : /serial.*(owned|in use|lock)/i.test(state.detail)
        ? 'USB port in use' : 'See Faceplate settings'} : {}) };
}

/** No wall-clock guesses, GIF payloads, device probes or timers in the UI. */
export function quickPanelState(status: Pick<Status, 'faceplate' | 'game' | 'current_display'>) {
  // Previously detected hardware cannot leave ghost controls after a disconnect.
  const faceplateControls = status.faceplate.available === true;
  // Content previews are read-only and independent of physical routing/power.
  const gamePreview = status.game.appid <= 0 ? null
    : status.current_display === 'performance' ? 'performance' : 'artwork';
  return { faceplateControls, gamePreview };
}
