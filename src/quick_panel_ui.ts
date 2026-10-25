import {reportRuntimeDiagnostic} from './api';

/** Closed vocabulary only: never log UI text, errors, paths or credentials. */
export function reportQuickUI(action:string,stage:string,choice='') {
  if(!['panel','timer','ambience','faceplate'].includes(action)
    ||!['mounted','opening','opened','cancelled','selected','requested','saved','failed'].includes(stage))return;
  const safe=['moderate','atmosphere','signals','immersive','immersive-plus','festive','custom','lights-out','essential','focus','dashboard','weather',
    'artwork','artwork-dashboard','native-clock','player-city','off','none','sleep','shutdown'].includes(choice)?choice:'';
  try{void reportRuntimeDiagnostic('quick_panel_ui',0,[action,stage,safe].filter(Boolean).join(':'),0).catch(()=>undefined);}
  catch{/* Diagnostics must never prevent a control from working. */}
}
