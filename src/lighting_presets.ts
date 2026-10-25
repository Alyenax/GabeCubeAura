/** Shared quick/full-settings names and compact summaries, not new recipes. */
export const QUICK_AMBIENCES=[
  {data:'custom',label:'Custom'},
  {data:'moderate',label:'Moderate'},
  {data:'atmosphere',label:'Atmosphere'},
  {data:'signals',label:'Signals'},
  {data:'immersive',label:'Immersive'},
  {data:'immersive-plus',label:'Immersive+'},
  {data:'festive',label:'Festive'},
];
export const LEGACY_AMBIENCES=[
  {data:'lights-out',label:'Lights out'},
  {data:'essential',label:'Essential'},
  {data:'focus',label:'Focus'},
];
const SUMMARIES:Record<string,string>={
  custom:'Your saved routing and effects.',
  moderate:'Home: colours · Games: artwork · Alerts + screensaver.',
  atmosphere:'Home: weather · Games: artwork · Alerts + screensaver.',
  signals:'Home: controllers · Games: CPU/GPU · Alerts + screensaver.',
  immersive:'Home: Sapphire audio · Games: screen colours · Alerts + screensaver.',
  'immersive-plus':'Audio + screen colours · Alerts + screensaver.',
  festive:'Home: screen-colour audio · Games: Aurora audio · Alerts + screensaver.',
  'lights-out':'LEDs off · Steam Families only.',
  essential:'LEDs off · Downloads + Steam Families.',
  focus:'Custom colours · Steam Families.',
};
export const presetSummary=(preset:string)=>SUMMARIES[preset]??SUMMARIES.custom;
export function quickAmbienceOptions(preset:string){
  // Existing quiet modes remain accurately labelled, never disguised as Custom.
  const legacy=LEGACY_AMBIENCES.find(option=>option.data===preset);
  return legacy?[...QUICK_AMBIENCES,legacy]:QUICK_AMBIENCES;
}
