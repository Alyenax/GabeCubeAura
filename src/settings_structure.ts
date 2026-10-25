/** Stable semantic destinations. Never resolve a setting by its translated title. */
export const SETTINGS_CATEGORIES = [
  {id:'display',title:'Display Light',tabs:[['daily','Affichage','Display'],['effects','Effets','Effects'],['sync','Synchronisation','Sync'],['profiles','Profils','Profiles']]},
  {id:'signals',title:'Signals light',tabs:[['events','Événements','Events'],['controllers','Manettes','Controllers'],['performance','Performances','Performance'],['timers','Minuteurs','Timers']]},
  {id:'weather',title:'Weather',tabs:[['forecast','Prévisions','Forecast'],['animations','Animations','Animations']]},
  {id:'faceplate',title:'Faceplate Jsaux',tabs:[['display','Affichage','Display'],['dashboard','Dashboard','Dashboard'],['artwork','Illustrations','Artwork'],['maintenance','Maintenance','Maintenance']]},
  {id:'updates',title:'Updates',tabs:[['install','Mise à jour','Update'],['preferences','Préférences','Preferences']]},
  {id:'advanced',title:'Advanced',tabs:[['general','Général','General'],['diagnostics','Diagnostics','Diagnostics'],['data','Données','Data']]},
] as const;
export type SettingsCategory = typeof SETTINGS_CATEGORIES[number]['id'];
export interface SettingsSelection {category: SettingsCategory; tab: string}
export const SETTINGS_ROUTE_PATTERN='/gabecubeaura/settings/:source?';
const CATEGORY_SOURCE:Record<SettingsCategory,string>={display:'routing',signals:'events',weather:'weather',faceplate:'pixel-settings',updates:'updates',advanced:'advanced'};
export const settingsCategoryRoute=(category:SettingsCategory)=>`/gabecubeaura/settings/${CATEGORY_SOURCE[category]}`;
export function settingsCategoryFromRoute(route:string):SettingsCategory|undefined{
  return SETTINGS_CATEGORIES.find(item=>settingsCategoryRoute(item.id)===route)?.id;
}
export type SettingsSourcePage = 'routing'|'customization'|'artwork'|'screen-sync'|'audio-sync'|'profiles'|'events'|'launches'|'controllers'|'performance'|'countdown'|'weather'|'pixel-settings'|'pixel-artwork'|'updates'|'advanced';
export function settingsSelection(category: string, tab?: string): SettingsSelection {
  const item=SETTINGS_CATEGORIES.find(item=>item.id===category)??SETTINGS_CATEGORIES[0];
  return {category:item.id,tab:item.tabs.some(item=>item[0]===tab)?tab!:item.tabs[0][0]};
}
/** Only connected hardware earns a Settings category, even after previous detection. */
export function visibleSettingsCategories(faceplateConnected:boolean){
  return SETTINGS_CATEGORIES.filter(item=>item.id!=='faceplate'||faceplateConnected);
}
/** Hardware-specific links must resolve to a reachable native page. */
export function visibleSettingsSelection(selection:SettingsSelection,faceplateConnected:boolean):SettingsSelection{
  return !faceplateConnected&&selection.category==='faceplate'?settingsSelection('display','daily'):selection;
}
export function settingsSources(selection: SettingsSelection, effect='customization',sync='screen-sync',event='events'):SettingsSourcePage[]{
  switch(selection.category){
    case 'display':return selection.tab==='effects'?[effect==='artwork'?'artwork':'customization']:
      selection.tab==='sync'?[sync==='audio-sync'?'audio-sync':'screen-sync']:
      selection.tab==='profiles'?['profiles']:['routing'];
    case 'signals':return [selection.tab==='events'?(event==='launches'?'launches':'events'):
      selection.tab==='controllers'?'controllers':selection.tab==='performance'?'performance':'countdown'];
    case 'weather':return ['weather'];
    case 'faceplate':return selection.tab==='artwork'?['pixel-settings','pixel-artwork']:['pixel-settings'];
    case 'updates':return ['updates'];
    case 'advanced':return ['advanced'];
  }
}
export function settingsStep(selection:SettingsSelection,direction:number):SettingsSelection{
  const item=SETTINGS_CATEGORIES.find(item=>item.id===selection.category)!;
  const index=item.tabs.findIndex(item=>item[0]===selection.tab);
  // Match Steam Tabs wrapAround=false. At either edge keep the current tab;
  // do not consume D-pad movement here: native navigation can leave the row.
  const next=Math.max(0,Math.min(item.tabs.length-1,index+direction));
  return {...selection,tab:item.tabs[next][0]};
}
export const SETTINGS_ALIASES:Record<string,SettingsSelection>={
  routing:{category:'display',tab:'daily'},customization:{category:'display',tab:'effects'},artwork:{category:'display',tab:'effects'},
  'screen-sync':{category:'display',tab:'sync'},'audio-sync':{category:'display',tab:'sync'},profiles:{category:'display',tab:'profiles'},
  events:{category:'signals',tab:'events'},launches:{category:'signals',tab:'events'},controllers:{category:'signals',tab:'controllers'},
  performance:{category:'signals',tab:'performance'},countdown:{category:'signals',tab:'timers'},weather:{category:'weather',tab:'forecast'},
  'pixel-settings':{category:'faceplate',tab:'display'},'pixel-artwork':{category:'faceplate',tab:'artwork'},
  updates:{category:'updates',tab:'install'},advanced:{category:'advanced',tab:'general'},
};
/** One section belongs to one tab. A missing assignment is a test failure. */
export const SETTINGS_SLOTS:Record<string,string>={
  'weather.forecast':'weather/forecast','weather.night':'display/daily','weather.animations':'weather/animations',
  'weather.faceplate':'faceplate/display','weather.brightness':'weather/animations',
  'faceplate.display':'faceplate/display','faceplate.dashboard':'faceplate/dashboard',
  'faceplate.status':'faceplate/display',
  'faceplate.power':'faceplate/display','faceplate.protection':'faceplate/maintenance',
  'faceplate.sgdb':'faceplate/artwork','faceplate.catalog':'faceplate/artwork',
  'updates.install':'updates/install','updates.preferences':'updates/preferences',
  'updates.recovery':'updates/install','updates.safety':'updates/install',
  'advanced.general':'advanced/general',
  'advanced.diagnostics':'advanced/diagnostics','advanced.support':'advanced/diagnostics',
  'advanced.clock':'advanced/diagnostics','advanced.engine':'advanced/diagnostics','advanced.fixtures':'advanced/diagnostics',
  'advanced.data':'advanced/data','advanced.snapshot':'advanced/data',
};
export function settingsSlotVisible(selection:SettingsSelection,slot:string):boolean{
  return SETTINGS_SLOTS[slot]===`${selection.category}/${selection.tab}`;
}
