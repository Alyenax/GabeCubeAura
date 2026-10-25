/** Read only data already present in SteamUI. Never request network statistics. */
export interface SteamDashboardStats { total_minutes?: number; achieved?: number; achievements_total?: number; }
export function steamDashboardStats(overview: unknown, details: unknown): SteamDashboardStats {
  const result: SteamDashboardStats = {};
  const total = (overview as any)?.minutes_playtime_forever;
  if (typeof total === 'number' && Number.isSafeInteger(total) && total >= 0 && total <= 9999999999) result.total_minutes = total;
  const counts = (details as any)?.achievements;
  if (typeof counts?.nAchieved === 'number' && typeof counts?.nTotal === 'number'
      && Number.isInteger(counts.nAchieved) && Number.isInteger(counts.nTotal)
      && counts.nAchieved >= 0 && counts.nAchieved <= counts.nTotal && counts.nTotal <= 100000) {
    result.achieved = counts.nAchieved; result.achievements_total = counts.nTotal;
  }
  return result;
}
export interface SteamAppDetailsStore {GetAppDetails:(appid:number)=>unknown;RegisterForAppData:(appid:number,callback:(details:unknown)=>void)=>{unregister?:()=>void};}
export function isSteamAppDetailsStore(value: unknown): value is SteamAppDetailsStore {
  return typeof (value as any)?.GetAppDetails === 'function' && typeof (value as any)?.RegisterForAppData === 'function';
}
