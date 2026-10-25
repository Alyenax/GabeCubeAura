import type {
  FaceplateDashboardVisualTheme,
  FaceplateVisualTheme,
  FaceplateWeatherVisualTheme,
} from "./types";
import type { FaceplateWeatherPreview } from "./api";

export const FACEPLATE_BASE_VISUAL_THEME_OPTIONS: Array<{
  data: FaceplateVisualTheme;
  label: string;
}> = [
  { data: "integrated", label: "GabeCubeAura · Integrated" },
  { data: "night-paper-v3", label: "Enriched night paper" },
  { data: "night-paper", label: "Night paper" },
  { data: "sun-cut", label: "Sun cut" },
  { data: "winter-loom", label: "Winter loom" },
];

export const FACEPLATE_WEATHER_VISUAL_THEME_OPTIONS: Array<{
  data: FaceplateWeatherVisualTheme;
  label: string;
}> = [
  { data: "weather-artwork-v2", label: "Realistic" },
];

export const FACEPLATE_DASHBOARD_VISUAL_THEME_OPTIONS: Array<{
  data: FaceplateDashboardVisualTheme;
  label: string;
}> = [
  { data: "weather-artwork-v2", label: "Realistic" },
];

export function weatherPreviewMeta(preview: FaceplateWeatherPreview, detailed = false): string[] {
  const result = [preview.live_weather ? "live temperature" : "sample temperature"];
  if (preview.visual_theme === "weather-artwork-v2") result.push("Realistic");
  if (detailed && preview.collection_revision) result.push(preview.collection_revision);
  if (detailed && preview.selection_status === "exact") result.push("exact palette match");
  if (detailed && preview.selection_status === "fallback") result.push("fallback renderer");
  if (preview.variant_name) result.push(preview.variant_name);
  else if (detailed && preview.preset_id) result.push(preview.preset_id);
  if (detailed && preview.source_scene) result.push(preview.source_scene);
  return result;
}
