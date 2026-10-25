/** Ordered Steam observations, not a playback/USB queue.
 *
 * A polling RPC already dispatched to Decky can finish after a native exit
 * notification. One in-flight RPC prevents that older active observation from
 * arriving last and reviving a closed activation. Keep at most an inactive edge
 * and the latest subsequent state while transport is busy.
 */
export interface ScreensaverContext {
  active:boolean;
  detection:'available'|'waiting'|'error'|'unavailable';
  detail:string;
}
interface Pending {
  value:ScreensaverContext;
  current:()=>boolean;
  done:()=>void;
}
export class ScreensaverContextQueue {
  private pending:Pending[]=[];
  private draining=false;
  constructor(private send:(value:ScreensaverContext)=>Promise<unknown>) {}

  submit(value:ScreensaverContext,current:()=>boolean=()=>true):Promise<void> {
    return new Promise(resolve=>{
      const entry={value,current,done:resolve};
      // A real negative edge cannot be swallowed by a newer positive poll:
      // the broker must first close the previous activation. Repeated positive
      // polls need only one latest snapshot; a later negative replaces all.
      const retained=value.active?this.pending.filter(item=>!item.value.active):[];
      for(const item of this.pending)if(!retained.includes(item))item.done();
      this.pending=[...retained.slice(-1),entry];
      void this.drain();
    });
  }

  private async drain() {
    if(this.draining)return;
    this.draining=true;
    try {
      while(this.pending.length){
        const entry=this.pending.shift()!;
        try {if(entry.current())await this.send(entry.value);}
        catch {/* Existing backend freshness expires; never retry old evidence. */}
        finally {entry.done();}
      }
    } finally {this.draining=false;}
  }
}
