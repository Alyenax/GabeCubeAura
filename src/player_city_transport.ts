/** Official Steam API via Decky's supported transport, as used by PlayCount.
 * The backend leases polls and validates results; this never writes the panel.
 */
type Lease={request_id:string;appid:number};
type Options={claim:()=>Promise<Lease|null>;complete:(id:string,appid:number,payload:unknown,error:string)=>Promise<boolean>;
  fetch:(url:string,init:RequestInit)=>Promise<Response>};
export class PlayerCityTransport{
  private alive=false;
  private lifetime=0;
  private busy=false;
  private controller:AbortController|undefined;
  constructor(private options:Options){}
  start(){this.alive=true;this.lifetime++;}
  stop(){this.alive=false;this.lifetime++;this.controller?.abort();}
  async poll(){
    if(!this.alive||this.busy)return;
    this.busy=true;
    const lifetime=this.lifetime,current=()=>this.alive&&this.lifetime===lifetime;
    let timer:ReturnType<typeof setTimeout>|undefined;
    try{
      const lease=await this.options.claim();
      if(!current()||!lease)return;
      if(!Number.isInteger(lease.appid)||lease.appid<=0||lease.appid>0xffffffff||!/^[a-f0-9]{32}$/.test(lease.request_id))return;
      const controller=new AbortController();this.controller=controller;
      timer=setTimeout(()=>controller.abort(),6000);
      let payload:unknown=null,error='';
      try{
        const response=await this.options.fetch(`https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid=${lease.appid}`,
          {method:'GET',headers:{Accept:'application/json'},signal:controller.signal,redirect:'error'});
        if(!response.ok){error=`http_${response.status}`;try{await response.body?.cancel();}catch{/* Keep the HTTP status. */}}
        else{
          const chunks:Uint8Array[]=[];let length=0;
          const reader=response.body?.getReader();
          if(reader){
            try{
              while(true){const {done,value}=await reader.read();if(done)break;
                length+=value.length;if(length>8192){error='response_too_large';await reader.cancel();break;}chunks.push(value);}
            }finally{reader.releaseLock();}
            if(!error){const bytes=new Uint8Array(length);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
              payload=JSON.parse(new TextDecoder().decode(bytes));}
          }else{const text=await response.text();if(text.length>8192)error='response_too_large';else payload=JSON.parse(text);}
          // Report only the two public numeric fields, never response headers or error text.
          const data=payload as {response?:{result?:unknown;player_count?:unknown}}|null;
          if(!error){const result=data?.response;
            if(result?.result!==1||!Number.isInteger(result.player_count)||Number(result.player_count)<0||Number(result.player_count)>0xffffffff)error='response_invalid';
            else payload={response:{result:1,player_count:result.player_count}};}
        }
      }catch(reason){error=controller.signal.aborted?'timeout':reason instanceof SyntaxError?'response_invalid':'connection';}
      if(current())await this.options.complete(lease.request_id,lease.appid,error?null:payload,error);
    }catch{/* Retry scheduling and request expiry belong to the backend. */}
    finally{if(timer!==undefined)clearTimeout(timer);this.controller=undefined;this.busy=false;}
  }
}
