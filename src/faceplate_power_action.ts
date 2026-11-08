import type {Status} from './types';

/** An explicit recovery never requests a new GIF or confirms its playback. */
export function faceplatePowerAction(status: Status) {
  if (status.faceplate.restoration?.recovery_available) return {
    enabled: true, label: 'Resume stored picture', button: 'Resume stored picture',
    description: 'Restores power without uploading another image. The requested image remains unconfirmed.',
  };
  const enabled=status.faceplate.powered===false;
  return {enabled, label: enabled?'Turn faceplate on':'Turn faceplate off',
    button: enabled?'Power on':'Power off', description: enabled
      ? 'Restores panel power and reapplies the current brightness; the stored GIF resumes.'
      : 'Turns only the matrix off now. The stored GIF and flash contents are preserved.'};
}
