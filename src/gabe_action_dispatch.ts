/** Fixed, synchronous Steam calls after a single-use backend claim. */
export type GabeSteamAction = { action: 'close' | 'sleep' | 'shutdown'; appid: number };
export interface GabeSteamPorts {
  alive(): boolean;
  currentAppId(): number;
  close?: (id: string, force: boolean) => void;
  sleep?: () => void;
  shutdown?: () => void;
}
export function dispatchGabeAction(action: GabeSteamAction, ports: GabeSteamPorts): void {
  if (!ports.alive()) throw new Error('Session stopped');
  if (action.action === 'close') {
    if (!Number.isInteger(action.appid) || action.appid <= 0 || action.appid >= 2 ** 32 || ports.currentAppId() !== action.appid || !ports.close) throw new Error('Running game changed or Steam unavailable');
    ports.close(String(action.appid), false);
  } else if (action.action === 'sleep' && ports.sleep) ports.sleep();
  else if (action.action === 'shutdown' && ports.shutdown) ports.shutdown();
  else throw new Error('Unsupported Steam action');
}
