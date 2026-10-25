/** Share accepted setup status with Decky's independently mounted title action. */
let completed = false;
let faceplateCompleted: boolean|undefined;
const listeners = new Set<() => void>();
export const quickSetupCompleted = () => completed;
export function publishQuickSetupStatus(status: {onboarding_completed: boolean;faceplate_setup_completed?:boolean}) {
  const next = status.onboarding_completed === true;
  if (next === completed && status.faceplate_setup_completed === faceplateCompleted) return;
  faceplateCompleted = status.faceplate_setup_completed;
  completed = next;
  for (const listener of listeners) listener();
}
export function subscribeQuickSetup(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
