import {useEffect,useRef,useState} from 'react';
import {callable} from '@decky/api';
import {PanelSectionRow} from '../localized_ui';
import {QuickInlineChoice} from './QuickInlineChoice';

type Destination='home'|'game'|'both'|'none';
type BridgeState={present:boolean;compatible:boolean;revision:number;destination:Destination;context:'home'|'game';state:string;source_error?:string};
const getState=callable<[],BridgeState>('get_pixel_clocks_state');
const setDestination=callable<[destination:Destination,expected_revision:number],BridgeState>('set_pixel_clocks_destinations');
export const PIXEL_CLOCKS_DESTINATIONS=[
  {data:'home',label:'À l’accueil'}, {data:'game',label:'En jeu'},
  {data:'both',label:'Les deux'}, {data:'none',label:'Aucun'},
];
export function PixelClocksIntegration({active=true,french=false}:{active?:boolean;french?:boolean}){
  const[state,setState]=useState<BridgeState|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const sequence=useRef(0),mounted=useRef(true),working=useRef(false);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;sequence.current++;};},[]);
  useEffect(()=>{
    if(!active)return;
    let alive=true,inflight=false;
    const refresh=async()=>{if(inflight||working.current)return;inflight=true;const revision=sequence.current;try{const next=await getState();if(alive&&revision===sequence.current){setState(next);setError('');}}catch{if(alive&&revision===sequence.current)setError(french?'Liaison indisponible':'Connection unavailable');}finally{inflight=false;}};
    void refresh();const timer=setInterval(()=>void refresh(),1000);
    return()=>{alive=false;clearInterval(timer);};
  },[active,french]);
  if(!state||(!state.present&&state.destination==='none'))return null;
  const labels=french?PIXEL_CLOCKS_DESTINATIONS:[{data:'home',label:'At Home'},{data:'game',label:'In game'},{data:'both',label:'Both'},{data:'none',label:'None'}];
  const descriptions:Record<string,string>=french?{'fallback-failed':'Pixel Clocks et horloge de secours indisponibles','fallback-clock':'Pixel Clocks indisponible · horloge de secours','fallback-pending':'Pixel Clocks indisponible · préparation du secours','display-confirmed':'Affichage confirmé','prepared':'Préparé · transfert à venir','applied':'Choix enregistré','preparing':'Préparation…','connected':'Connecté','inactive':'En attente du contexte choisi','disconnected':'Pixel Clocks déconnecté','failed':'Échec de l’affichage','unconfirmed':'Affichage non confirmé','overridden':'En pause · priorité ou écran éteint'}:{'fallback-failed':'Pixel Clocks and backup clock unavailable','fallback-clock':'Pixel Clocks unavailable · backup clock','fallback-pending':'Pixel Clocks unavailable · preparing backup','display-confirmed':'Display confirmed','prepared':'Prepared · transfer pending','applied':'Choice saved','preparing':'Preparing…','connected':'Connected','inactive':'Waiting for selected context','disconnected':'Pixel Clocks disconnected','failed':'Display failed','unconfirmed':'Display unconfirmed','overridden':'Paused · priority or display off'};
  return <PanelSectionRow><div style={{maxWidth:'100%',minWidth:0}} data-pixel-clocks-integration>
    <QuickInlineChoice label={french?"Afficher Pixel Clocks":"Show Pixel Clocks"} selectedOption={state.destination} rgOptions={labels} disabled={busy}
      onChange={option=>{if(working.current)return;if(!state.compatible&&option.data!=='none'){setError(french?'Pixel Clocks indisponible · seul le retrait est possible':'Pixel Clocks unavailable · only removal is possible');return;}working.current=true;const serial=++sequence.current;const current=()=>mounted.current&&serial===sequence.current;setBusy(true);setError('');void setDestination(option.data as Destination,state.revision).then(next=>{if(current())setState(next);}).catch(()=>{if(!current())return;setError(french?'Choix modifié ailleurs · resynchronisation':'Choice changed elsewhere · resynchronizing');return getState().then(next=>{if(current())setState(next);}).catch(()=>undefined);}).finally(()=>{if(current()){sequence.current++;working.current=false;setBusy(false);}});}}/>
    <small role="status" aria-live="polite">{busy?(french?'Application…':'Applying…'):(descriptions[state.state]||state.state)}</small>
    {error?<small role="alert">{error}</small>:null}
  </div></PanelSectionRow>;
}
