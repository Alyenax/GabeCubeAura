import { addEventListener, callable, removeEventListener } from '@decky/api';
import { Router } from '@decky/ui';
import { selectObservedGame } from './game_session';
import { dispatchGabeAction, type GabeSteamAction } from './gabe_action_dispatch';

declare const SteamClient: any;
const claim = callable<[token: string], GabeSteamAction | null>('timer_claim_action');
const acknowledge = callable<[token: string, accepted: boolean], void>('timer_acknowledge_action');

export function startTimerActions() {
  let stopped = false;
  const listener = addEventListener<[payload: { token: string }]>('timer-action', async payload => {
    if (stopped || !/^[a-f0-9]{32}$/.test(payload?.token ?? '')) return;
    const action = await claim(payload.token).catch(() => null);
    if (!action || stopped) return;
    try {
      dispatchGabeAction(action, {
        alive: () => !stopped,
        currentAppId: () => selectObservedGame(Router?.MainRunningApp, Router?.RunningApps).appid,
        close: typeof SteamClient?.Apps?.TerminateApp === 'function' ? (id, force) => SteamClient.Apps.TerminateApp(id, force) : undefined,
        sleep: typeof SteamClient?.System?.SuspendPC === 'function' ? () => SteamClient.System.SuspendPC() : undefined,
        // Shutdown is confirmation-gated logind PowerOff in the backend.
        // A stale frontend request must fail, never take a different power path.
      });
      // Dispatched to Steam, not proof of a physical power-state transition.
      await acknowledge(payload.token, true);
    } catch { await acknowledge(payload.token, false).catch(() => undefined); }
  });
  return { stop() { stopped = true; removeEventListener('timer-action', listener); } };
}
