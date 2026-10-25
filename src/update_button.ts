import type {UpdateStatus} from "./types";

/** Independent from toast preferences/acknowledgement and current game. */
export function showUpdateButton(update: UpdateStatus | null): update is UpdateStatus {
  return Boolean(update && update.available_version && update.available_version !== update.installed_version
    && !update.recovery_prepared
    && (update.phase === 'available' || update.phase === 'ready'
      || update.phase === 'error' && update.confirmation_token));
}
