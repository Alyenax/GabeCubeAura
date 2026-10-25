/** Coalesce a slider, serialise saves, and flush the last choice on page exit. */
export function trailingSetting<T,R>(save:(value:T)=>Promise<R>,delay=400,
  schedule:(callback:()=>void,ms:number)=>ReturnType<typeof setTimeout> = setTimeout,
  unschedule:(timer:ReturnType<typeof setTimeout>)=>void = clearTimeout) {
  let pending:{value:T}|undefined,timer:ReturnType<typeof setTimeout>|undefined;
  let chain:Promise<unknown>=Promise.resolve();
  let outstanding=0;
  let generation=0;
  const flush=()=>{
    if(timer!==undefined){unschedule(timer);timer=undefined;}
    const selected=pending;pending=undefined;
    const ticket=generation;
    if(selected){outstanding++;chain=chain.catch(()=>undefined).then(()=>ticket===generation?save(selected.value):undefined).finally(()=>{outstanding--;});}
    return chain;
  };
  return {
    push(value:T){pending={value};if(timer!==undefined)unschedule(timer);timer=schedule(()=>void flush().catch(()=>undefined),delay);},
    flush,
    cancel(){generation++;pending=undefined;if(timer!==undefined){unschedule(timer);timer=undefined;}},
    pending:()=>pending!==undefined||outstanding>0,
  };
}
