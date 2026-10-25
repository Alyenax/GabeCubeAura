import { callable } from '@decky/api';
import type { Status, WeatherLocation } from './types';
// Legacy voice steps remain readable so interrupted drafts can resume at a valid GCA step.
export type SetupStep = 'ambiance'|'brightness'|'assistant'|'voice'|'faceplate'|'services'|'review';
export interface SetupDraft {
  step: SetupStep; preset:'custom'|'moderate'|'atmosphere'|'signals'|'immersive'; brightness:number;
  night:boolean; night_percentage:number; city:WeatherLocation|null;
  /** Legacy draft fields only; GCA setup never applies voice preferences. */
  assistant_requested?:boolean|null; assistant_confirmed?:boolean; faceplate_requested:boolean|null;
  home:Status['faceplate']['routing']['routes']['home']; game:'artwork'|'dashboard'|'artwork-dashboard'|'weather'|'player-city'|'keep';
}
export interface SetupSnapshot { draft:Partial<SetupDraft>;bar_detected:boolean;faceplate_detected:boolean;faceplate_busy:boolean;voice_verified?:boolean;recovery_error?:string;draft_storage?:'memory'|'disk';draft_error?:string;draft_error_code?:string;draft_reset_error?:string }
export const getOnboarding=callable<[],SetupSnapshot>('get_onboarding');
export const resetOnboardingDraft=callable<[],SetupSnapshot>('reset_onboarding_draft');
export const saveOnboardingDraft=callable<[changes:Partial<SetupDraft>],SetupDraft>('save_onboarding_draft');
export const completeOnboarding=callable<[choices:Partial<SetupDraft>],Status>('complete_onboarding');
export {setupSteps} from './setupFlow';
