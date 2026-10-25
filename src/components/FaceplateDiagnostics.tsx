import type {ReactNode} from 'react';
import type {Status} from '../types';
import {Disclosure} from './Disclosure';

/** One troubleshooting view; an acknowledged transfer never claims visible playback. */
export function FaceplateDiagnostics({status,summaryShown=false}:{status:Status;summaryShown?:boolean}){
  const p=status.faceplate,r=p.routing,w=p.automation,f=p.flash_protection,x=p.last_transfer;
  const t=(en:string,fr:string)=>status.ui_language==='fr'?fr:en;
  const row=(en:string,fr:string,value:ReactNode)=><div><b>{t(en,fr)}: </b>{value??'—'}</div>;
  const words:Record<string,[string,string]>={
    idle:['Idle','Au repos'],pending:['Waiting','En attente'],preparing:['Preparing image','Préparation de l’image'],ready:['Ready','Prête'],error:['Failed','Échec'],unconfirmed:['Confirmation missing','Confirmation manquante'],
    failed:['Failed','Échec'],sending:['Sending','Envoi en cours'],confirmed:['Confirmed','Confirmé'],deferred:['Waiting to send','Envoi différé'],unknown:['Unknown','Inconnu'],persisted:['Saved','Enregistré'],fresh:['New history','Nouvel historique'],recovered:['Recovered','Récupéré'],missing:['Not found','Introuvable'],corrupt:['Unreadable','Illisible'],written:['Sent','Envoyé'],identical:['Already stored','Déjà enregistré'],reused:['Already stored','Déjà enregistré'],uncertain:['Not confirmed','Non confirmé'],
    weather:['Weather','Météo'],dashboard:['Weather Dashboard','Dashboard météo'],'artwork-dashboard':['Artwork Dashboard','Dashboard artwork'],artwork:['Game artwork','Image du jeu'],'native-clock':['Native clock','Horloge native'],'player-city':['Steam Players City','Steam Players City'],
  };
  const name=(value?:string)=>value?(words[value]?t(...words[value]):value):'—';
  const errors=[...new Set([status.faceplate_configuration_error,p.error,r.preparation.error,w.last_error,f?.persistence_error].filter((v):v is string=>Boolean(v)))];
  const today=p.upload_observability?.today_utc,journal=p.upload_observability?.journal??[],last=journal[journal.length-1];
  const section=(en:string,fr:string)=><h3 style={{fontSize:'1em',margin:'16px 0 6px'}}>{t(en,fr)}</h3>;
  return <Disclosure title="Faceplate diagnostics"><div style={{fontSize:'1em',lineHeight:1.5,width:'100%',overflowWrap:'anywhere'}}>
    {section('Connection','Connexion')}
    {row('USB connection','Connexion USB',!p.available?t('Not detected','Non détectée'):p.busy?t('Another app is using the Faceplate','Utilisée par une autre application'):t('Connected','Connectée'))}
    {row('USB port','Port USB',p.port||'—')}
    {row('Power','Alimentation',p.powered===true?t('On','Allumée'):p.powered===false?t('Off','Éteinte'):t('Not confirmed','Non confirmée'))}
    {!p.power_recovery?.suspended&&p.power_recovery?.route_state&&p.power_recovery?.route_state!=='idle'?row('Display recovery','Récupération de l’affichage',
      p.power_recovery?.route_state==='exhausted'?t('Automatic recovery stopped after three attempts. Retry with Power on.','Reprise automatique arrêtée après trois tentatives. Réessayez avec Allumer.'):
      p.power_recovery?.route_state==='retry-waiting'?t('Final USB confirmation missing. One automatic retry is scheduled.','Confirmation USB finale manquante. Un seul nouvel essai automatique est prévu.'):
      p.power_recovery?.route_state==='unconfirmed'?t('USB confirmation still missing. Automatic retry stopped. Use Power on to try again.','Confirmation USB toujours manquante. Reprise automatique arrêtée. Utilisez Allumer pour réessayer.'):
      t('Restoring the current image before powering on.','Restauration de l’image actuelle avant rallumage.')):null}
    {p.owners?.length?row('Used by','Utilisée par',p.owners.join(', ')):null}
    {p.detail&&!errors.includes(p.detail)?row('Device message','Message du périphérique',p.detail):null}
    {errors.map(message=><div key={message} role="alert" style={{color:'#ffb9ae'}}>{message}</div>)}

    {section('Display','Affichage')}
    {row('Automatic display','Affichage automatique',status.faceplate_lab_enabled?t('On','Activé'):t('Off','Désactivé'))}
    {row('Saved choices','Choix enregistrés',`${t('Home','Accueil')}: ${name(r.routes.home)} · ${t('In game','En jeu')}: ${name(r.routes.game)}`)}
    {row('Requested image','Image demandée',name(r.desired_scene))}
    {row('Prepared image','Image préparée',name(r.prepared_scene))}
    {row('Last USB-confirmed display','Dernier affichage confirmé par USB',name(r.effective_scene))}
    {w.busy&&w.active_scene?row('Current task','Tâche en cours',w.active_scene):null}
    {w.last_scene&&w.last_scene!==r.effective_scene?row('Last task','Dernière tâche',w.last_scene):null}
    {row('Image preparation','Préparation de l’image',name(r.preparation.state))}
    {w.last_result?.fallback?row('Replacement image','Image de remplacement',w.last_result.fallback):null}
    {w.last_result?.frames?row('Last image','Dernière image',w.last_result.automatic_background?t('Local Steam image','Image Steam locale'):`${w.last_result.frames} ${t('animation frames','images d’animation')}`):null}
    {w.last_result?.refresh_policy?row('Last information refresh','Dernière actualisation des informations',w.last_result.refresh_policy==='economy'?t('Every 5 minutes','Toutes les 5 minutes'):t('Every minute','Chaque minute')):null}
    {row('Weather graphics','Style de la météo','Realistic')}
    {p.last_asset?row('Last image file','Dernier fichier image',p.last_asset):null}

    {section('Transfers','Transferts')}
    {f&&!summaryShown?<>
      {row('Confirmed GIF transfers','Transferts GIF confirmés',`${f.session.confirmed} ${t('session','session')} · ${f.total.confirmed} ${t('total','au total')}`)}
      {row('Avoided / delayed / unconfirmed','Évités / différés / non confirmés',`${f.total.reused} / ${f.total.deferred} / ${f.total.uncertain}`)}
    </>:null}
    {row('Transfer status','État du transfert',w.busy||w.active_generation?t('In progress','En cours'):name(p.delivery?.state??'idle'))}
    {row('Waiting image','Image en attente',w.queued?t('Latest request queued','Dernière demande conservée'):t('None','Aucune'))}
    {row('Requests replaced','Demandes remplacées',w.dropped??'—')}
    {w.superseded_active?row('Cancelled after a display change','Annulés après changement d’affichage',w.superseded_active):null}
    {today&&[today.writes,today.identical,today.failed].some(value=>value!=null)?row('Today (UTC)','Aujourd’hui (UTC)',`${today.writes??'—'} ${t('sent','envoyés')} · ${today.identical??'—'} ${t('already stored','déjà présents')} · ${today.failed??'—'} ${t('failed','échoués')}`):null}
    {(!f||p.writes_session!==f.session.confirmed||p.writes_total!==f.total.confirmed)?row('Image-change counter','Compteur de changements d’image',`${p.writes_session} ${t('session','session')} · ${p.writes_total} ${t('recorded total','au total enregistré')}`):null}
    {(x?.total_ms||p.last_upload_ms)?row('Last transfer time','Durée du dernier transfert',`${x?.total_ms||p.last_upload_ms} ms`):null}
    {p.last_start_ack_ms?row('Start confirmed after','Démarrage confirmé après',`${p.last_start_ack_ms} ms`):null}
    {w.ack_ema_ms?row('Average USB response','Réponse USB moyenne',`${w.ack_ema_ms} ms`):null}
    {x?.total_ms?<>
      {row('USB mode','Mode USB',x.active_profile||x.configured_profile||'baseline')}
      {row('Transfer stages (ms)','Étapes du transfert (ms)',`${t('Check','Vérification')} ${x.preflight_ms??0} · ${t('Open','Ouverture')} ${x.begin_ms??0} · ${t('Send','Envoi')} ${x.chunks_ms??0} · ${t('Confirm','Validation')} ${x.finalize_ms??0}`)}
      {row('Data blocks','Blocs de données',x.chunks??0)}
    </>:null}
    {x?.end_timeout_seconds?row('Confirmation time limit','Délai maximal de confirmation',`${x.end_timeout_seconds.toFixed(1)} s`):null}
    {x?.already_stored?<div>{t('The image was already stored; its data was not sent again.','L’image était déjà enregistrée ; ses données n’ont pas été renvoyées.')}</div>:null}
    {x?.transfer_retries?row('Full retries','Nouvelles tentatives complètes',x.transfer_retries):null}
    {f?row('Saved transfer history','Historique des transferts',f.history_state==='ready'?t('Available','Disponible'):name(f.history_state)):null}
    {last?row('Last attempt','Dernière tentative',`${name(last.outcome)} · ${last.reason} · ${last.size_bytes} B · ${t('USB response','réponse USB')} ${last.ack_ms} ms · ${last.duration_ms} ms · ${t('Image ID','Identifiant image')} ${last.crc32}`):null}
    {f?.recent.length?<div style={{marginTop:6}}><b>{t('Recent transfers','Transferts récents')}</b>{f.recent.slice(-4).reverse().map((event,index)=><div key={`${event.at}:${index}`}>{new Date(event.at*1000).toLocaleTimeString()} · {name(event.scene)} · {name(event.outcome)} · {event.bytes} B</div>)}</div>:null}
    <p>{t('One animated GIF is one transfer. USB confirmation cannot tell us what is visible on the screen.','Un GIF animé compte pour un transfert. La confirmation USB ne permet pas de vérifier ce qui est visible à l’écran.')}</p>
  </div></Disclosure>;
}
