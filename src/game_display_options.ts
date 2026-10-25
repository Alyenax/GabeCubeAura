import type {GameDisplay} from './types';

export const GAME_DISPLAY_OPTIONS: {data: GameDisplay; label: string}[] = [
  { data: "faceplate_extension", label: "Faceplate image extension" },
  { data: "bar_off", label: "Light bar off" },
  { data: "displays_off", label: "Light bar + Faceplate off" },
  { data: "customization", label: "Customization+" },
  { data: "artwork", label: "Artwork" },
  { data: "performance", label: "Performance" },
  { data: "screen_sync", label: "Screen Sync" },
  { data: "audio_sync", label: "Audio Sync" },
  { data: "weather", label: "Weather" },
  { data: "controller", label: "Controller status" },
];

export function gameDisplayOptions(faceplateAvailable: boolean, selected?: string) {
  return GAME_DISPLAY_OPTIONS.filter(option => faceplateAvailable || option.data !== 'faceplate_extension' || selected === 'faceplate_extension');
}
