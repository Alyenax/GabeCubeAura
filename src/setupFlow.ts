import type {SetupDraft,SetupSnapshot,SetupStep} from './onboardingApi';
export function setupNeeds(draft:SetupDraft,device:SetupSnapshot) {
  const panel=Boolean(device.faceplate_detected&&draft.faceplate_requested);
  return {
    weather:Boolean(device.bar_detected&&(draft.night||draft.preset==='atmosphere')||panel&&
      (draft.home!=='native-clock'||draft.game==='dashboard'||draft.game==='weather'||draft.game==='player-city')),
    artwork:Boolean(panel&&(draft.game==='artwork'||draft.game==='artwork-dashboard')),
  };
}
export function setupSteps(draft:SetupDraft,device:SetupSnapshot):SetupStep[]{
  const result:SetupStep[]=device.bar_detected?['ambiance','brightness']:[];
  if(device.faceplate_detected)result.push('faceplate');
  const needs=setupNeeds(draft,device);
  if(needs.weather||needs.artwork)result.push('services');
  result.push('review');return result;
}
