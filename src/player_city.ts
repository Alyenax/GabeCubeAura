import type {Status} from './types';

/** Same readout in both existing selectors; never describes a delayed image as fresh. */
export function playerCitySummary(status:Status):string{
  const fr=status.ui_language==='fr',city=status.faceplate.player_city,sample=city?.sample;
  const t=(english:string,french:string)=>fr?french:english;
  if(!(status.game.appid>0&&status.game.appid<=0xffffffff))
    return status.game.title?t('This game has no compatible Steam AppID; previous image kept.','Ce jeu n’a pas d’AppID Steam compatible ; image précédente conservée.')
      :t('Start a Steam game to show its player city.','Lancez un jeu Steam pour afficher sa ville de joueurs.');
  const age=(seconds:number|null|undefined)=>seconds==null?'?':seconds<60?t('less than 1 min','moins de 1 min'):`${Math.floor(seconds/60)} min`;
  const count=(value:number)=>value.toLocaleString('en-US');
  let message=sample?.state==='ready'&&sample.players!=null
    ? t(`Steam: ${count(sample.players)} · measured ${age(sample.sample_age_s)} ago`,
        `Steam : ${count(sample.players)} · mesure il y a ${age(sample.sample_age_s)}`)
    : sample?.state==='zero'?t('Steam returned 0 players; no population scene.','Steam indique 0 joueur ; aucune scène de population.')
    : sample?.state==='network_error'?sample.error_code==='dns'?t('Steam address could not be resolved.','L’adresse de Steam n’a pas pu être résolue.')
      :sample.error_code==='timeout'?t('Steam request timed out.','La requête Steam a dépassé le délai d’attente.')
      :t('Steam connection unavailable.','Connexion à Steam indisponible.')
    : sample?.state==='tls_error'?t('Steam HTTPS certificate could not be verified.','Le certificat HTTPS de Steam n’a pas pu être vérifié.')
    : sample?.state==='unavailable'?t('Steam count unavailable.','Nombre de joueurs Steam indisponible.')
    : sample?.state==='stale'?t('Steam measurement is too old.','La mesure Steam est trop ancienne.')
    :t('Waiting for a Steam measurement.','En attente d’une mesure Steam.');
  if(city?.reason==='weather_unavailable')message+=' '+t('Configure Weather to show the city.','Configurez la météo pour afficher la ville.');
  const displayed=city?.displayed;
  if(displayed?.appid===status.game.appid){
    message+=' · '+t(`Last City: ${count(displayed.players)} · measurement ${age(Math.max(0,Date.now()/1000-displayed.sampled_at))} old`,
      `Dernière ville : ${count(displayed.players)} · mesure de ${age(Math.max(0,Date.now()/1000-displayed.sampled_at))}`);
  }else message+=' '+t('Previous image kept.','Image précédente conservée.');
  if(['deferred','unconfirmed','journal_unavailable'].includes(city?.reason??''))
    message+=' '+t('Display update pending confirmation.','Actualisation de l’écran en attente de confirmation.');
  if(city?.reason==='cadence'&&city.next_refresh_s!=null)
    message+=' '+t(`Next update in ${Math.ceil(city.next_refresh_s/60)} min.`,
      `Prochaine actualisation dans ${Math.ceil(city.next_refresh_s/60)} min.`);
  return message;
}
