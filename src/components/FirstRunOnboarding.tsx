import {useEffect,useRef,useState,type CSSProperties} from 'react';
import {DialogBody,DialogHeader,getGamepadNavigationTrees} from '@decky/ui';
import {DialogButton,DropdownItem,Focusable,ScrollPanel,SliderField,TextField,ToggleField} from '../localized_ui';
import {FullPageSection as PanelSection,FullPageRow as PanelSectionRow} from '../full_page_ui';
import {completeOnboarding,getOnboarding,resetOnboardingDraft,saveOnboardingDraft,setupSteps,type SetupDraft,type SetupSnapshot,type SetupStep} from '../onboardingApi';
import {getStatus,previewDisplayPreset,stopDisplayPresetPreview,searchWeatherCities,setSteamGridDBApiKey,validateSteamGridDBApiKey} from '../api';
import type {Status,WeatherLocation} from '../types';
import {createSetupPreview,type PresetPreview} from '../onboardingPreview';
import {setupNeeds} from '../setupFlow';
import {finishSetupWithFaceplate,setupActivationMessage} from '../setupActivation';
import {takeArtworkNativeFocus,type ArtworkNativeNavigationTree} from '../faceplate_artwork_gallery';
import {FACEPLATE_GAME_OPTIONS,isDashboardChoice,quickFaceOptions} from '../faceplate_choices';
import {QUICK_CONTROL_CSS} from './QuickAction';
import {recoverSetupDraft,setupReadGate,setupRecoveryMessage} from '../onboardingRecovery';

const shell:CSSProperties={width:'100%',height:'100%',minHeight:0,display:'flex',flexDirection:'column',paddingBottom:'calc(88px + env(safe-area-inset-bottom, 0px))',boxSizing:'border-box',overflow:'hidden',background:'var(--gpSystemDarkestGrey,#0e141b)',color:'var(--gpSystemLightestGrey,#dcdedf)'};
const viewportCSS='.gca-onboarding-content > *{height:100%;max-height:100%;min-height:0;box-sizing:border-box}';
const card:CSSProperties={margin:'16px 0',minWidth:0};
const choices=[['custom','Garder les réglages de départ','Keep initial settings'],['moderate','Modéré','Moderate'],['atmosphere','Atmosphère','Atmosphere'],['signals','Signaux','Signals'],['immersive','Immersif','Immersive']] as const;
const descriptions={
  custom:['Conserver les couleurs, effets et réglages proposés ; les étapes suivantes restent obligatoires.','Keep the supplied colours, effects and settings; the following steps are still required.'],
  moderate:['Customization+ à l’accueil, couleurs du jeu en jeu.','Customization+ at Home, game artwork colours in games.'],
  atmosphere:['Météo à l’accueil, Slow Prism en attendant la météo ; couleurs du jeu en jeu.','Weather at Home, Slow Prism while weather is unavailable; game artwork colours in games.'],
  signals:['État des manettes à l’accueil, CPU/GPU en jeu.','Controller status at Home, CPU/GPU in games.'],
  immersive:['Audio Sync à l’accueil, Screen Sync en jeu.','Audio Sync at Home, Screen Sync in games.'],
};
function initial(status:Status):SetupDraft{return{step:'ambiance',preset:choices.some(item=>item[0]===status.display_preset)?status.display_preset as SetupDraft['preset']:'custom',brightness:status.light_bar_day_brightness||15,
  night:status.night_mode_enabled,night_percentage:status.night_mode_brightness||75,city:status.weather_location,
  faceplate_requested:null,home:'dashboard',game:status.faceplate.routing.routes.game};}

/** Native setup; temporary bar previews never persist the selected recipe. */
export function FirstRunOnboarding({status,setStatus,onClose,openBrowser,faceplateOnly=false}:{faceplateOnly?:boolean;status:Status;setStatus:(s:Status)=>void;onClose:()=>void;openBrowser:(url:string)=>void}){
  const [device,setDevice]=useState<SetupSnapshot|null>(null),[draft,setDraft]=useState<SetupDraft>(()=>initial(status));
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const [cityQuery,setCityQuery]=useState(''),[cities,setCities]=useState<WeatherLocation[]>([]),[apiKey,setApiKey]=useState('');
  const alive=useRef(true),draftRef=useRef(draft),saveTimer=useRef<number|undefined>(undefined),saveChain=useRef<Promise<unknown>>(Promise.resolve());
  const panelRef=useRef<HTMLDivElement>(null);
  const loaded=useRef(false);
  const readGate=useRef(setupReadGate()),pendingAction=useRef(false);
  const [notice,setNotice]=useState('');
  const [activating,setActivating]=useState(false);
  const [preview,setPreview]=useState<PresetPreview|null>(null),[previewError,setPreviewError]=useState(false),[replay,setReplay]=useState(0);
  const previewSession=useRef<ReturnType<typeof createSetupPreview>|null>(null);
  const fr=status.ui_language==='fr',t=(a:string,b:string)=>fr?a:b;
  const scopedDevice=(snapshot:SetupSnapshot)=>faceplateOnly?{...snapshot,bar_detected:false}:snapshot;
  const refresh=async()=>{const token=readGate.current.read();if(token===null)return;
    const next=await getOnboarding();if(alive.current&&readGate.current.accepts(token)){
    if(!loaded.current){const value={...initial(status),...next.draft,home:'dashboard' as const};
      const steps=setupSteps(value,scopedDevice(next));if(faceplateOnly&&value.faceplate_requested===null)value.step=steps[0];if(!steps.includes(value.step))value.step=steps[0];
      draftRef.current=value;setDraft(value);loaded.current=true;setError('');}
    setDevice(next);
  }return next;};
  useEffect(()=>{alive.current=true;void refresh().catch(e=>{if(alive.current)setError(String(e));});
    const timer=window.setInterval(()=>void refresh().catch(()=>undefined),4000);
    return()=>{alive.current=false;readGate.current.invalidate();window.clearTimeout(saveTimer.current);window.clearInterval(timer);};
  },[]);
  useEffect(()=>{
    // A NEW step starts at the top of our own viewport. In-step actions and
    // metadata polling do not touch focus/scroll, nor Steam's surrounding tree.
    let frame=0,attempts=0;
    const focusStep=()=>{
      const panel=panelRef.current;if(!panel?.isConnected)return;
      if(attempts===0){
        panel.scrollTop=0;
        for(const node of panel.querySelectorAll<HTMLElement>('div')){
          if(node.scrollHeight>node.clientHeight&&/auto|scroll/.test(getComputedStyle(node).overflowY))node.scrollTop=0;
        }
      }
      const controls=Array.from(panel.querySelectorAll<HTMLElement>(
        'button:not(:disabled),input:not(:disabled),select:not(:disabled),[role="button"]:not([aria-disabled="true"]),[role="slider"]:not([aria-disabled="true"])'))
        .filter(node=>node.getClientRects().length>0);
      try{
        const trees=(getGamepadNavigationTrees()||[]) as ArtworkNativeNavigationTree[];
        if(controls.some(control=>takeArtworkNativeFocus(control,trees)))return;
      }catch{/* Keyboard fallback stays strictly inside this component. */}
      if(++attempts<8){frame=window.requestAnimationFrame(focusStep);return;}
      controls[0]?.focus({preventScroll:true});
    };
    frame=window.requestAnimationFrame(focusStep);
    return()=>window.cancelAnimationFrame(frame);
  },[draft.step,Boolean(device),Boolean(device?.draft_error)]);
  useEffect(()=>{
    setPreview(null);setPreviewError(false);
    if(draft.step!=='ambiance'||draft.preset==='custom'||!device?.bar_detected||device.draft_error)return;
    const session=createSetupPreview({start:previewDisplayPreset,stop:stopDisplayPresetPreview,read:getStatus,
      frame:setPreview,failed:()=>setPreviewError(true)});
    previewSession.current=session;void session.start(draft.preset);
    return()=>{if(previewSession.current===session)previewSession.current=null;void session.stop();};
  },[draft.step,draft.preset,Boolean(device?.bar_detected),Boolean(device?.draft_error),replay]);
  const change=(patch:Partial<SetupDraft>)=>{
    if(device?.draft_error)return;
    const value={...draftRef.current,...patch};draftRef.current=value;setDraft(value);
    window.clearTimeout(saveTimer.current);
    saveTimer.current=window.setTimeout(()=>{
      saveChain.current=saveChain.current.catch(()=>undefined).then(()=>saveOnboardingDraft(value))
        .catch(e=>{if(alive.current)setError(String(e));});
    },250);
  };
  const run=async(action:()=>Promise<unknown>)=>{if(pendingAction.current)return;pendingAction.current=true;setBusy(true);setError('');try{await action();}catch(e){if(alive.current)setError(String(e).replace(/^Error:\s*/,''));}finally{pendingAction.current=false;if(alive.current)setBusy(false);}};
  const recoverDraft=()=>void run(async()=>{
    window.clearTimeout(saveTimer.current);
    await recoverSetupDraft({gate:readGate.current,reset:resetOnboardingDraft,alive:()=>alive.current,
      pending:()=>saveChain.current.catch(()=>undefined),
      snapshot:setDevice,failed:code=>setError(setupRecoveryMessage(code,fr)),
      recovered:snapshot=>{
        const value={...initial(status),...snapshot.draft,home:'dashboard' as const};value.step=setupSteps(value,scopedDevice(snapshot))[0];
        draftRef.current=value;setDraft(value);loaded.current=true;setError('');
        setNotice(t('Le guide peut reprendre. Tes réglages actifs sont inchangés.','Setup can continue. Your active settings are unchanged.'));
      }});
  });
  const steps=device?setupSteps(draft,scopedDevice({...device,faceplate_detected:device.faceplate_detected||draft.step==='faceplate'})):[];
  const visiblePreview=preview?.preset===draft.preset?preview:null;
  const rgb=visiblePreview?.colors??[];
  const at=steps.indexOf(draft.step);
  const go=(step:SetupStep)=>{setApiKey('');setError('');change({step});};
  const next=()=>{const index=steps.indexOf(draft.step);go(steps[index<0?steps.length-1:Math.min(index+1,steps.length-1)]);};
  const finish=()=>void run(async()=>{window.clearTimeout(saveTimer.current);await previewSession.current?.stop();await saveChain.current.catch(()=>undefined);
    const choice=draftRef.current;
    try {
      const selected=faceplateOnly?{faceplate_requested:choice.faceplate_requested,home:choice.home,game:choice.game,city:choice.city}:choice;
      const nextStatus=await finishSetupWithFaceplate(selected,{apply:completeOnboarding,read:getStatus,
        publish:setStatus,alive:()=>alive.current,waiting:()=>setActivating(true)});
      if(nextStatus&&alive.current)onClose();
    } catch(error) { throw new Error(setupActivationMessage(error,fr)); }
    finally {if(alive.current)setActivating(false);}
  });
  const label=(step:SetupStep)=>({ambiance:t('Votre ambiance','Your experience'),brightness:t('Luminosité','Brightness'),faceplate:t('Votre faceplate','Your faceplate'),services:t('Images et météo','Images and weather'),review:t('Récapitulatif','Review')} as Partial<Record<SetupStep,string>>)[step]??t('Récapitulatif','Review');
  const action=(text:string,onClick:()=>void,disabled=false)=><div style={{margin:'10px 0'}}><DialogButton
    className="gca-quick-action" disabled={busy||disabled} onClick={onClick}>{text}</DialogButton></div>;
  const keyStatus=status.faceplate.steamgriddb;
  const {weather:weatherNeeded,artwork:artNeeded}=device?setupNeeds(draft,scopedDevice(device)):{weather:false,artwork:false};
  const enabledNext=draft.step==='faceplate'&&device?.faceplate_detected?draft.faceplate_requested!==null:true;
  return <Focusable ref={panelRef} style={shell} flow-children="column" aria-label="GabeCubeAura guided setup">
    <style>{viewportCSS}</style>
    <div className="gca-onboarding-content" data-setup-scroll style={{flex:'1 1 0%',minHeight:0,overflow:'hidden'}}><ScrollPanel><DialogBody><div style={{maxWidth:1040,margin:'0 auto',padding:'24px clamp(22px,5vw,70px) 24px'}}>
    <style>{QUICK_CONTROL_CSS}</style>
    <header style={{display:'flex',justifyContent:'space-between',gap:18,flexWrap:'wrap',marginBottom:20}}>
      <div><strong style={{fontSize:24}}>GabeCubeAura</strong><div style={{opacity:.7}}>{faceplateOnly?t('Configuration de la faceplate','Faceplate setup'):t('Première utilisation','First-time setup')}</div></div>
      <div style={{opacity:.75}}>{device?.bar_detected?'Steam Machine':'SteamOS'}{device?.faceplate_detected?' · JSAUX':''}</div>
    </header>
    {device?.draft_storage==='memory'?<div role="status" style={card}>{t('Le guide peut continuer. La progression est gardée pour cette session ; après un redémarrage, il faudra peut-être reprendre le guide.','Setup can continue. Progress is kept for this session; after a restart you may need to start setup again.')}</div>:null}
    {notice?<div role="status" style={card}>{notice}</div>:null}
    {activating?<p role="status">{t('Activation de la Faceplate… Attente de la confirmation du transfert.','Activating Faceplate… Waiting for transfer confirmation.')}</p>:null}
      {error?<div role="alert" style={{...card,color:'#ffb9ae'}}>{error}</div>:null}
    {!device?<div style={card}><p>{error||t('Lecture de votre configuration…','Reading your configuration…')}</p>{action(t('Réessayer','Retry'),()=>void run(refresh))}</div>:device.draft_error?<div style={card}>
      <p role="alert">{t('Le brouillon ne peut pas être relu. Votre configuration active reste intacte.','The draft could not be read. Your active configuration is unchanged.')}</p>
      <p>{setupRecoveryMessage(device.draft_error_code,fr)}</p>
      {action(busy?t('Récupération en cours…','Recovering…'):t('Archiver le brouillon et recommencer','Archive draft and start again'),recoverDraft)}
      {action(t('Fermer le guide sans rien changer','Close setup without changes'),onClose)}
      <small>{t('Conserve une copie du brouillon invalide. Ne supprime aucun réglage, téléchargement ou fichier média.','Keeps a copy of the invalid draft. No settings, downloads or media are deleted.')}</small>
    </div>:<>
      <div aria-label={t('Étapes','Steps')} style={{display:'flex',flexWrap:'wrap',gap:8,marginBottom:22}}>{steps.map((step,i)=><span key={step} aria-current={draft.step===step?'step':undefined}
        style={{padding:'8px 12px',fontSize:14,fontWeight:step===draft.step?600:400}}>{i+1}. {label(step)}</span>)}</div>
      <DialogHeader>{label(draft.step)}</DialogHeader>
      {draft.step==='ambiance'?<>
        <p>{t('Un point de départ pour l’accueil et les jeux. Vous pourrez tout changer ensuite.','A starting point for Home and games. Everything can be changed later.')}</p>
        <div style={{display:'grid',gridTemplateColumns:'repeat(2,minmax(0,1fr))',gap:12}}>{choices.map(([value,french,english])=><DialogButton key={value} disabled={busy} onClick={()=>{change({preset:value});if(value===draft.preset)setReplay(n=>n+1);}}
          aria-pressed={draft.preset===value} style={{textAlign:'left',minHeight:110}}><strong>{draft.preset===value?'● ':'○ '}{fr?french:english}</strong><div style={{fontSize:14,marginTop:8}}>{descriptions[value][fr?0:1]}</div></DialogButton>)}</div>
        {draft.preset!=='custom'?<>
        <div role="img" aria-label={t('Aperçu animé 17 LED','17 LED live preview')} data-preview-preset={visiblePreview?.preset??''} data-preview-on-bar={Boolean(visiblePreview?.on_bar)} style={{display:'flex',gap:6,...card}}>{Array.from({length:17},(_,i)=><span key={i} style={{height:20,flex:1,minWidth:0,borderRadius:7,background:`rgb(${(rgb[i]??[0,0,0]).join(',')})`}}/>)}</div>
        <p role="status">{previewError?t('L’aperçu est indisponible. Réessayez ; vous pouvez continuer le guide.','Preview is unavailable. Retry, or continue setup.'):
          visiblePreview?.active?visiblePreview.on_bar?t('Aperçu sur la barre','Preview on the light bar')+` · ${visiblePreview.phase||(status.game?.appid>0?t('En jeu','In game'):t('À l’accueil','At Home'))} · ${Math.ceil(visiblePreview.remaining_s)} s`:
          t('Aperçu demandé · en attente de la barre. Une priorité Steam peut le suspendre.','Preview requested · waiting for the light bar. Steam priority may suspend it.'):
          t('Sélectionnez une ambiance pour voir son animation sur la barre.','Select an experience to see its animation on the light bar.')}</p>
        {draft.preset==='immersive'?<p>{t('Démonstration : Slow Prism, puis Screen Sync. Aucun son ni capture d’écran n’est nécessaire.','Demo: Slow Prism, then Screen Sync. No audio or screen capture is needed.')}</p>:null}
        {draft.preset==='atmosphere'?<p>{t('Météo réelle si disponible ; sinon démonstration Slow Prism sans capture audio.','Live weather when available; otherwise a Slow Prism demo without audio capture.')}</p>:null}
        {draft.preset==='signals'?<p>{t('Démonstration avec deux manettes, même avant leur connexion.','Two-controller demo, even before controllers are connected.')}</p>:null}
        {action(t('Rejouer l’aperçu · 10 s','Replay preview · 10 s'),()=>setReplay(n=>n+1),!device.bar_detected)}
        <small>{t('L’aperçu est temporaire. La luminosité et les réglages enregistrés restent inchangés jusqu’à la confirmation.','Preview is temporary. Brightness and saved settings stay unchanged until confirmation.')}</small>
        </>:null}
      </>:null}
      {draft.step==='brightness'?<PanelSection>
        <PanelSectionRow><SliderField label={t('Luminosité de la barre','Light bar brightness')} min={1} max={255} step={1} value={draft.brightness} showValue valueSuffix="/255" onChange={brightness=>change({brightness})}/></PanelSectionRow>
        {draft.brightness<8?<PanelSectionRow><div role="note" style={{color:'#ffaeaa'}}>{t('Sous 8/255, certains effets peuvent être très peu visibles.','Below 8/255 some effects may be difficult to see.')}</div></PanelSectionRow>:null}
        <PanelSectionRow><ToggleField label={t('Diminuer le soir','Dim in the evening')} checked={draft.night} onChange={night=>change({night})}/></PanelSectionRow>
        {draft.night?<PanelSectionRow><SliderField label={t('Luminosité de nuit','Night brightness')} min={1} max={100} step={1} value={draft.night_percentage} showValue valueSuffix="%" onChange={night_percentage=>change({night_percentage})}/>
          <p>{t('La ville sera choisie une seule fois pour la météo et le coucher du soleil.','Choose a city once for both weather and sunset.')}</p></PanelSectionRow>:null}
      </PanelSection>:null}
      {draft.step==='faceplate'?<div style={card}>
        {!device.faceplate_detected?<p role="status">{t('Faceplate débranchée. Vos choix sont conservés ; aucun envoi ne sera déclenché.','Faceplate disconnected. Your choices are kept; nothing will be sent.')}</p>:<>
          <p>{t('La détection seule ne change ni l’image ni la luminosité.','Detection alone changes neither the picture nor brightness.')}</p>
          {device.faceplate_busy?<p role="status">{t('Port occupé. Configurez vos choix ; aucun contrôle concurrent ne sera tenté.','Port busy. Save your choices; no competing access will be attempted.')}</p>:null}
          {action((draft.faceplate_requested===true?'● ':'○ ')+t('Oui, la configurer','Yes, configure it'),()=>change({faceplate_requested:true}))}
          {action((draft.faceplate_requested===false?'● ':'○ ')+t('Pas maintenant','Not now'),()=>change({faceplate_requested:false}))}
          {draft.faceplate_requested?<>
            <p>{t('À l’accueil : Dashboard Weather','At Home: Dashboard Weather')}</p>
            <p>{t('Aucun artwork n’est fourni. Pour utiliser un artwork à l’accueil, créez-le puis appliquez-le depuis Réglages → Faceplate JSAUX → Artwork.','No artwork is included. To use artwork at Home, create and apply your own in Settings → Faceplate JSAUX → Artwork.')}</p>
            <DropdownItem label={t('En jeu','In game')} selectedOption={draft.game} rgOptions={[...FACEPLATE_GAME_OPTIONS,{data:'keep',label:t('Ne pas modifier mon choix actuel','Keep my current choice')}]} onChange={o=>change({game:o.data as SetupDraft['game']})}/>
            {isDashboardChoice(draft.home)||isDashboardChoice(draft.game)?<p style={{color:'#ffd27a'}}>{t('Voir l’onglet Dashboard pour paramétrer ses choix.','See the Dashboard tab to configure your choices.')}</p>:null}
            <p>{t('Pas de CPU/GPU sur la matrice. Les nouveaux Dashboard n’affichent pas l’heure par défaut. L’horloge native reste un mode distinct.','No CPU/GPU on the matrix. New Dashboards hide the clock by default. Native clock remains a separate mode.')}</p>
          </>:null}
        </>}
      </div>:null}
      {draft.step==='services'?<>
        {weatherNeeded?<PanelSection title={t('Votre météo','Your weather')}><PanelSectionRow><p>{t('Sans clé API. Cette ville sert aussi au mode nuit.','No API key. This city is also used for night mode.')}</p>
          {draft.city?<p>{draft.city.name}, {draft.city.country}</p>:null}<TextField label={t('Ville ou code postal','City or postal code')} value={cityQuery} onChange={e=>setCityQuery(e.currentTarget.value)}/>
          {action(t('Rechercher','Search'),()=>void run(async()=>setCities((await searchWeatherCities(cityQuery)).results.slice(0,5))),!cityQuery.trim())}</PanelSectionRow>
          {cities.map(city=><PanelSectionRow key={`${city.latitude}:${city.longitude}`}>{action(`${city.name}, ${city.country}`,()=>{change({city});setCities([]);})}</PanelSectionRow>)}
          {!draft.city?<PanelSectionRow><p>{t('Vous pouvez continuer sans ville. La météo restera en attente de sa configuration.','Continue without a city if you prefer. Weather will wait until a city is configured.')}</p></PanelSectionRow>:null}
        </PanelSection>:null}
        {artNeeded?<PanelSection title="SteamGridDB"><PanelSectionRow><p>{t('Facultatif. Les images Steam locales restent utilisables lorsqu’elles existent. Cette clé sert uniquement aux illustrations.','Optional. Local Steam images remain usable when available. This key is used only for artwork.')}</p>
          {action(t('Obtenir ma clé','Get my key'),()=>openBrowser('https://www.steamgriddb.com/profile/preferences/api'))}
          <TextField label={t('Clé API personnelle','Personal API key')} bIsPassword value={apiKey} onChange={e=>setApiKey(e.currentTarget.value)} />
          {action(t('Enregistrer et vérifier','Save and verify'),()=>void run(async()=>{const key=apiKey.trim();setApiKey('');setStatus(await setSteamGridDBApiKey(key));}),apiKey.trim().length<16)}
          <p role="status" style={keyStatus.validation_state==='validated'?{color:'#93f7a7'}:undefined}>{keyStatus.validation_state==='validated'?<><span aria-hidden="true">✓ </span>{t('Connexion vérifiée','Connection verified')}</>:keyStatus.configured?t('Clé enregistrée · connexion à vérifier','Key saved · connection not verified'):t('Aucune clé enregistrée','No key saved')}</p>
          {keyStatus.configured?action(t('Vérifier la connexion','Verify connection'),()=>void run(async()=>setStatus(await validateSteamGridDBApiKey()))):null}
          {keyStatus.validation_detail?<div role="status">{keyStatus.validation_detail}</div>:null}
        </PanelSectionRow></PanelSection>:null}
      </>:null}
      {draft.step==='review'?<div style={card}>
        <p>{t('Vérifiez ce qui sera activé. Tout reste modifiable ensuite.','Review what will be enabled. Everything stays editable later.')}</p>
        {device.bar_detected&&!faceplateOnly?<div>{t('Barre','Light bar')} : {choices.find(item=>item[0]===draft.preset)?.[fr?1:2]??draft.preset} · {draft.brightness}/255 {action(t('Modifier la lumière','Edit lighting'),()=>go('ambiance'))}</div>:null}
        {device.faceplate_detected?<div>JSAUX : {draft.faceplate_requested?`${quickFaceOptions(false,status.ui_language==='fr').find(item=>item.data===draft.home)?.label??draft.home} · ${quickFaceOptions(true,status.ui_language==='fr').find(item=>item.data===draft.game)?.label??t('Choix actuel conservé','Current choice kept')}`:t('Non activée','Not enabled')}{action(t('Modifier les affichages','Edit displays'),()=>go('faceplate'))}</div>:null}
        {weatherNeeded?<p>{draft.city?`${draft.city.name}, ${draft.city.country}`:t('Ville à renseigner plus tard','City to configure later')}</p>:null}
        {artNeeded?<p>SteamGridDB : {keyStatus.validation_state==='validated'?t('vérifiée','verified'):t('facultatif · sources Steam locales','optional · local Steam sources')}</p>:null}
        <p>{t('Vos choix seront enregistrés après confirmation.','Your choices will be saved after confirmation.')}</p>
        {device.faceplate_detected&&draft.faceplate_requested?<p>{t('Les affichages JSAUX suivent leurs protections. Decky Animated Screensaver se configure séparément.','JSAUX displays follow their protections. Configure Decky Animated Screensaver separately.')}</p>:null}
      </div>:null}
      {device.recovery_error?<div role="alert" style={{...card,color:'#ffb9ae'}}>{t('Une configuration interrompue doit être vérifiée. Vos fichiers sont conservés.','An interrupted setup needs attention. Your files have been preserved.')} {device.recovery_error}</div>:null}
    </>}
    </div></DialogBody></ScrollPanel></div>
    {device&&!device.draft_error?<div data-setup-actions style={{flex:'0 0 auto',boxSizing:'border-box',width:'100%',maxWidth:1040,margin:'0 auto',padding:'8px clamp(22px,5vw,70px) 12px',borderTop:'1px solid rgba(255,255,255,.15)'}}>
      <Focusable flow-children="row" style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(180px,1fr))',gap:12}}>
        {draft.step==='review'?action(t('Confirmer et terminer','Confirm and finish'),finish):action(t('Continuer','Continue'),next,!enabledNext)}
        {at>0?action(t('Retour','Back'),()=>go(steps[at-1])):faceplateOnly?action(t('Fermer','Close'),onClose):null}
        {draft.step==='services'?action(t('Configurer ces services plus tard','Set up services later'),next):null}
      </Focusable>
      <small style={{opacity:.7}}>{faceplateOnly?t('Vos choix de faceplate seront appliqués après confirmation.','Faceplate choices apply after confirmation.'):t('Seule la barre joue les aperçus temporaires. Les réglages et la Faceplate seront appliqués à la confirmation.','Only the light bar plays temporary previews. Settings and Faceplate choices apply after confirmation.')}</small>
    </div>:null}
  </Focusable>;
}
