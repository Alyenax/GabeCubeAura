"""Opt-in Open-Meteo weather and restrained 17-LED animation loops.

Network work runs on its own daemon thread. The render loop only reads a recent
sample, and never falls back to invented weather when the service is unavailable.
"""

from __future__ import annotations

import json
import math
import os
import ssl
import threading
import time
from datetime import datetime
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from signalbar.models import LED_COUNT, ProviderOutput, normalize_frame
from signalbar.providers.weather_sequences import weather_loop_seconds, weather_sequence

BLACK = (0, 0, 0)
MAX_SAMPLE_AGE_SECONDS = 3600.0
REFRESH_SECONDS = 900.0
RETRY_SECONDS = 300.0
CONDITIONS = (
    "clear_day", "clear_night", "rain", "cloud", "cloud_night",
    "breaks", "breaks_night", "snow", "storm",
)
VARIANT_NAMES = {
    "clear_day": ("Sun glints", "Solar bloom"),
    "clear_night": ("Breathing moon", "Lunar bloom"),
    "rain": ("Bluewater", "Pearl rain"),
    "cloud": ("Passing shadow", "Passing shadows", "Cross & gather", "Slow convergence"),
    "cloud_night": (
        "Night passing shadow", "Night passing shadows",
        "Night cross & gather", "Night slow convergence",
    ),
    "breaks": ("Sun through clouds", "Sun, fading clouds"),
    "breaks_night": ("Moon through clouds", "Moon, fading clouds"),
    "snow": ("Melting snowfall", "Snow takes hold"),
    "storm": ("Pulse and echoes", "Storm break"),
}
SYSTEM_CA_BUNDLES = (
    "/etc/ssl/cert.pem",  # Arch/SteamOS ca-certificates-utils
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/ssl/certs/ca-bundle.crt",
)


def _certificate_failure(error):
    return isinstance(getattr(error, "reason", error), ssl.SSLCertVerificationError)


def _open_with_system_trust(request, first_error):
    """Retry a missing-issuer failure with SteamOS's system CA bundle.

    Never disable certificate or hostname verification. Explicit cafile avoids
    an embedded Python/OpenSSL default path that may not point at SteamOS's
    trusted roots inside Decky's plugin process.
    """
    last_error = first_error
    attempted = set()
    for bundle in SYSTEM_CA_BUNDLES:
        if not os.path.isfile(bundle):
            continue
        resolved = os.path.realpath(bundle)
        if resolved in attempted:
            continue
        attempted.add(resolved)
        try:
            context = ssl.create_default_context(cafile=bundle)
        except OSError as error:
            last_error = error
            continue
        try:
            return urlopen(request, timeout=6, context=context)
        except URLError as error:
            if not _certificate_failure(error):
                raise
            last_error = error
    raise RuntimeError("Open-Meteo HTTPS certificate could not be verified with the SteamOS system CA bundle") from last_error


def _read_json(url):
    request = Request(url, headers={"User-Agent": "GabeCubeAura/1.2 weather"})
    try:
        response = urlopen(request, timeout=6)
    except URLError as error:
        if not _certificate_failure(error):
            raise
        response = _open_with_system_trust(request, error)
    with response:
        payload = response.read(262145)
    if len(payload) > 262144:
        raise ValueError("weather response too large")
    result = json.loads(payload)
    if not isinstance(result, dict) or result.get("error"):
        raise ValueError("weather service rejected the request")
    return result


def search_cities(query, read_json=_read_json):
    query = str(query or "").strip()
    if not 2 <= len(query) <= 80:
        raise ValueError("Enter at least two city characters (maximum 80)")
    url = "https://geocoding-api.open-meteo.com/v1/search?" + urlencode({
        "name": query, "count": 8, "language": "en", "format": "json",
    })
    results = read_json(url).get("results", [])
    cities = []
    for item in results if isinstance(results, list) else []:
        try:
            name, country = str(item["name"]).strip(), str(item.get("country", "")).strip()
            lat, lon = float(item["latitude"]), float(item["longitude"])
            if name and math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
                cities.append({"name": name[:80], "country": country[:80], "latitude": lat, "longitude": lon})
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return cities


def condition_for_code(code, is_day=True):
    code = int(code)
    if code in {95, 96, 99}:
        return "storm"
    if code in {71, 73, 75, 77, 85, 86}:
        return "snow"
    if code in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}:
        return "rain"
    if code == 2:
        return "breaks" if is_day else "breaks_night"
    if code in {3, 45, 48}:
        return "cloud" if is_day else "cloud_night"
    if code in {0, 1}:
        return "clear_day" if is_day else "clear_night"
    return "cloud"


def fetch_current(location, read_json=_read_json):
    url = "https://api.open-meteo.com/v1/forecast?" + urlencode({
        "latitude": location["latitude"], "longitude": location["longitude"],
        "current": "weather_code,is_day,temperature_2m", "timezone": "auto",
        "daily": "sunrise,sunset", "forecast_days": 2,
    })
    payload = read_json(url)
    current = payload.get("current")
    if not isinstance(current, dict):
        raise ValueError("weather service returned no current conditions")
    code = int(current["weather_code"])
    day = int(current["is_day"]) == 1
    try:
        temperature = float(current["temperature_2m"])
        if not math.isfinite(temperature) or not -100 <= temperature <= 70:
            temperature = None
    except (KeyError, TypeError, ValueError, OverflowError):
        temperature = None
    observed_at = str(current.get("time", ""))[:32]
    sunrise_at = ""
    sunset_at = ""
    next_transition_at = ""
    seconds_until_transition = None
    daily = payload.get("daily")
    if isinstance(daily, dict):
        sunrises = daily.get("sunrise")
        sunsets = daily.get("sunset")
        if isinstance(sunrises, list) and isinstance(sunsets, list):
            sunrise_at = str(sunrises[0])[:32] if sunrises else ""
            sunset_at = str(sunsets[0])[:32] if sunsets else ""
            try:
                observed = datetime.fromisoformat(observed_at)
                transitions = []
                for value in [*sunrises[:2], *sunsets[:2]]:
                    parsed = datetime.fromisoformat(str(value))
                    if parsed > observed:
                        transitions.append(parsed)
                if transitions:
                    upcoming = min(transitions)
                    next_transition_at = upcoming.isoformat(timespec="minutes")
                    seconds_until_transition = max(
                        0.0, (upcoming - observed).total_seconds()
                    )
            except (TypeError, ValueError, OverflowError):
                pass
    return {"weather_code": code, "is_day": day,
            "condition": condition_for_code(code, day), "temperature_c": temperature,
            "observed_at": observed_at, "sunrise_at": sunrise_at,
            "sunset_at": sunset_at, "next_solar_transition_at": next_transition_at,
            "seconds_until_solar_transition": seconds_until_transition}


def _clamp(value):
    return max(0, min(255, round(value)))


def dim_weather_pixel(pixel, brightness=65, shadow_cutoff=25):
    """Linear RGB gain and optional black gate; no gamma or shadow remapping.

    At 100% / cutoff 0 this is the identity for valid RGB bytes, just like the
    Light Events output. Cutting faint pixels must not dim survivors further.
    """
    scaled = tuple(_clamp(channel * brightness / 100.0) for channel in pixel)
    return BLACK if max(scaled) <= shadow_cutoff else scaled


def weather_frame(condition, variant, elapsed, values):
    """Render a weather loop without a temperature overlay."""
    if condition not in VARIANT_NAMES or type(variant) is not int or not 0 <= variant < len(VARIANT_NAMES[condition]):
        raise ValueError("unknown weather animation")
    raw = weather_sequence(condition, variant, elapsed)
    return normalize_frame([dim_weather_pixel(pixel, values["weather_brightness"],
                                              values["weather_shadow_cutoff"]) for pixel in raw])


class WeatherProvider:
    def __init__(self, clock=time.monotonic, fetch=fetch_current):
        self._clock = clock
        self._fetch = fetch
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._location = None
        self._enabled = False
        self._generation = 0
        self._sample = None
        self._fetched_at = 0.0
        self._next_fetch = 0.0
        self._error = ""
        self._fetching = False
        self._preview = None

    def configure(self, location, display, topbar_enabled=False, night_mode_enabled=False):
        enabled = (display != "off" or topbar_enabled or night_mode_enabled) and location is not None
        with self._lock:
            if location != self._location or enabled != self._enabled:
                self._location = dict(location) if location else None
                self._enabled = enabled
                self._sample = None
                self._fetched_at = 0.0
                self._next_fetch = 0.0
                self._error = ""
                self._fetching = False
                self._generation += 1
                self._wake.set()

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="signalbar-weather", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread.is_alive():
            # A forecast request has a six-second timeout. Let that request
            # finish before a rapid plugin restart can reuse a stopped worker.
            self._thread.join(timeout=7)

    def _run(self):
        while not self._stop.is_set():
            with self._lock:
                due = self._enabled and self._location and self._clock() >= self._next_fetch
                location = dict(self._location) if due else None
                generation = self._generation
                if due:
                    self._fetching = True
                wait = max(1.0, self._next_fetch - self._clock()) if self._enabled else 60.0
            if not due:
                self._wake.wait(min(wait, 60.0))
                self._wake.clear()
                continue
            try:
                sample = self._fetch(location)
                error = ""
            except Exception as caught:
                sample = None
                error = str(caught)[:180]
            with self._lock:
                if not self._stop.is_set() and generation == self._generation:
                    self._fetching = False
                    if sample is not None:
                        self._sample = sample
                        self._fetched_at = self._clock()
                        self._error = ""
                        transition = sample.get("seconds_until_solar_transition")
                        transition_wait = (
                            max(10.0, float(transition) + 1.0)
                            if isinstance(transition, (int, float)) else REFRESH_SECONDS
                        )
                        self._next_fetch = self._clock() + min(
                            REFRESH_SECONDS, transition_wait
                        )
                    else:
                        self._error = error or "weather unavailable"
                        self._next_fetch = self._clock() + RETRY_SECONDS

    def preview(self, condition, variant):
        if condition not in CONDITIONS or type(variant) is not int or not 0 <= variant < len(VARIANT_NAMES[condition]):
            return False
        with self._lock:
            self._preview = {"condition": condition, "variant": variant,
                             "started_at": self._clock()}
        return True

    def stop_preview(self):
        with self._lock:
            self._preview = None

    @staticmethod
    def _frame(sample, variant, elapsed, values):
        return weather_frame(sample["condition"], variant, elapsed, values)

    def _current(self, values, now):
        with self._lock:
            preview = self._preview
            sample = self._sample
            fetched = self._fetched_at
        if preview and now - preview["started_at"] < weather_loop_seconds(preview["condition"], preview["variant"]):
            return preview, preview["variant"], now - preview["started_at"], True
        if sample and fetched and now - fetched < MAX_SAMPLE_AGE_SECONDS:
            condition = sample["condition"]
            variant = values[f"weather_{condition}_variant"]
            return sample, variant, now, False
        return None, 0, 0.0, False

    def output(self, values, game_running=False, now=None):
        now = self._clock() if now is None else now
        sample, variant, elapsed, preview = self._current(values, now)
        if sample is None:
            return ProviderOutput("weather", None, "weather unavailable or not configured")
        display = values["weather_display"]
        allowed = (display == "everywhere" or (display == "home" and not game_running)
                   or (display == "game" and game_running))
        if not preview and not allowed:
            return ProviderOutput("weather", None, "weather not selected here")
        frame = self._frame(sample, variant, elapsed, values)
        return ProviderOutput("weather:preview" if preview else "weather", frame, sample["condition"])

    def solar_status(self, values, now=None):
        now = self._clock() if now is None else now
        with self._lock:
            sample, fetched = self._sample, self._fetched_at
            location = self._location
        fresh = bool(sample and fetched and now - fetched < MAX_SAMPLE_AGE_SECONDS)
        enabled = bool(values.get("night_mode_enabled"))
        is_night = bool(fresh and not sample["is_day"])
        return {
            "enabled": enabled,
            "active": bool(enabled and is_night),
            "available": fresh,
            "location": dict(location) if location else None,
            "is_night": is_night if fresh else None,
            "sunrise_at": sample.get("sunrise_at", "") if sample else "",
            "sunset_at": sample.get("sunset_at", "") if sample else "",
            "next_transition_at": sample.get("next_solar_transition_at", "") if sample else "",
            "brightness": values.get("night_mode_brightness", 35),
        }

    def status(self, values, game_running=False):
        now = self._clock()
        with self._lock:
            sample, fetched = self._sample, self._fetched_at
            location, enabled, error, fetching = self._location, self._enabled, self._error, self._fetching
        current, variant, elapsed, preview = self._current(values, now)
        frame = (self._frame(current, variant, elapsed, values)
                 if current else None)
        solar = self.solar_status(values, now)
        return {"location": location, "display": values["weather_display"],
                "phase": "loading" if fetching else "ready" if sample and fetched and now - fetched < MAX_SAMPLE_AGE_SECONDS
                else "error" if error else "waiting" if enabled else "off",
                "error": error,
                "condition": sample["condition"] if sample else None,
                "is_day": sample["is_day"] if sample else None,
                "weather_code": sample["weather_code"] if sample else None,
                "temperature_c": sample.get("temperature_c") if sample and fetched and now - fetched < MAX_SAMPLE_AGE_SECONDS else None,
                "observed_at": sample["observed_at"] if sample else "",
                "sunrise_at": sample.get("sunrise_at", "") if sample else "",
                "sunset_at": sample.get("sunset_at", "") if sample else "",
                "next_solar_transition_at": sample.get("next_solar_transition_at", "") if sample else "",
                "night_mode_enabled": solar["enabled"],
                "night_mode_active": solar["active"],
                "night_mode_brightness": values.get("night_mode_brightness", 35),
                "age_s": max(0.0, now - fetched) if fetched else None,
                "preview_active": preview,
                "preview_remaining_s": max(0.0, weather_loop_seconds(current["condition"], variant) - elapsed)
                if preview else 0,
                "colors": frame if frame is not None else normalize_frame([BLACK] * LED_COUNT),
                "active_here": self.output(values, game_running, now).frame is not None}
