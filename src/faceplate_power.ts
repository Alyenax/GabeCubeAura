// Informational copy only: moving the slider never profiles image pixels.
export const FACEPLATE_BRIGHTNESS_NOTE = 'Above 70%, stability depends on USB power.';

export function faceplateBrightnessNotice(requested: number): string | null {
  return Number.isFinite(requested) && requested > 70 ? FACEPLATE_BRIGHTNESS_NOTE : null;
}
