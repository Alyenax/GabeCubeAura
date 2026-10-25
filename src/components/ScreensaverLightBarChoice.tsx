import {DropdownItem,PanelSectionRow} from '../localized_ui';
import {setSetting} from '../api';
import type {Status} from '../types';

export function ScreensaverLightBarChoice({status,setStatus}:{status:Status;setStatus:(value:Status)=>void}){
  const detected=Boolean(status.faceplate.available);
  const saved=status.screensaver_light_bar_mode??(status.screen_sync_screensaver_enabled?'screen_sync':'none');
  return <PanelSectionRow><DropdownItem label="During Steam screensaver"
    description={saved==='faceplate_extension'&&!detected
      ? 'Reconnect the JSAUX faceplate to resume the saved extension.'
      : 'Temporarily follows the screen or the Faceplate image, then restores your usual lighting. Extension uses the mapping selected in Display routing. None keeps your usual lighting.'}
    selectedOption={!detected&&saved==='faceplate_extension'?'none':saved}
    rgOptions={[{data:'none',label:'No screensaver effect'},{data:'screen_sync',label:'Screen Sync'},
      ...(detected?[{data:'faceplate_extension',label:'Faceplate extension'}]:[])]}
    onChange={async option=>setStatus(await setSetting('screensaver_light_bar_mode',String(option.data)))}/></PanelSectionRow>;
}
