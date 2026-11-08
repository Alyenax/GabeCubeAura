import type {HomeDisplay} from './types';
export const HOME_DISPLAY_OPTIONS:{data:HomeDisplay;label:string}[]=[
  {data:'faceplate_extension',label:'Faceplate image extension'},
  {data:'blackout',label:'Blackout (held off)'},
  {data:'customization',label:'Customization+'},
  {data:'performance',label:'Performance'},
  {data:'audio_sync',label:'Audio Sync'},
  {data:'weather',label:'Weather'},
  {data:'controller',label:'Controller status'},
];
export const homeDisplayOptions=(available:boolean,selected?:string)=>HOME_DISPLAY_OPTIONS.filter(option=>available||option.data!=='faceplate_extension'||selected==='faceplate_extension');
