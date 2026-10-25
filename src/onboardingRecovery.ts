import type {SetupSnapshot} from './onboardingApi';

/** An old polling response must not resurrect the error after recovery. */
export function setupReadGate(){
  let generation=0,recovering=false;
  return {
    read:()=>recovering?null:generation,
    accepts:(token:number|null)=>token!==null&&!recovering&&token===generation,
    beginRecovery:()=>{if(recovering)return false;recovering=true;generation++;return true;},
    endRecovery:()=>{recovering=false;},
    invalidate:()=>{generation++;},
  };
}

export function setupRecoveryMessage(code:string|undefined,fr:boolean){
  const messages:Record<string,readonly [string,string]>={
    draft_permissions:['Le dossier du guide ne peut pas être modifié : accès refusé ou disque en lecture seule. Ferme le guide et envoie le diagnostic GCA.','The setup folder cannot be changed: access denied or read-only storage. Close setup and send a GCA diagnostic.'],
    draft_unsafe:['Le brouillon a un propriétaire ou un type de fichier inattendu. Il a été conservé. Ferme le guide et envoie le diagnostic GCA.','The draft has an unexpected owner or file type. It was preserved. Close setup and send a GCA diagnostic.'],
    draft_archive_full:['Les sauvegardes du guide ont atteint leur limite. Aucune n’a été écrasée. Ferme le guide et envoie le diagnostic GCA.','Setup backups have reached their limit. None was overwritten. Close setup and send a GCA diagnostic.'],
    draft_schema:['Le format du brouillon n’est pas compatible. Tu peux en conserver une copie et repartir avec un nouveau brouillon.','The draft format is incompatible. You can keep a copy and start a new draft.'],
    draft_too_large:['Le brouillon dépasse la taille autorisée. Tu peux en conserver une copie et repartir avec un nouveau brouillon.','The draft exceeds the allowed size. You can keep a copy and start a new draft.'],
    draft_invalid:['Le brouillon enregistré est invalide. Tu peux en conserver une copie et repartir avec un nouveau brouillon.','The saved draft is invalid. You can keep a copy and start a new draft.'],
    draft_io:['Le fichier du guide est inaccessible. Rien n’a été réinitialisé. Ferme le guide et envoie le diagnostic GCA.','The setup file is inaccessible. Nothing was reset. Close setup and send a GCA diagnostic.'],
    draft_transport:['La récupération n’a pas pu être confirmée par le plugin. Rien n’a été appliqué aux réglages actifs. Réessaie ou ferme le guide.','The plugin could not confirm recovery. No active settings were applied. Retry or close setup.'],
  };
  return (messages[code||'draft_io']||messages.draft_io)[fr?0:1];
}

/** Recovery changes only the draft UI after an acknowledged, usable snapshot. */
export async function recoverSetupDraft(deps:{
  gate:ReturnType<typeof setupReadGate>;reset:()=>Promise<SetupSnapshot>;alive:()=>boolean;
  snapshot:(state:SetupSnapshot)=>void;recovered:(state:SetupSnapshot)=>void;failed:(code:string)=>void;
  timeoutMs?:number;
  pending?:()=>Promise<unknown>;
}){
  if(!deps.gate.beginRecovery())return;
  let timer:ReturnType<typeof setTimeout>|undefined;
  let expired=false;
  try{
    const deadline=new Promise<never>((_,reject)=>{timer=setTimeout(()=>{expired=true;reject(new Error('Recovery deadline'));},deps.timeoutMs??12000);});
    const operation=(async()=>{
      if(deps.pending)await deps.pending();
      if(expired||!deps.alive())throw new Error('Inactive recovery');
      return deps.reset();
    })();
    const state=await Promise.race([operation,deadline]);
    if(!deps.alive())return;
    if(!state||typeof state!=='object'||!state.draft||typeof state.draft!=='object'
      ||Array.isArray(state.draft)||typeof state.bar_detected!=='boolean'
      ||typeof state.faceplate_detected!=='boolean'||typeof state.faceplate_busy!=='boolean')throw new Error('Invalid recovery response');
    deps.snapshot(state);
    if(state.draft_reset_error||state.draft_error){
      deps.failed(state.draft_reset_error||state.draft_error_code||'draft_io');return;
    }
    deps.recovered(state);
  }catch{if(deps.alive())deps.failed('draft_transport');}
  finally{expired=true;clearTimeout(timer);deps.gate.endRecovery();}
}
