import {useEffect,useRef,useState} from 'react';
import {Navigation,showModal,getGamepadNavigationTrees} from '@decky/ui';
import {ButtonItem,ConfirmModal,DialogButton,Focusable,Localized,PanelSection,PanelSectionRow,TextField} from '../localized_ui';
import {getFaceplateGameArtworkOverrides,resetFaceplateGameArtwork,type FaceplateGameArtworkOverride} from '../api';
import {artworkGamePath,GAME_ARTWORK_ROUTE,steamGameTitle} from '../game_artwork_menu';
import {takeArtworkNativeFocus,type ArtworkNativeNavigationTree} from '../faceplate_artwork_gallery';
import type {Status} from '../types';

export function GameArtworkOverview({status,setStatus}:{status:Status;setStatus:(next:Status)=>void}){
  const [entries,setEntries]=useState<FaceplateGameArtworkOverride[]>([]),[loading,setLoading]=useState(true);
  const [limit,setLimit]=useState(20),[query,setQuery]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState<number|null>(null);
  const alive=useRef(true),pending=useRef(false),chooser=useRef<HTMLDivElement|null>(null);const french=status.ui_language==='fr';
  const t=(en:string,fr:string)=>french?fr:en;
  const load=async()=>{try{const next=await getFaceplateGameArtworkOverrides();if(alive.current){setEntries(next.entries);setError('');}}catch{if(alive.current)setError(t('Could not read customized games. Try again.','Impossible de lire les jeux personnalisés. Réessaie.'));}finally{if(alive.current)setLoading(false);}};
  useEffect(()=>{alive.current=true;void load();return()=>{alive.current=false;};},[]);
  const open=(appid?:number)=>{Navigation.CloseSideMenus();Navigation.Navigate(appid?artworkGamePath(appid):GAME_ARTWORK_ROUTE);};
  const reset=(item:FaceplateGameArtworkOverride)=>{
    let modal:ReturnType<typeof showModal>|undefined;
    modal=showModal(<ConfirmModal strTitle={t('Use default Faceplate artwork?','Revenir à l’illustration Faceplate par défaut ?')}
      strDescription={t('This game will follow the default artwork. Prepared files and the Home display are kept.','Ce jeu suivra l’illustration par défaut. Les fichiers préparés et l’affichage à l’accueil sont conservés.')}
      strOKButtonText={t('Use default','Par défaut')} strCancelButtonText={t('Cancel','Annuler')}
      onCancel={()=>modal?.Close()} onOK={()=>{
        modal?.Close();if(!alive.current||pending.current)return;pending.current=true;setBusy(item.appid);setError('');
        void resetFaceplateGameArtwork(item.appid).then(async next=>{if(alive.current){setStatus(next);await load();
            if(typeof window!=='undefined')window.requestAnimationFrame(()=>{if(alive.current&&chooser.current)try{takeArtworkNativeFocus(chooser.current,(getGamepadNavigationTrees()||[]) as ArtworkNativeNavigationTree[]);}catch{/* Steam retains its native fallback. */}});}})
          .catch(()=>{if(alive.current)setError(t('The default could not be restored. Try again.','Le choix par défaut n’a pas pu être rétabli. Réessaie.'));})
          .finally(()=>{pending.current=false;if(alive.current)setBusy(null);});
      }}><p translate="no">{item.name||steamGameTitle(item.appid,`App ${item.appid}`)}</p></ConfirmModal>);
  };
  useEffect(()=>{setLimit(20);},[query]);
  const shown=entries.filter(item=>(item.name||String(item.appid)).toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  return <PanelSection title={t('Customized games','Jeux personnalisés')}>
    <PanelSectionRow><Localized><p style={{fontSize:'.85em',opacity:.8,lineHeight:1.5}}>
      Open a game’s menu in your Steam library and choose JSAUX Faceplate artwork. Only games with custom artwork or layout are listed here.
    </p></Localized></PanelSectionRow>
    <PanelSectionRow><Focusable ref={chooser} style={{width:'100%'}}><ButtonItem label={t('Customize a game','Personnaliser un jeu')}
      description={t('Choose an installed game, then select and adjust its artwork.','Choisis un jeu installé, puis sélectionne et ajuste son illustration.')}
      onClick={()=>open()}>{t('Choose a game','Choisir un jeu')}</ButtonItem></Focusable></PanelSectionRow>
    {loading?<PanelSectionRow><Localized><p>Loading customized games…</p></Localized></PanelSectionRow>:null}
    {!loading&&!entries.length&&!error?<PanelSectionRow><Localized><p>No customized games yet.</p></Localized></PanelSectionRow>:null}
    {entries.length>5?<PanelSectionRow><TextField label={t('Find a customized game','Chercher un jeu personnalisé')}
      value={query} onChange={event=>setQuery(event.currentTarget.value)}/></PanelSectionRow>:null}
    {shown.slice(0,limit).map(item=><PanelSectionRow key={item.appid}><Focusable style={{width:'100%',padding:'14px 0',borderTop:'1px solid rgba(255,255,255,.12)'}}>
      <div style={{display:'flex',gap:14,alignItems:'center',marginBottom:10}}>
        {item.thumb&&!/\.(?:mp4|webm)(?:\?|$)/i.test(item.thumb)?<img src={item.thumb} referrerPolicy="no-referrer" loading="lazy" alt=""
          style={{width:76,height:64,objectFit:'contain',borderRadius:8,background:'#090e15'}}/>:null}
        <div><div translate="no" style={{fontWeight:700}}>{item.name||steamGameTitle(item.appid,`App ${item.appid}`)}</div>
          <small style={{opacity:.7}}>{item.source==='layout'?t('Custom layout','Disposition personnalisée'):item.animated?t('Animated artwork','Illustration animée'):t('Custom artwork','Illustration personnalisée')}</small></div>
      </div>
      <Focusable flow-children="row" style={{display:'flex',gap:10,flexWrap:'wrap'}}>
        <DialogButton disabled={busy!==null} onClick={()=>open(item.appid)}>{t('Edit artwork','Modifier l’illustration')}</DialogButton>
        <DialogButton disabled={busy!==null} onClick={()=>reset(item)}>{busy===item.appid?t('Restoring…','Rétablissement…'):t('Use default','Par défaut')}</DialogButton>
      </Focusable>
    </Focusable></PanelSectionRow>)}
    {shown.length>limit?<PanelSectionRow><ButtonItem label={t('More customized games','Autres jeux personnalisés')} onClick={()=>setLimit(value=>value+20)}>{t('Show more','Afficher plus')}</ButtonItem></PanelSectionRow>:null}
    {error?<PanelSectionRow><div role="alert">{error} <DialogButton onClick={()=>{setLoading(true);void load();}}>{t('Try again','Réessayer')}</DialogButton></div></PanelSectionRow>:null}
  </PanelSection>;
}
