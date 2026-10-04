import type { Status, WeatherCondition, WeatherIconStyle } from "./types";

const NAMES: Record<WeatherCondition, string> = {
  clear_day: "Clear sky", clear_night: "Clear night", cloud: "Cloudy", cloud_night: "Cloudy night",
  rain: "Rain", snow: "Snow", storm: "Thunderstorm",
  breaks: "Partly cloudy", breaks_night: "Partly cloudy night",
};

export function weatherTopBarReading(status: Status): {
  condition: WeatherCondition;
  icon_style: WeatherIconStyle;
  text: string;
  title: string;
} | null {
  const { weather } = status;
  const temperature = weather.temperature_c;
  if (!status.weather_topbar_enabled || !status.weather_location || weather.phase !== "ready"
      || weather.condition == null || temperature == null || !Number.isFinite(temperature)
      || weather.age_s == null || weather.age_s >= 3600) return null;
  const fahrenheit = status.weather_temperature_unit === "fahrenheit";
  const text = fahrenheit
    ? `${Math.round(temperature * 9 / 5 + 32)}°F`
    : `${Math.round(temperature)}°C`;
  const title = `${NAMES[weather.condition]} · ${text} · ${status.weather_location.name}`;
  return {
    condition: weather.condition,
    icon_style: status.weather_icon_style ?? "phosphor-duotone",
    text,
    title,
  };
}
