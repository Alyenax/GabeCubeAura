import type {Status} from './types';
export type ClockContext='home'|'game';
export type ClockEntry={id:string;label:string;private:boolean;family?:string;movement_seconds:number;packet_seconds:number};
export type ClockStatus={catalog:ClockEntry[];selected:string;context:ClockContext;state:string;server_now:number;
  cadence?:'conservative'|'minute';packet_seconds?:number;nominal_transfers_per_hour?:number;
  next_gif_at:number|null;next_movement_at:number|null;estimated_display_at:number|null;valid_until:number|null;
  bytes:number;transfer_seconds:number;ack_offset_ms:number|null;optical_verified:false;error:string};
export const CLOCK_TRANSFER_NOTICE='Clock transfers take several seconds (around 8 KiB/s). Conservative mode refreshes about every four minutes; Fixed minute refreshes about once a minute. Preparation anticipates the transfer; display timing still needs checking.';
export function clockCountdown(deadline:number|null|undefined,now:number):string{
  if(deadline==null)return '-';
  const seconds=Math.max(0,Math.ceil(deadline-now));
  return `${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;
}
export function selectedClock(status:Status,context:ClockContext){return context==='home'?status.faceplate_clock_home:status.faceplate_clock_game;}
