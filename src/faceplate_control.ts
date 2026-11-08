import type {Status} from './types';

export function faceplateControlLabel(status:Pick<Status,'faceplate_control_mode'|'faceplate_control'>):string {
  const phase=status.faceplate_control?.phase;
  if(phase==='releasing')return 'Releasing Faceplate access...';
  if(status.faceplate_control_mode==='other-app')return phase==='released'
    ? 'USB access released to other apps' : 'Releasing Faceplate access...';
  if(status.faceplate_control_mode==='gca-priority')return phase==='reserved'
    ? 'USB reserved for GCA' : 'Waiting to reserve the Faceplate';
  return 'Automatic Faceplate control';
}
