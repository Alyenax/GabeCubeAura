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
FACEPLATE_FALLBACK_AGE_SECONDS = 7200.0
REFRESH_SECONDS = 900.0
RETRY_SECONDS = 30.0
RETRY_WINDOW_SECONDS = 300.0
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
                city = {"name": name[:80], "country": country[:80], "latitude": lat, "longitude": lon}
                country_code = str(item.get("country_code", "")).strip().upper()
                if len(country_code) == 2 and country_code.isascii() and country_code.isalpha():
                    city["country_code"] = country_code
                cities.append(city)
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


def _forecast_facts(payload, observed_at, sunrise_at, sunset_at):
    # Keep the compact forecast facts needed by the 64 x 54 Dashboard.  The
    # provider does the alignment once so renderers never parse or guess API
    # array positions. Missing/malformed hourly data remains an honest None.
    forecast = {
        "next_hour_temperature_c": None,
        "next_hour_condition": None,
        "next_hour_precipitation_probability": None,
        "morning_temperature_c": None,
        "afternoon_temperature_c": None,
        "today_condition": None,
    }
    hourly = payload.get("hourly")
    if isinstance(hourly, dict):
        times = hourly.get("time")
        codes = hourly.get("weather_code")
        temperatures = hourly.get("temperature_2m")
        precipitation = hourly.get("precipitation_probability")
        # Some models do not supply probabilities. Keep temperatures and
        # conditions usable, without substituting zero or another model.
        if not isinstance(precipitation, list):
            precipitation = []
        if all(isinstance(values, list) for values in (times, codes, temperatures)):
            try:
                observed = datetime.fromisoformat(observed_at)
            except (TypeError, ValueError):
                observed = None

            def at(index, values, low, high):
                try:
                    value = float(values[index])
                    return value if math.isfinite(value) and low <= value <= high else None
                except (IndexError, TypeError, ValueError, OverflowError):
                    return None

            parsed = []
            for index, raw_time in enumerate(times):
                try:
                    instant = datetime.fromisoformat(str(raw_time))
                    code_value = int(codes[index])
                except (IndexError, TypeError, ValueError, OverflowError):
                    continue
                temperature_value = at(index, temperatures, -100, 70)
                precipitation_value = at(index, precipitation, 0, 100)
                daylight = True
                try:
                    if sunrise_at and sunset_at:
                        rise = datetime.fromisoformat(sunrise_at)
                        set_at = datetime.fromisoformat(sunset_at)
                        daylight = rise <= instant < set_at
                    else:
                        daylight = 7 <= instant.hour < 19
                except (TypeError, ValueError):
                    daylight = 7 <= instant.hour < 19
                parsed.append((
                    instant, code_value, temperature_value,
                    precipitation_value, daylight,
                ))
            if observed is not None:
                next_item = next((item for item in parsed if item[0] > observed), None)
                if next_item is not None:
                    forecast["next_hour_temperature_c"] = next_item[2]
                    forecast["next_hour_condition"] = condition_for_code(
                        next_item[1], next_item[4],
                    )
                    forecast["next_hour_precipitation_probability"] = next_item[3]
                today = [item for item in parsed if item[0].date() == observed.date()]
                morning = min(today, key=lambda item: abs(item[0].hour - 9), default=None)
                afternoon = min(today, key=lambda item: abs(item[0].hour - 15), default=None)
                midday = min(today, key=lambda item: abs(item[0].hour - 12), default=None)
                forecast["morning_temperature_c"] = morning[2] if morning else None
                forecast["afternoon_temperature_c"] = afternoon[2] if afternoon else None
                if midday:
                    forecast["today_condition"] = condition_for_code(
                        midday[1], midday[4],
                    )
    return forecast


def fetch_current(location, read_json=_read_json):
    parameters = {
        "latitude": location["latitude"], "longitude": location["longitude"],
        "current": (
            "weather_code,is_day,temperature_2m,apparent_temperature,"
            "relative_humidity_2m,precipitation_probability,wind_speed_10m"
        ),
        "hourly": "weather_code,temperature_2m,precipitation_probability",
        "timezone": "auto",
        "daily": "sunrise,sunset,weather_code", "forecast_days": 2,
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urlencode(parameters)
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
    optional = {}
    for source, destination, low, high in (
        ("apparent_temperature", "apparent_temperature_c", -100, 80),
        ("relative_humidity_2m", "relative_humidity_percent", 0, 100),
        ("precipitation_probability", "precipitation_probability", 0, 100),
        ("wind_speed_10m", "wind_speed_kmh", 0, 500),
    ):
        try:
            value = float(current[source])
            optional[destination] = value if math.isfinite(value) and low <= value <= high else None
        except (KeyError, TypeError, ValueError, OverflowError):
            optional[destination] = None
    try:
        utc_offset_seconds = int(payload.get("utc_offset_seconds", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        utc_offset_seconds = 0
    forecast = _forecast_facts(payload, observed_at, sunrise_at, sunset_at)
    return {"weather_code": code, "is_day": day,
            "condition": condition_for_code(code, day), "temperature_c": temperature,
            "observed_at": observed_at, "sunrise_at": sunrise_at,
            "sunset_at": sunset_at, "next_solar_transition_at": next_transition_at,
            "seconds_until_solar_transition": seconds_until_transition,
            "timezone": str(payload.get("timezone", ""))[:64],
            "utc_offset_seconds": utc_offset_seconds,
            **optional, **forecast}


def _clamp(value):
    return max(0, min(255, round(value)))


def dim_weather_pixel(pixel, brightness=65, shadow_cutoff=25):
    """Linear RGB gain and optional black gate; no gamma or shadow remapping.

    At 100% / cutoff 0 this is the identity for valid RGB bytes, just like the
    Light Events output. Cutting faint pixels must not dim survivors further.
    """
    scaled = tuple(_clamp(channel * brightness / 100.0) for channel in pixel)
    return BLACK if max(scaled) <= shadow_cutoff else scaled


def weather_preview_condition(condition):
    """Configuration aliases select a period without inventing forecasts."""
    for base in ('rain', 'snow', 'storm'):
        if condition == base + '_day':
            return base, True
        if condition == base + '_night':
            return base, False
    return str(condition), None


def weather_variant_key(condition, is_day=True):
    suffix = '_night' if condition in ('rain', 'snow', 'storm') and not is_day else ''
    return f"weather_{condition}{suffix}_variant"


def weather_frame(condition, variant, elapsed, values, *, is_day=True):
    """Render a weather loop without a temperature overlay."""
    if condition not in VARIANT_NAMES or type(variant) is not int or not 0 <= variant < len(VARIANT_NAMES[condition]):
        raise ValueError("unknown weather animation")
    raw = weather_sequence(condition, variant, elapsed, is_day=is_day)
    return normalize_frame([dim_weather_pixel(pixel, values["weather_brightness"],
                                              values["weather_shadow_cutoff"]) for pixel in raw])


def _weather_elapsed_clock(animation_clock, wall_clock):
    """Keep freshness/deadlines separate from the animation timeline.

    Linux BOOTTIME includes suspend and ignores civil-clock corrections. A
    paired, nondecreasing fallback accounts for elapsed sleep on other hosts;
    it can conservatively expire data early after a forward civil-clock step.
    Explicit one-clock fixtures retain their supplied timeline.
    """
    if animation_clock is time.monotonic and hasattr(time, 'CLOCK_BOOTTIME'):
        try:
            time.clock_gettime(time.CLOCK_BOOTTIME)
        except (OSError, ValueError):
            pass
        else:
            def read_boot():return time.clock_gettime(time.CLOCK_BOOTTIME)
            read_boot.weather_clock_kind = 'boottime'
            return read_boot
    if animation_clock is not time.monotonic and wall_clock is time.time:
        return animation_clock
    lock = threading.Lock()
    previous = [animation_clock(), wall_clock()]
    elapsed = [previous[0]]
    def read():
        with lock:
            mono, wall = animation_clock(), wall_clock()
            elapsed[0] += max(0.0, mono - previous[0], wall - previous[1])
            previous[:] = mono, wall
            return elapsed[0]
    read.weather_clock_kind = 'paired-fallback'
    return read


class WeatherProvider:
    def __init__(self, clock=time.monotonic, fetch=fetch_current,
                 cache_path=None, wall_clock=time.time, elapsed_clock=None):
        self._clock = clock
        self._wall_clock = wall_clock
        self._elapsed_clock = elapsed_clock or _weather_elapsed_clock(clock, wall_clock)
        self._fetch = fetch
        self._cache_path = str(cache_path) if cache_path else ""
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
        self._retry_deadline = None
        self._error = ""
        self._fetching = False
        self._preview = None
        self._refresh_requests = 0
        self._discarded_responses = 0
        self._last_refresh_reason = 'configuration'
        self._last_fetch_started = None
        self._last_fetch_completed = None
        self._last_error_category = ''

    @staticmethod
    def _location_key(location):
        if not isinstance(location, dict):
            return ""
        try:
            # Country-specific and mixed-source caches have a suffix and are
            # rejected. Existing coordinate-only automatic caches remain valid.
            return f"{float(location['latitude']):.5f},{float(location['longitude']):.5f}"
        except (KeyError, TypeError, ValueError, OverflowError):
            return ""

    def _load_cached(self, location):
        if not self._cache_path:
            return None, 0.0
        try:
            if os.path.getsize(self._cache_path) > 256 * 1024:
                return None, 0.0
            with open(self._cache_path, encoding="utf-8") as stream:
                value = json.load(stream)
            sample = value.get("sample")
            saved_at = float(value.get("saved_at", 0) or 0)
            if (value.get("schema") != 1 or not isinstance(sample, dict)
                    or value.get("location_key") != self._location_key(location)
                    or sample.get("condition") not in CONDITIONS or saved_at <= 0):
                return None, 0.0
            age = max(0.0, self._wall_clock() - saved_at)
            return dict(sample), self._elapsed_clock() - age
        except (OSError, ValueError, TypeError, OverflowError):
            return None, 0.0

    def _persist_cached(self, location, sample):
        if not self._cache_path:
            return
        try:
            parent = os.path.dirname(self._cache_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            temporary = self._cache_path + ".tmp"
            with open(temporary, "w", encoding="utf-8") as stream:
                json.dump({
                    "schema": 1,
                    "location_key": self._location_key(location),
                    "saved_at": self._wall_clock(),
                    "sample": dict(sample),
                }, stream, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._cache_path)
        except (OSError, TypeError, ValueError):
            pass

    def configure(self, location, display, topbar_enabled=False, night_mode_enabled=False,
                  faceplate_enabled=False):
        enabled = (
            display != "off" or topbar_enabled or night_mode_enabled or faceplate_enabled
        ) and location is not None
        with self._lock:
            if location != self._location or enabled != self._enabled:
                self._location = dict(location) if location else None
                self._enabled = enabled
                cached, cached_at = self._load_cached(self._location)
                self._sample = cached
                self._fetched_at = cached_at
                self._next_fetch = 0.0
                self._retry_deadline = None
                self._error = ""
                self._fetching = False
                self._generation += 1
                self._wake.set()

    def request_refresh(self, reason="resume"):
        """Wake the existing worker and invalidate pre-refresh responses.

        No network or panel command runs here. Repeated notifications do not
        renew an exhausted outage's five-minute fast-retry allowance.
        """
        with self._lock:
            if not self._enabled or not self._location:
                return False
            self._generation += 1
            self._refresh_requests += 1
            self._last_refresh_reason = reason if reason in ('steam-resume','logind-resume','resume') else 'manual'
            self._next_fetch = 0.0
            self._wake.set()
            return True

    def _sample_age(self):
        # Caller holds _lock. Zero is a valid injected elapsed-clock timestamp.
        return max(0.0, self._elapsed_clock() - self._fetched_at) if self._sample is not None else None

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="signalbar-weather", daemon=True)
            self._thread.start()

    def stop(self, timeout=7):
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread.is_alive():
            # A forecast request has a six-second timeout. Let that request
            # finish before a rapid plugin restart can reuse a stopped worker.
            self._thread.join(timeout=max(0.0, float(timeout)))

    def _run(self):
        while not self._stop.is_set():
            with self._lock:
                due = self._enabled and self._location and self._elapsed_clock() >= self._next_fetch
                location = dict(self._location) if due else None
                generation = self._generation
                if due:
                    self._fetching = True
                    self._last_fetch_started = self._elapsed_clock()
                wait = max(1.0, self._next_fetch - self._elapsed_clock()) if self._enabled else 60.0
                # Clear under the same lock as request_refresh/configure. A
                # notification delivered before wait must remain observable.
                self._wake.clear()
            if self._stop.is_set():
                break
            if not due:
                self._wake.wait(min(wait, 30.0) if self._enabled else 60.0)
                continue
            try:
                sample = self._fetch(location)
                error = ""
                category = '' if sample is not None else 'no-data'
            except Exception as caught:
                sample = None
                error = str(caught)[:180]
                category = 'timeout' if isinstance(caught, TimeoutError) else 'network' if isinstance(caught, OSError) else 'request-failed'
            with self._lock:
                self._last_fetch_completed = self._elapsed_clock()
                if generation != self._generation:
                    self._discarded_responses += 1
                if not self._stop.is_set() and generation == self._generation:
                    self._last_error_category = category
                    self._fetching = False
                    if sample is not None:
                        self._sample = sample
                        self._fetched_at = self._elapsed_clock()
                        self._retry_deadline = None
                        self._persist_cached(self._location, sample)
                        self._error = ""
                        transition = sample.get("seconds_until_solar_transition")
                        transition_wait = (
                            max(10.0, float(transition) + 1.0)
                            if isinstance(transition, (int, float)) else REFRESH_SECONDS
                        )
                        self._next_fetch = self._elapsed_clock() + min(
                            REFRESH_SECONDS, transition_wait
                        )
                    else:
                        self._error = error or "weather unavailable"
                        now = self._elapsed_clock()
                        if self._retry_deadline is None:
                            self._retry_deadline = now + RETRY_WINDOW_SECONDS
                        # One bounded recovery window per outage. Keep the
                        # deadline after exhaustion so continued failures stay
                        # on the normal cadence until success or reconfiguration.
                        delay = (RETRY_SECONDS
                                 if now + RETRY_SECONDS <= self._retry_deadline
                                 else REFRESH_SECONDS)
                        self._next_fetch = now + delay


    def diagnostic_status(self):
        """Read-only clock/deadline evidence without city, raw exceptions or IO."""
        with self._lock:
            now=self._elapsed_clock()
            ago=lambda value:max(0.0,now-value) if value is not None else None
            return {'clock_kind':getattr(self._elapsed_clock,'weather_clock_kind','injected'),
                'enabled':bool(self._enabled),'sample_present':self._sample is not None,
                'sample_age_s':self._sample_age(),'next_fetch_in_s':max(0.0,self._next_fetch-now) if self._enabled else None,
                'retry_window_in_s':max(0.0,self._retry_deadline-now) if self._retry_deadline is not None else None,
                'fetching':bool(self._fetching),'worker_alive':bool(self._thread and self._thread.is_alive()),
                'generation':self._generation,'refresh_requests':self._refresh_requests,
                'last_refresh_reason':self._last_refresh_reason,'discarded_responses':self._discarded_responses,
                'last_fetch_started_ago_s':ago(self._last_fetch_started),'last_fetch_completed_ago_s':ago(self._last_fetch_completed),
                'error_category':self._last_error_category,'retry_seconds':RETRY_SECONDS,'retry_window_seconds':RETRY_WINDOW_SECONDS}

    def preview(self, condition, variant, started_at=None, frame_step_seconds=None, *, is_day=None):
        condition, forced_daylight = weather_preview_condition(condition)
        if forced_daylight is not None:
            is_day = forced_daylight
        if condition not in CONDITIONS or type(variant) is not int or not 0 <= variant < len(VARIANT_NAMES[condition]):
            return False
        now = self._clock()
        try:
            epoch = float(started_at) if started_at is not None else now
        except (TypeError, ValueError, OverflowError):
            epoch = now
        # A linked faceplate may already be part-way through its autonomous
        # GIF loop. It may never place the provider in the future.
        epoch = min(now, epoch)
        try:
            frame_step = float(frame_step_seconds) if frame_step_seconds is not None else 0.0
        except (TypeError, ValueError, OverflowError):
            frame_step = 0.0
        if not math.isfinite(frame_step) or not 0.0 < frame_step <= 1.0:
            frame_step = 0.0
        with self._lock:
            self._preview = {"condition": condition, "variant": variant,
                             "started_at": epoch,
                             "is_day": bool(is_day) if is_day is not None else bool((self._sample or {}).get("is_day", True)),
                             "frame_step_seconds": frame_step}
        return True

    def stop_preview(self):
        with self._lock:
            self._preview = None

    @staticmethod
    def _frame(sample, variant, elapsed, values):
        return weather_frame(sample["condition"], variant, elapsed, values,
                             is_day=sample.get("is_day", True))

    def _current(self, values, now):
        with self._lock:
            preview = self._preview
            sample = self._sample
            age = self._sample_age()
        elapsed = now - preview["started_at"] if preview else 0.0
        if preview and elapsed < weather_loop_seconds(preview["condition"], preview["variant"]):
            frame_step = preview.get("frame_step_seconds", 0.0)
            if frame_step:
                # The faceplate holds each GIF frame for 100 ms. Render the
                # light bar from that same sampled instant instead of letting
                # its continuous clock reach between-frame rain events early.
                elapsed = math.floor((elapsed + 1e-9) / frame_step) * frame_step
            return preview, preview["variant"], elapsed, True
        if sample and age is not None and age < MAX_SAMPLE_AGE_SECONDS:
            condition = sample["condition"]
            variant = values.get(weather_variant_key(condition, sample.get("is_day", True)),
                                 values[f"weather_{condition}_variant"])
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

    def preview_frame(self, values):
        sample, variant, elapsed, _preview = self._current(values, self._clock())
        return self._frame(sample, variant, elapsed, values) if sample else None

    def solar_status(self, values, now=None):
        # Keep the caller's animation-time argument compatible; freshness uses
        # the separate suspend-inclusive timeline, never that timestamp.
        with self._lock:
            sample, age = self._sample, self._sample_age()
            location = self._location
        fresh = bool(sample and age is not None and age < MAX_SAMPLE_AGE_SECONDS)
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
            sample, age = self._sample, self._sample_age()
            location, enabled, error, fetching = self._location, self._enabled, self._error, self._fetching
        current, variant, elapsed, preview = self._current(values, now)
        frame = (self._frame(current, variant, elapsed, values)
                 if current else None)
        solar = self.solar_status(values, now)
        fresh = bool(sample and age is not None and age < MAX_SAMPLE_AGE_SECONDS)
        fallback = bool(
            sample and age is not None and age < FACEPLATE_FALLBACK_AGE_SECONDS
        )
        faceplate_state = (
            "fresh" if fresh else "cached" if fallback
            else "background-only" if sample else "unavailable"
        )
        return {"location": location, "display": values["weather_display"],
                "phase": "loading" if fetching else "ready" if fresh
                else "error" if error else "waiting" if enabled else "off",
                "error": error,
                "condition": sample["condition"] if sample else None,
                "is_day": sample["is_day"] if sample else None,
                "weather_code": sample["weather_code"] if sample else None,
                "temperature_c": sample.get("temperature_c") if fresh else None,
                "cached_temperature_c": sample.get("temperature_c") if sample else None,
                "faceplate_fallback_available": fallback,
                "faceplate_background_only": bool(sample and not fallback),
                "faceplate_weather_state": faceplate_state,
                "observed_at": sample["observed_at"] if sample else "",
                "sunrise_at": sample.get("sunrise_at", "") if sample else "",
                "sunset_at": sample.get("sunset_at", "") if sample else "",
                "next_solar_transition_at": sample.get("next_solar_transition_at", "") if sample else "",
                "precipitation_probability": sample.get("precipitation_probability") if sample else None,
                "next_hour_temperature_c": sample.get("next_hour_temperature_c") if sample else None,
                "next_hour_condition": sample.get("next_hour_condition") if sample else None,
                "next_hour_precipitation_probability": sample.get("next_hour_precipitation_probability") if sample else None,
                "morning_temperature_c": sample.get("morning_temperature_c") if sample else None,
                "afternoon_temperature_c": sample.get("afternoon_temperature_c") if sample else None,
                "today_condition": sample.get("today_condition") if sample else None,
                "apparent_temperature_c": sample.get("apparent_temperature_c") if sample else None,
                "relative_humidity_percent": sample.get("relative_humidity_percent") if sample else None,
                "wind_speed_kmh": sample.get("wind_speed_kmh") if sample else None,
                "timezone": sample.get("timezone", "") if sample else "",
                "utc_offset_seconds": sample.get("utc_offset_seconds", 0) if sample else 0,
                "night_mode_enabled": solar["enabled"],
                "night_mode_active": solar["active"],
                "night_mode_brightness": values.get("night_mode_brightness", 35),
                "age_s": age,
                "preview_active": preview,
                "preview_remaining_s": max(0.0, weather_loop_seconds(current["condition"], variant) - elapsed)
                if preview else 0,
                "colors": frame if frame is not None else normalize_frame([BLACK] * LED_COUNT),
                "active_here": self.output(values, game_running, now).frame is not None}
