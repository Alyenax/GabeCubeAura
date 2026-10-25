import type { Status, WeatherCondition, WeatherConfigurationCondition } from "./types";

export const WEATHER_CONDITIONS: { data: WeatherCondition; label: string }[] = [
  { data: "clear_day", label: "Clear sky · sun" },
  { data: "clear_night", label: "Clear sky · night" },
  { data: "rain", label: "Rain" },
  { data: "cloud", label: "Cloud" },
  { data: "cloud_night", label: "Cloud · night" },
  { data: "breaks", label: "Partly cloudy · day" },
  { data: "breaks_night", label: "Partly cloudy · night" },
  { data: "snow", label: "Snow" },
  { data: "storm", label: "Thunderstorm" },
];

const PHASED_WEATHER = new Set<WeatherCondition>(["rain", "snow", "storm"]);
const PHASE_LABELS = {rain: "Rain", snow: "Snow", storm: "Thunderstorm"} as const;
export const WEATHER_CONFIGURATION_CONDITIONS: {data: WeatherConfigurationCondition; label: string}[] =
  WEATHER_CONDITIONS.flatMap(condition => PHASED_WEATHER.has(condition.data)
    ? (["day", "night"] as const).map(phase => ({data: `${condition.data}_${phase}` as WeatherConfigurationCondition,
      label: `${PHASE_LABELS[condition.data as keyof typeof PHASE_LABELS]} · ${phase}`}))
    : [condition as {data: WeatherConfigurationCondition; label: string}]);

export function weatherConfigurationCondition(condition: WeatherCondition | null, isDay: boolean | null): WeatherConfigurationCondition {
  return condition && PHASED_WEATHER.has(condition)
    ? `${condition}_${isDay === false ? "night" : "day"}` as WeatherConfigurationCondition
    : (condition ?? "clear_day") as WeatherConfigurationCondition;
}

export function weatherVariantKey(condition: WeatherConfigurationCondition): keyof Status {
  return `weather_${condition.replace(/^(rain|snow|storm)_day$/, "$1")}_variant` as keyof Status;
}

export const WEATHER_VARIANTS: Record<WeatherCondition, { label: string; detail: string }[]> = {
  clear_day: [
    { label: "Sun glints", detail: "White-gold reflections travel across a gently sparkling yellow band." },
    { label: "Solar bloom", detail: "A white-yellow centre grows across a steady golden band, then recedes." },
  ],
  clear_night: [
    { label: "Breathing moon", detail: "Two central moon LEDs breathe gently out to four over exact night blue." },
    { label: "Lunar bloom", detail: "A stepped white moon halo grows across exact night blue, then recedes." },
  ],
  rain: [
    { label: "Bluewater", detail: "Cyan by day, deep blue with magenta contacts at night; short coloured rain ripples." },
    { label: "Pearl rain", detail: "Green-turquoise by day, cobalt with violet contacts at night; brief coloured rain ripples." },
  ],
  cloud: [
    { label: "Passing shadow", detail: "A wide shadow crosses a continuous soft-white sky, with a brief silver edge." },
    { label: "Passing shadows", detail: "A second shadow follows from the other side without crossing at the centre." },
    { label: "Cross & gather", detail: "Two cloud pairs cross, then a three-LED cloud slowly gathers smaller ones. 20-second loop." },
    { label: "Slow convergence", detail: "Clouds grow into one eight-LED cloud. It drifts left, returns right, then leaves the bar. 48-second loop." },
  ],
  cloud_night: [
    { label: "Night passing shadow", detail: "One dim-white cloud crosses a continuous night-blue sky." },
    { label: "Night passing shadows", detail: "Two dim-white clouds make separate opposing passes over night blue." },
    { label: "Night cross & gather", detail: "Low-white cloud pairs cross and gather over exact night blue. 20-second loop." },
    { label: "Night slow convergence", detail: "Low-white points become one eight-LED cloud and keep the original 48-second drift." },
  ],
  breaks: [
    { label: "Sun through clouds", detail: "The familiar sun opens through a soft-white cloud field, then closes." },
    { label: "Sun, fading clouds", detail: "White clouds fade all the way out as the yellow sun opens, then return." },
  ],
  breaks_night: [
    { label: "Moon through clouds", detail: "The familiar pale moon opens through dim-white clouds, then closes." },
    { label: "Moon, fading clouds", detail: "Dim-white clouds fade all the way out as the pale moon opens, then return." },
  ],
  snow: [
    { label: "Melting snowfall", detail: "Paired, then single gaps appear in a soft white field and fill back in." },
    { label: "Snow takes hold", detail: "White flakes gather until the whole bar is covered, then the scene starts again." },
  ],
  storm: [
    { label: "Pulse and echoes", detail: "A second lightning phrase follows the first, each with scattered echoes." },
    { label: "Storm break", detail: "A fast double strike returns once more after a pause." },
  ],
};

export const WEATHER_CONFIGURATION_VARIANTS: Record<WeatherConfigurationCondition, { label: string; detail: string }[]> = {
  ...WEATHER_VARIANTS,
  snow_day: [
    {label: "Melting snowfall", detail: "Cyan winter daylight with petrol flakes; the ice-blue LED field keeps its melting gaps."},
    {label: "Snow takes hold", detail: "Daylight snow accumulates over rock shadows; cyan LED flakes settle along the bar."},
  ],
  snow_night: [
    {label: "Melting snowfall", detail: "The original snowy night scene with a deep-blue LED field and the same melting gaps."},
    {label: "Snow takes hold", detail: "The original night snowfall and accumulation, with blue LED flakes and settling snow."},
  ],
  storm_day: [
    {label: "Pulse and echoes", detail: "Daylight sea and stone, dark storm clouds and cyan LED strikes with their original echoes."},
    {label: "Storm break", detail: "A daylight squall with the original double strike, pause and cyan LED return."},
  ],
  storm_night: [
    {label: "Pulse and echoes", detail: "The original night fortress with violet LED lightning and the same scattered echoes."},
    {label: "Storm break", detail: "The original night storm with violet LED double strikes and the original pause."},
  ],
  rain_day: [
    { label: "Bluewater", detail: "Cyan daylight with turquoise rain contacts and short ripples." },
    { label: "Pearl rain", detail: "Green-turquoise daylight with brief coloured rain contacts." },
  ],
  rain_night: [
    { label: "Bluewater", detail: "Deep blue at night with brief magenta rain contacts." },
    { label: "Pearl rain", detail: "Cobalt at night with brief violet rain contacts." },
  ],
};
