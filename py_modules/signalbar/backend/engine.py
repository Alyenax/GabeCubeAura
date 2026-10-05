"""GabeCubeAura runtime orchestration.

Data collection stays in providers, ownership policy in Arbiter/VanillaGuard,
and all sysfs writes in Renderer.
"""

from __future__ import annotations

import os
import threading
import time

from signalbar import __version__
from signalbar.activation import ScreenSyncActivation
from signalbar.arbiter import Arbiter, VanillaGuard
from signalbar.hardware import ValveLedHardware
from signalbar.integration import LightEventLease, StripMineClaimReader, Tw3SteamRgbClaimReader
from signalbar.models import GameState, ProviderOutput
from signalbar.providers import (
    ArtworkProvider, CountdownProvider, CustomizationProvider,
    EventProvider, IdleProvider, LaunchArtworkProvider, PerformanceProvider,
    ScreenSyncProvider, AudioSyncProvider,
)
from signalbar.providers.controller import ControllerProvider
from signalbar.providers.audio_sync import ADAPTIVE_STYLES
from signalbar.providers.weather import WeatherProvider
from signalbar.renderer import Renderer
from signalbar.settings.store import DISPLAY_PRESET_RECIPES
from signalbar.thermal import ThermalProtection, THERMAL_SUSPENSION_MESSAGE

LED_OUTPUT_REFERENCE_BRIGHTNESS = 9


def resolve_light_bar_brightness(values, provider, solar_status):
    """Return the global hardware gain and the reason it was selected."""
    try:
        day = max(1, min(255, int(values.get("light_bar_day_brightness", 9))))
    except (TypeError, ValueError, OverflowError):
        day = LED_OUTPUT_REFERENCE_BRIGHTNESS
    try:
        percentage = max(10, min(100, int(values.get("night_mode_brightness", 35))))
    except (TypeError, ValueError, OverflowError):
        percentage = 35
    night = max(1, min(255, round(day * percentage / 100.0)))
    if provider.endswith(":night") and provider.startswith("customization:brightness-preview:"):
        return night, "night"
    if provider.endswith(":day") and provider.startswith("customization:brightness-preview:"):
        return day, "day"
    if provider == "countdown" or provider.startswith("controller:low"):
        return day, "alert"
    if solar_status.get("active"):
        return night, "night"
    return day, "day"


def apply_rgb_brightness_fallback(frame, target):
    """Approximate global gain when the LED driver lacks brightness_scale."""
    if frame is None:
        return None
    scale = max(1, min(255, int(target))) / float(LED_OUTPUT_REFERENCE_BRIGHTNESS)
    return [
        tuple(max(0, min(255, round(channel * scale))) for channel in pixel)
        for pixel in frame
    ]


class Engine:
    def __init__(self, settings, cache_path, logger=None, hardware_factory=ValveLedHardware,
                 event_lease=None, stripmine_claim=None, tw3_steamrgb_claim=None):
        self.settings = settings
        self._brightness_recovery_path = os.path.join(
            os.path.dirname(getattr(settings, "path", cache_path)),
            "brightness-calibration-recovery.json",
        )
        self.log = logger
        self.hardware_factory = hardware_factory
        self.event_lease = event_lease or LightEventLease()
        self.stripmine_claim = stripmine_claim or StripMineClaimReader()
        self.tw3_steamrgb_claim = tw3_steamrgb_claim or Tw3SteamRgbClaimReader()
        self._light_event_announced_at = 0.0
        self.artwork = ArtworkProvider(cache_path)
        self.launch_palette = ArtworkProvider(
            os.path.join(os.path.dirname(cache_path), "launch-artwork-cache.json")
        )
        self.launch_artwork = LaunchArtworkProvider()
        self.customization = CustomizationProvider()
        self.countdown = CountdownProvider()
        self.performance = PerformanceProvider()
        self.thermal_protection = ThermalProtection()
        self.screen_sync = ScreenSyncProvider()
        self.audio_sync = AudioSyncProvider()
        self.screen_sync_activation = ScreenSyncActivation()
        self.events = EventProvider()
        self.events.set_variants(settings.all())
        self.controllers = ControllerProvider()
        self.weather = WeatherProvider()
        initial = settings.all()
        self.launch_artwork.configure(
            initial["launch_artwork_animation_enabled"], initial["launch_artwork_pattern"],
            initial["launch_artwork_colour_count"], initial["launch_artwork_duration_seconds"],
        )
        self.weather.configure(
            initial["weather_location"], initial["weather_display"],
            initial["weather_topbar_enabled"], initial["night_mode_enabled"],
        )
        self.idle = IdleProvider()
        self.arbiter = Arbiter()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._game = GameState()
        self._artwork_identity = None
        self._steam_active_until = 0.0
        self._steam_reason = ""
        self._launch_handoff_until = 0.0
        self._context_transition_active = False
        self._context_transition_until = 0.0
        self._context_palette_not_before = 0.0
        self._context_transition_from = 0
        self._context_transition_to = 0
        self._last_recovery_at = 0.0
        self._last_recovery_reason = ""
        self._native_priority_kind = ""
        self._native_priority_reason_text = ""
        self._display_preset_preview = ""
        self._display_preset_preview_until = 0.0
        self._ignored_native_takeovers = 0
        self._effective_steam_priority = False
        self._guard_was_allowed = False
        self._renderer = None
        self._guard = None
        self._decision = "none"
        self._decision_at = 0.0
        self._owner = "Valve"
        self._suspension_reason = "starting"
        self._error = ""
        self._last_runtime_error = ""
        self._last_runtime_error_at = 0.0
        self._available = False
        self._runtime_debug = {
            "appid": 0,
            "game_detection_source": "startup",
            "game_sync_ms": None,
            "parental_callback_state": "idle",
            "parental_callback_delay_ms": None,
            "parental_wait_started_at": 0.0,
            "controller_callback_source": "waiting",
            "controller_last_update_at": 0.0,
            "controller_telemetry": {"phase": "starting", "hooks": 0, "queries": 0,
                                     "events": 0, "raw_count": 0, "query_ms": None, "error": ""},
            "frontend_heartbeat_at": 0.0,
            "game_session_state": "startup",
            "steam_led_override_state": "waiting",
            "game_retained_count": 0,
        }

    def _info(self, message):
        if self.log:
            self.log.info(f"[GabeCubeAura] {message}")

    def _warn(self, message):
        if self.log:
            self.log.warning(f"[GabeCubeAura] {message}")

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self.weather.start()
            self._thread = threading.Thread(target=self._run, name="signalbar-engine", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        self.weather.stop()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        self.screen_sync.stop()
        self.audio_sync.stop()
        self.screen_sync_activation.stop_preview()
        with self._lock:
            self.events.clear_transients()
            self.launch_artwork.cancel()
            self.events.clear_recording()
            self.controllers.clear()
            if self._renderer:
                self._renderer.relinquish(restore_if_owned=True)
            self.event_lease.release()
            self.stripmine_claim.release()
            self._light_event_announced_at = 0.0
            self._owner = "Valve"
            self._decision = "none"
            self._decision_at = time.monotonic()

    def set_game(self, appid=0, title="", launch=False, source=""):
        try:
            appid = max(0, int(appid or 0))
        except (TypeError, ValueError):
            appid = 0
        with self._lock:
            previous_appid = self._game.appid
            changed = appid != previous_appid
            self._game = GameState(appid, str(title or ""))
            if changed:
                # A Steam Families deadline belongs to the game session that
                # produced it. Never leak it into the next game or after exit.
                self.countdown.stop("parental")
                self.events.clear_recording()
                self.launch_artwork.cancel()
                self._launch_handoff_until = 0.0
                now = time.monotonic()
                launch_duration = (
                    float(self.settings.all()["launch_artwork_duration_seconds"])
                    if self._game.running and bool(launch) else 0.0
                )
                self._context_transition_active = True
                self._context_transition_until = now + launch_duration + 7.0
                self._context_palette_not_before = now + 0.55
                self._context_transition_from = previous_appid
                self._context_transition_to = appid
            if changed or not self._game.running:
                self.artwork.clear()
                self.launch_palette.clear()
                self._artwork_identity = None
            self.controllers.cancel_for_settings(self.settings.all(), self._game.running)
            if changed and self._game.running and bool(launch):
                self._launch_handoff_until = time.monotonic() + 1.0
                self._refresh_launch_palettes(self._game.appid)
                self.launch_artwork.arm(self._game.appid)
        if changed:
            # Gamescope replaces/reconfigures its PipeWire producer across game
            # transitions.  Tear the old gst-launch process down synchronously
            # so a stale client cannot leave the next pipeline failing during
            # its PAUSED preroll. The render loop will start a fresh capture on
            # the next tick if Screen Sync is still requested.
            self.screen_sync.stop()
            # Preserve the last rendered palette across the short PipeWire
            # rebuild. The first fresh audio frame then fades from the old
            # context into the new Home or in-game selection instead of
            # flashing through a cold fallback palette.
            self.audio_sync.stop(preserve_palette=True)

    def prepare_artwork(self, appid, fingerprint, filename="", source="hero"):
        artwork_settings = self.settings.artwork_for(appid)
        identity = (int(appid), str(fingerprint), str(filename or ""), str(source or "hero"))
        with self._lock:
            self._artwork_identity = identity
            cached = self.artwork.activate_cached(
                identity[0], identity[1], artwork_settings["mode"], artwork_settings["manual_y"]
            )
            return cached

    def submit_artwork(self, appid, fingerprint, colors, sample_y, dominant_palettes,
                       filename="", source="hero"):
        artwork_settings = self.settings.artwork_for(appid)
        self.artwork.submit(
            appid, fingerprint, artwork_settings["mode"], artwork_settings["manual_y"],
            colors, sample_y, filename, source, dominant_palettes,
        )

    def prepare_launch_artwork(self, appid, fingerprint, filename="", source="hero"):
        cached = self.launch_palette.activate_cached(appid, fingerprint, "auto", 0.34)
        self._refresh_launch_palettes(appid)
        return cached

    def submit_launch_artwork(self, appid, fingerprint, colors, sample_y, dominant_palettes,
                              filename="", source="hero"):
        self.launch_palette.submit(
            appid, fingerprint, "auto", 0.34, colors, sample_y,
            filename, source, dominant_palettes,
        )
        self._refresh_launch_palettes(appid)

    def _refresh_launch_palettes(self, appid):
        profile = self.settings.launch_artwork_for(appid)
        artwork_vibrance = self.settings.artwork_for(appid)["vibrance"]
        palettes = (
            profile["custom_palettes"]
            if profile["palette_mode"] == "custom"
            else self.launch_palette.dominant_palettes(appid, artwork_vibrance)
        )
        self.launch_artwork.set_palettes(appid, palettes)

    def update_launch_artwork_settings(self, appid, changes):
        profile = self.settings.update_launch_artwork(appid, changes)
        self._refresh_launch_palettes(appid)
        self.launch_artwork.cancel()
        return profile

    def update_artwork_settings(self, appid, changes):
        artwork_settings = self.settings.update_artwork(appid, changes)
        with self._lock:
            if self._artwork_identity and int(appid or 0) == self._artwork_identity[0]:
                identity_appid, fingerprint, _, _ = self._artwork_identity
                self.artwork.activate_cached(
                    identity_appid, fingerprint,
                    artwork_settings["mode"], artwork_settings["manual_y"],
                )
            self._refresh_launch_palettes(int(appid or self._game.appid or 0))
        return artwork_settings

    def set_steam_activity(self, active, reason="Steam event"):
        with self._lock:
            if active:
                # Lease prevents a vanished frontend from suspending forever.
                self._steam_active_until = time.monotonic() + 6.0
                self._steam_reason = str(reason or "Steam event")
            else:
                self._steam_active_until = 0.0
                self._steam_reason = ""
            thermal_active = self.thermal_protection.active
        values = self.settings.all()
        policy = values["valve_ownership_policy"]
        return {
            "ownership_policy": policy,
            "suppress_download_animation": bool(
                active
                and values["signalbar_enabled"]
                and policy == "critical"
                and not thermal_active
            ),
            "restore_download_animation": bool(
                active
                and values["signalbar_enabled"]
                and policy == "downloads"
                and not thermal_active
            ),
        }

    def set_screen_sync_context(self, context, active, state="available", detail=""):
        if str(context or "") != "steam-screensaver":
            return False
        self.screen_sync_activation.set_screensaver(active, state, detail)
        return True

    def preview_screen_sync(self, seconds=15.0):
        if not self.settings.all()["signalbar_enabled"]:
            return False
        return self.screen_sync_activation.preview(seconds)

    def preview_audio_sync(self, seconds=15.0):
        if not self.settings.all()["signalbar_enabled"]:
            return False
        return self.audio_sync.preview(seconds)

    def report_runtime_diagnostic(self, event, appid=0, source="", duration_ms=-1):
        """Record frontend lifecycle timings without affecting provider policy."""
        try:
            appid = max(0, int(appid or 0))
            duration_ms = max(0.0, float(duration_ms))
        except (TypeError, ValueError):
            return
        event = str(event or "")
        now = time.monotonic()
        with self._lock:
            if event == "game_synced":
                self._runtime_debug.update({
                    "appid": appid,
                    "game_detection_source": str(source or "unknown")[:48],
                    "game_sync_ms": duration_ms,
                    "frontend_heartbeat_at": now,
                    "game_session_state": str(source or "unknown")[:64],
                    "parental_callback_state": (
                        "waiting" if appid > 0 and self.settings.all()["parental_countdown_enabled"]
                        else "disabled" if appid > 0 else "idle"
                    ),
                    "parental_callback_delay_ms": None,
                    "parental_wait_started_at": now if appid > 0 else 0.0,
                })
            elif event == "parental_received" and appid == self._runtime_debug["appid"]:
                self._runtime_debug.update({
                    "parental_callback_state": "received",
                    "parental_callback_delay_ms": duration_ms,
                    "parental_wait_started_at": 0.0,
                })
            elif event == "heartbeat":
                self._runtime_debug["frontend_heartbeat_at"] = now
            elif event == "game_retained":
                self._runtime_debug.update({
                    "frontend_heartbeat_at": now,
                    "game_session_state": str(source or "retained")[:64],
                    "game_retained_count": self._runtime_debug["game_retained_count"] + 1,
                })
            elif event == "steam_led_override":
                self._runtime_debug["steam_led_override_state"] = str(source or "unknown")[:32]

    def report_parental_minutes(self, minutes):
        try:
            minutes = float(minutes)
        except (TypeError, ValueError):
            return
        values = self.settings.all()
        with self._lock:
            game_running = self._game.running
        if not values["parental_countdown_enabled"] or not game_running:
            self.countdown.stop("parental")
            return
        # SteamUI uses values above one day as the no-active-limit sentinel.
        if minutes <= 0:
            self.countdown.stop("parental")
            return
        if minutes > 1440:
            self.countdown.stop("parental")
            return
        self.countdown.start(
            "parental", minutes * 60.0,
            label="Steam Families",
        )

    def start_free_timer(self, minutes):
        values = self.settings.update({"free_timer_minutes": minutes})
        duration = values["free_timer_minutes"] * 60.0
        self.countdown.start("free", duration, total_seconds=duration, label="Free timer")

    def stop_free_timer(self):
        self.countdown.stop("free")

    def preview_countdown(self):
        self.countdown.start("preview", 15.0, total_seconds=15.0, label="Preview")

    def preview_launch_artwork(self):
        values = self.settings.all()
        if values["mode"] == "disabled":
            return False
        with self._lock:
            appid = self._game.appid
        if appid <= 0:
            return False
        return self.launch_artwork.arm(appid, preview=True)

    def preview_customization(self):
        values = self.settings.all()
        if values["mode"] == "disabled":
            return False
        return self.customization.preview()

    def preview_light_calibration(self):
        values = self.settings.all()
        if values["mode"] == "disabled":
            return False
        return self.customization.preview_calibration(10.0)

    def preview_light_brightness(self, mode="day"):
        values = self.settings.all()
        if values["mode"] == "disabled":
            return False
        return self.customization.preview_brightness(mode, 3.0)

    def preview_display_preset(self, preset, seconds=10.0):
        if preset not in {"moderate", "atmosphere", "signals", "immersive"}:
            return False
        with self._lock:
            self._display_preset_preview = preset
            self._display_preset_preview_until = time.monotonic() + max(3.0, min(20.0, float(seconds)))
        return True

    def trigger_event(self, kind, preview=False, variant=""):
        values = self.settings.all()
        kind = str(kind or "")
        if not preview and kind in {"record-start", "record-stop"}:
            # Capture safety follows recording even when its optional visual
            # event or persistent marker is disabled.
            self.events.set_recording(kind == "record-start")
        if values["mode"] == "disabled":
            return False
        if self.controllers.event_output().provider == "controller:low":
            return False
        if not preview:
            setting = {
                "notification": "event_notifications_enabled",
                "achievement": "event_achievements_enabled",
                "screenshot": "event_screenshots_enabled",
                "record-start": "event_recording_enabled",
                "record-stop": "event_recording_enabled",
            }.get(kind)
            if not values["events_enabled"] or not setting or not values[setting]:
                return False
        with self._lock:
            game_running = self._game.running
        countdown = self.countdown.status(
            allow_parental=values["parental_countdown_enabled"] and game_running,
        )
        if countdown["active"] and countdown["remaining_seconds"] <= 300:
            # Recording state still follows Steam, but the warning is never
            # visually interrupted, even for a fraction of one render tick.
            if kind in {"record-start", "record-stop"} and not preview:
                self.events.trigger(kind)
                self.events.clear_transients()
            return False
        return self.events.trigger(kind, preview=bool(preview), variant=variant)

    def update_controllers(self, controllers, source="Steam callback"):
        values = self.settings.all()
        with self._lock:
            running = self._game.running
            self._runtime_debug["controller_callback_source"] = str(source or "Steam callback")[:48]
            self._runtime_debug["controller_last_update_at"] = time.monotonic()
        countdown = self.countdown.status(allow_parental=values["parental_countdown_enabled"] and running)
        if countdown["active"] and countdown["remaining_seconds"] <= 300:
            # Keep receiving real state, but don't consume an unseen low warning.
            values = {**values, "controller_alerts_enabled": False}
        if self.controllers.update(controllers, values, running) == "low":
            self.events.clear_transients()

    def reset_controllers(self):
        self.controllers.clear()
        with self._lock:
            self._runtime_debug["controller_callback_source"] = "waiting"
            self._runtime_debug["controller_last_update_at"] = 0.0
            self._runtime_debug["controller_telemetry"]["phase"] = "starting"

    def report_controller_telemetry(self, state):
        if not isinstance(state, dict):
            return
        phase = state.get("phase")
        if phase not in {"starting", "ready", "unavailable", "error"}:
            return
        clean = {"phase": phase, "error": str(state.get("error") or "")[:180]}
        for key in ("hooks", "queries", "events", "raw_count", "query_ms"):
            value = state.get(key)
            clean[key] = min(10000000, max(0, int(value))) if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value < float("inf") else (None if key == "query_ms" else 0)
        clean["devices"] = []
        devices = state.get("devices", [])
        if isinstance(devices, list):
            for device in devices[:8]:
                if not isinstance(device, dict):
                    continue
                entry = {"name": str(device.get("name", "Controller"))[:64],
                         "source": str(device.get("source", "unknown"))[:40]}
                for key in ("index", "list_percent", "store_percent", "event_percent", "effective_percent", "event_age_s"):
                    value = device.get(key)
                    maximum = 0xffffffff if key == "index" else 100 if key.endswith("percent") else 10000000
                    entry[key] = value if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= maximum else None
                clean["devices"].append(entry)
        with self._lock:
            self._runtime_debug["controller_telemetry"] = clean

    def preview_controller(self, kind, variant="", count=1, target=0):
        values = self.settings.all()
        if values["mode"] == "disabled":
            return False
        with self._lock:
            running = self._game.running
        countdown = self.countdown.status(
            allow_parental=values["parental_countdown_enabled"] and running,
        )
        if countdown["active"] and countdown["remaining_seconds"] <= 300:
            return False
        selected = str(kind or "")
        played = self.controllers.preview(selected, values, str(variant or ""), count, target)
        if played and selected == "low":
            self.events.clear_transients()
        return played

    def _weather_preview_allowed(self):
        values = self.settings.all()
        if values["mode"] == "disabled":
            return False
        with self._lock:
            running = self._game.running
        countdown = self.countdown.status(
            allow_parental=values["parental_countdown_enabled"] and running,
        )
        if countdown["active"] and countdown["remaining_seconds"] <= 300:
            return False
        return True

    def preview_weather(self, condition, variant):
        return self._weather_preview_allowed() and self.weather.preview(condition, variant)

    def stop_weather_preview(self):
        self.weather.stop_preview()
        return True

    def update_settings(self, changes):
        values = self.settings.update(changes)
        self._apply_settings(values, changes)
        return values

    def import_configuration(self, global_values, display_profiles, artwork_profiles,
                             launch_artwork_profiles=None):
        previous = self.settings.all()
        values = self.settings.replace_configuration(
            global_values, display_profiles, artwork_profiles, launch_artwork_profiles,
        )
        changes = {key: value for key, value in values.items() if previous.get(key) != value}
        self._apply_settings(values, changes)
        self.countdown.stop("free")
        self.weather.stop_preview()
        self.customization.stop_preview()
        self.controllers.clear_transients()
        self.events.clear_transients()
        with self._lock:
            if self._artwork_identity:
                appid, fingerprint, _, _ = self._artwork_identity
                artwork_settings = self.settings.artwork_for(appid)
                self.artwork.activate_cached(appid, fingerprint,
                                             artwork_settings["mode"], artwork_settings["manual_y"])
        return values

    def update_display(self, appid, mode):
        previous = self.settings.all()
        result = self.settings.update_display(appid, mode)
        values = self.settings.all()
        changes = {key: value for key, value in values.items() if previous.get(key) != value}
        self._apply_settings(values, changes)
        return result

    def reset_configuration(self):
        return self.import_configuration({}, {}, {})

    def _apply_settings(self, values, changes):
        self.launch_artwork.configure(
            values["launch_artwork_animation_enabled"], values["launch_artwork_pattern"],
            values["launch_artwork_colour_count"], values["launch_artwork_duration_seconds"],
        )
        if any(key in changes for key in (
            "launch_artwork_pattern", "launch_artwork_colour_count",
            "launch_artwork_duration_seconds", "launch_artwork_source",
        )):
            self.launch_artwork.cancel()
        if "launch_artwork_source" in changes:
            self.launch_palette.clear()
            self.launch_artwork.clear_palettes()
        self.weather.configure(
            values["weather_location"], values["weather_display"],
            values["weather_topbar_enabled"], values["night_mode_enabled"],
        )
        self.events.set_variants(values)
        with self._lock:
            running = self._game.running
        self.controllers.cancel_for_settings(values, running)
        if not values["events_enabled"]:
            self.events.clear_transients()
        elif values["mode"] == "disabled":
            self.events.clear_transients()
        else:
            for key, kinds in (
                ("event_notifications_enabled", ("notification",)),
                ("event_achievements_enabled", ("achievement",)),
                ("event_screenshots_enabled", ("screenshot",)),
                ("event_recording_enabled", ("record-start", "record-stop")),
            ):
                if key in changes and not values[key]:
                    self.events.cancel_kinds(kinds)
        if values["mode"] == "disabled":
            self.controllers.clear_transients()
            self.launch_artwork.cancel()
            self.customization.stop_preview()
        if "parental_countdown_enabled" in changes and not values["parental_countdown_enabled"]:
            # Turning the feature off is an immediate cancellation, not only
            # a visual filter. Later callbacks are ignored until re-enabled.
            self.countdown.stop("parental")
            with self._lock:
                self._runtime_debug["parental_callback_state"] = "disabled"
                self._runtime_debug["parental_wait_started_at"] = 0.0
        elif "parental_countdown_enabled" in changes:
            with self._lock:
                if self._game.running:
                    self._runtime_debug["parental_callback_state"] = "waiting"
                    self._runtime_debug["parental_callback_delay_ms"] = None
                    self._runtime_debug["parental_wait_started_at"] = time.monotonic()
        with self._lock:
            if self._guard:
                self._guard.cooldown_s = values["guard_cooldown_s"]
                self._guard.stable_s = values["guard_stable_s"]

    @staticmethod
    def _stripmine_family(provider):
        if provider.startswith("launch-artwork"):
            return "game_launches"
        if provider.startswith("artwork"):
            return "artwork"
        if provider.startswith("performance"):
            return "performance"
        if provider.startswith("screen-sync"):
            return "screen_sync"
        if provider.startswith("audio-sync"):
            return "audio_sync"
        if provider.startswith("customization"):
            return "customization"
        if provider.startswith("weather"):
            return "weather"
        if provider.startswith("controller"):
            return "controller"
        if provider.startswith("event:"):
            return "light_events"
        return "system"

    @classmethod
    def _stripmine_priority(cls, provider, values):
        if provider in {"none", "valve", "idle"}:
            return "stripmine"
        family = cls._stripmine_family(provider)
        if family == "system":
            # Countdowns and unknown safety providers keep GabeCubeAura priority.
            return "signalbar"
        return values.get(f"stripmine_priority_{family}", "stripmine")

    def _tw3_steamrgb_state(self, values, game):
        detected = bool(
            game.appid == 292030 and self.tw3_steamrgb_claim.active()
        )
        return detected, bool(
            values["tw3_steamrgb_integration_enabled"] and detected
        )

    @staticmethod
    def _screen_sync_should_run(values, requested, signal_critical,
                                guard_allows, stripmine_active, recording=False,
                                steam_priority=False):
        # Gamescope capture is read-only and must not follow short-lived LED
        # ownership changes. Stopping it for every Valve write, countdown or
        # screensaver handoff repeatedly rebuilds the PipeWire graph precisely
        # while Gamescope and the game are resuming. The arbiter still prevents
        # any LED write while Steam or a protected signal owns the bar.
        return (
            values["signalbar_enabled"]
            and requested
            and not recording
            and (
                not stripmine_active
                or values["stripmine_priority_screen_sync"] == "signalbar"
            )
        )

    @staticmethod
    def _audio_screen_capture_should_run(values, requested):
        """Use Gamescope colours for Audio Sync in both Home and game contexts."""
        return bool(
            requested
            and values["audio_sync_style"] in ADAPTIVE_STYLES
            and values["audio_sync_palette"] == "screen-sync"
        )

    @staticmethod
    def _screen_sync_fallback_should_run(requested, ownership_allowed,
                                         screen_sync_frame, launch_pending=False):
        """Avoid flashing Customization+ inside a game-launch transition.

        A pending launch effect deliberately waits for Steam's native writes
        to settle. During that interval the safe visual is the existing Valve
        frame (or a real Screen Sync frame if capture is already ready), not an
        unrelated permanent fallback colour.
        """
        return bool(
            requested
            and ownership_allowed
            and screen_sync_frame is None
            and not launch_pending
        )

    @staticmethod
    def _audio_sync_should_run(values, requested, signal_critical, guard_allows,
                               stripmine_active, steam_priority=False,
                               companion_hud_active=False):
        return bool(
            values["signalbar_enabled"]
            and requested
            and not signal_critical
            and not steam_priority
            and not companion_hud_active
            and (guard_allows or stripmine_active)
            and (
                not stripmine_active
                or values["stripmine_priority_audio_sync"] == "signalbar"
            )
        )

    @staticmethod
    def _audio_transition_ready(audio_sync_output, screen_capture_requested,
                                palette_source):
        """Only reveal the new Audio Sync context once its palette is genuine."""
        return bool(
            audio_sync_output is not None
            and audio_sync_output.frame is not None
            and (
                not screen_capture_requested
                or palette_source == "screen-sync"
            )
        )

    @staticmethod
    def _hold_context_frame(transition_active, audio_sync_requested,
                            launch_transition_active, steam_priority,
                            stripmine_active, companion_hud_active, decision):
        """Keep the previous physical frame through an Audio Sync handoff."""
        return bool(
            transition_active
            and audio_sync_requested
            and decision.frame is None
            and not steam_priority
            and not stripmine_active
            and not companion_hud_active
            and (
                launch_transition_active
                or decision.provider in {"none", "valve", "audio-sync"}
            )
        )

    @staticmethod
    def _native_priority_state(hardware, signature, expected_signature):
        # Ignore our own verified frame before asking hardware about explicit
        # native effects. Fixed colours, including red, have no semantics here.
        if expected_signature is not None and signature == expected_signature:
            return "", ""
        detector = getattr(hardware, "native_priority_state", None)
        if callable(detector):
            return detector(signature)
        detector = getattr(hardware, "native_priority_reason", None)
        reason = detector(signature) if callable(detector) else ""
        return ("effect" if reason else ""), reason

    @staticmethod
    def _resolve_ownership_policy(policy, *, download_active, native_kind,
                                  guard_allows, guard_hard_priority):
        """Resolve semantic Steam signals separately from generic LED churn."""
        policy = policy if policy in {"cooperative", "downloads", "critical"} else "cooperative"
        download = bool(download_active and policy in {"cooperative", "downloads"})
        native_effect = bool(native_kind and policy == "cooperative")
        steam_priority = bool(
            download or native_effect
            or policy == "cooperative" and guard_hard_priority
        )
        ownership_allowed = bool(guard_allows or policy != "cooperative")
        return ownership_allowed, steam_priority

    def _suspend_for_thermal_protection(self, renderer):
        """Stop every plugin animation and return the physical bar to Valve."""
        if renderer is not None:
            renderer.relinquish(restore_if_owned=True)
        self.screen_sync.set_active(False)
        self.audio_sync.set_active(False)
        self.screen_sync_activation.stop_preview()
        self.customization.stop_preview()
        self.weather.stop_preview()
        self.events.clear_transients()
        self.controllers.clear_transients()
        self.launch_artwork.cancel()
        self.event_lease.release()
        self.stripmine_claim.release()
        self._light_event_announced_at = 0.0
        with self._lock:
            self._owner = "Valve"
            self._decision = "thermal-protection"
            self._suspension_reason = THERMAL_SUSPENSION_MESSAGE
            self._error = ""
            self._decision_at = time.monotonic()

    @staticmethod
    def _restore_before_valve_handoff(*, externally_blocked,
                                      event_preempted_valve,
                                      semantic_download_priority):
        """Release manual sysfs mode before a requested native download.

        Renderer still verifies that its last signature is physically present,
        so this cannot overwrite a Valve frame that arrived concurrently.
        """
        return bool(
            not externally_blocked
            or event_preempted_valve
            or semantic_download_priority
        )

    def _run(self):
        hardware = None
        renderer = None
        guard = None
        interval = 0.10
        event_was_active = False
        event_preempted_valve = False
        next_hardware_attempt = 0.0
        while not self._stop.is_set():
            # Telemetry must not depend on LED ownership, hardware availability,
            # the chosen display, or whether a Decky panel is open.
            self.performance.refresh(self.settings.all()["performance_smoothing"])
            thermal_active = self.thermal_protection.update(
                self.performance.sample, now=time.monotonic(),
            )
            if thermal_active:
                self._suspend_for_thermal_protection(renderer)
                event_was_active = False
                event_preempted_valve = False
                if self._stop.wait(interval):
                    break
                continue
            if hardware is None:
                if time.monotonic() < next_hardware_attempt:
                    self._stop.wait(0.1)
                    continue
                try:
                    hardware = self.hardware_factory()
                    values = self.settings.all()
                    renderer = Renderer(
                        hardware,
                        brightness_recovery_path=self._brightness_recovery_path,
                    )
                    guard = VanillaGuard(values["guard_cooldown_s"], values["guard_stable_s"])
                    with self._lock:
                        self._renderer, self._guard = renderer, guard
                        self._available = True
                        self._error = ""
                        self._suspension_reason = "startup settle"
                    self._info("17 valve-leds detected; conservative startup settle begun")
                except Exception as error:
                    with self._lock:
                        self._available = False
                        self._error = str(error)
                        self._suspension_reason = "hardware unavailable; retrying"
                    next_hardware_attempt = time.monotonic() + 2.0
                    hardware = None
                    renderer = None
                    guard = None
                    continue

            if self._stop.wait(interval):
                break
            try:
                now = time.monotonic()
                values = self.settings.all()
                if hardware.reverse != values["reverse_led_order"]:
                    # Restore with the old mapping before changing orientation;
                    # otherwise a later shutdown would restore the snapshot backwards.
                    if renderer.last_frame is not None:
                        renderer.relinquish(restore_if_owned=True)
                    hardware.set_reverse(values["reverse_led_order"])
                with self._lock:
                    game = self._game
                    explicit = now < self._steam_active_until
                    explicit_reason = self._steam_reason
                    if self._context_transition_active and now >= self._context_transition_until:
                        self._context_transition_active = False
                    context_transition_active = self._context_transition_active
                    context_palette_not_before = self._context_palette_not_before
                    preview_preset = (
                        self._display_preset_preview
                        if now < self._display_preset_preview_until else ""
                    )
                display = self.settings.display_for(game.appid)
                if preview_preset:
                    values.update(DISPLAY_PRESET_RECIPES[preview_preset])
                    values["display_preset"] = preview_preset
                    selected_preview = values[
                        "game_display" if game.running else "home_display"
                    ]
                    display = {
                        "selected": selected_preview,
                        "default": selected_preview,
                        "override": "inherit",
                        "mode": (
                            selected_preview
                            if selected_preview in {
                                "artwork", "performance", "customization",
                                "screen_sync", "audio_sync", "blackout",
                            } else "events"
                        ),
                    }
                values["mode"] = display["mode"]
                current_display = display["selected"]
                audio_context = "game" if game.running else "home"
                values["audio_sync_style"] = values[f"audio_sync_{audio_context}_style"]
                values["audio_sync_palette"] = values[f"audio_sync_{audio_context}_palette"]
                for role in ("low", "middle", "high"):
                    values[f"audio_sync_colour_{role}"] = values[
                        f"audio_sync_{audio_context}_colour_{role}"
                    ]
                provider_values = dict(values)
                provider_values["controller_battery_display"] = (
                    "everywhere" if current_display == "controller" else "off"
                )
                provider_values["controller_charging_display"] = (
                    "everywhere" if current_display == "controller" else "off"
                )
                provider_values["weather_display"] = (
                    "everywhere" if current_display == "weather" else "off"
                )
                weather_base = self.weather.output(provider_values, game.running, now)
                signature = hardware.read_signature()
                stability_signature = getattr(hardware, "stability_signature", None)
                stability_signature = (
                    stability_signature(signature)
                    if callable(stability_signature) else signature
                )
                native_priority_kind, native_priority_reason = self._native_priority_state(
                    hardware, signature, renderer.last_signature,
                )
                ownership_policy = values["valve_ownership_policy"]
                semantic_native_priority = bool(
                    ownership_policy == "cooperative" and native_priority_kind
                )
                signature_mismatch = bool(
                    renderer.last_signature is not None
                    and signature != renderer.last_signature
                )
                semantic_download_priority = bool(
                    explicit and ownership_policy in {"cooperative", "downloads"}
                )
                allowed = guard.observe(
                    signature,
                    expected_signature=renderer.last_signature,
                    explicit_active=semantic_download_priority or semantic_native_priority,
                    explicit_reason=(
                        explicit_reason if semantic_download_priority else native_priority_reason
                    ),
                    stability_signature=stability_signature,
                )
                ownership_allowed, steam_priority = self._resolve_ownership_policy(
                    ownership_policy,
                    download_active=explicit,
                    native_kind=native_priority_kind,
                    guard_allows=allowed,
                    guard_hard_priority=guard.hard_priority,
                )
                # Cooperative mode keeps the existing fail-safe handoff. The
                # two protected modes instead reclaim ordinary Valve writes.
                # Thermal protection is an independent sensor-driven gate.
                event_interrupted = bool(
                    event_was_active and signature_mismatch
                    and (ownership_policy == "cooperative" or steam_priority)
                )
                recovering_ownership = bool(
                    ownership_allowed and not self._guard_was_allowed and guard.last_external_at
                )
                self._guard_was_allowed = ownership_allowed
                if signature_mismatch and ownership_policy != "cooperative" and not steam_priority:
                    self._ignored_native_takeovers += 1
                self._native_priority_kind = native_priority_kind
                self._native_priority_reason_text = native_priority_reason
                self._effective_steam_priority = steam_priority
                stripmine_active = (
                    values["stripmine_integration_enabled"]
                    and self.stripmine_claim.active()
                )
                _, tw3_steamrgb_active = self._tw3_steamrgb_state(values, game)
                performance = self.performance.output(
                    metric=values["performance_metric"],
                    cool_c=values["cool_temp_c"],
                    hot_c=values["hot_temp_c"],
                    palette=values["temperature_palette"],
                    direction=values["mixed_direction"],
                    dark_edge_compensation=values["countdown_dark_edge_compensation"],
                    smoothing=values["performance_smoothing"],
                    enabled=(values["mode"] == "performance"),
                    custom_palette=(
                        values["temperature_custom_cool"],
                        values["temperature_custom_middle"],
                        values["temperature_custom_hot"],
                    ),
                )
                artwork_settings = self.settings.artwork_for(game.appid)
                artwork = self.artwork.output(
                    game.appid, artwork_settings["vibrance"],
                )
                signal = self.countdown.output(
                    colour=values["countdown_colour"],
                    dark_edge_compensation=values["countdown_dark_edge_compensation"],
                    full_bar_seconds=values["countdown_full_bar_minutes"] * 60.0,
                    allow_parental=(
                        values["parental_countdown_enabled"] and game.running
                    ),
                )
                countdown_state = self.countdown.status(
                    allow_parental=values["parental_countdown_enabled"] and game.running,
                )
                signal_critical = (
                    countdown_state["active"] and countdown_state["remaining_seconds"] <= 300
                )
                game_screen_sync = (
                    values["mode"] == "screen_sync"
                    and current_display == "screen_sync"
                    and game.running
                )
                activation_reason = self.screen_sync_activation.resolve(
                    game_route=game_screen_sync,
                    screensaver_enabled=values["screen_sync_screensaver_enabled"],
                    enabled=values["signalbar_enabled"],
                )
                screen_sync_requested = bool(activation_reason)
                atmosphere_weather_fallback = bool(
                    values.get("display_preset") == "atmosphere"
                    and not game.running
                    and current_display == "weather"
                    and weather_base.frame is None
                )
                audio_sync_route = bool(
                    values["mode"] == "audio_sync" and current_display == "audio_sync"
                    or atmosphere_weather_fallback
                )
                # A Steam screensaver request is a hard mode handoff. Stop the
                # audio reader as well as its LED output so Screen Sync owns the
                # complete visual path until Steam dismisses the screensaver.
                audio_sync_requested = bool(
                    (audio_sync_route or self.audio_sync.previewing)
                    and not screen_sync_requested
                )
                launch_transition_status = self.launch_artwork.status(game.appid)
                launch_transition_active = bool(
                    launch_transition_status["pending"]
                    or launch_transition_status["active"]
                )
                audio_screen_capture = self._audio_screen_capture_should_run(
                    values, audio_sync_requested,
                )
                recording = self.events.recording
                screen_sync_active = self._screen_sync_should_run(
                    values, screen_sync_requested or audio_screen_capture,
                    signal_critical, ownership_allowed,
                    stripmine_active, recording, steam_priority,
                )
                self.screen_sync.set_active(screen_sync_active)
                screen_sync_base = self.screen_sync.output(values)
                audio_sync_active = self._audio_sync_should_run(
                    values, audio_sync_requested, signal_critical, ownership_allowed,
                    stripmine_active, steam_priority, tw3_steamrgb_active,
                )
                self.audio_sync.set_active(audio_sync_active)
                artwork_colours = self.artwork.dominant_palettes(
                    game.appid, artwork_settings["vibrance"],
                ).get("3", ())
                if not artwork_colours:
                    artwork_colours = self.launch_palette.dominant_palettes(
                        game.appid, artwork_settings["vibrance"],
                    ).get("3", ())
                audio_transition_frozen = bool(
                    context_transition_active
                    and (
                        launch_transition_active
                        or now < context_palette_not_before
                    )
                )
                if audio_transition_frozen:
                    # Keep both capture services warm, but never let the Steam
                    # launch surface recolour or advance Audio Sync underneath
                    # the launch animation. Its last palette remains intact.
                    audio_sync_base = ProviderOutput(
                        "audio-sync", None,
                        "Audio Sync held during game transition",
                    )
                else:
                    audio_sync_base = self.audio_sync.output(
                        values,
                        screen_colours=(
                            self.screen_sync.palette_samples
                            if (
                                audio_screen_capture
                                and values["audio_sync_style"] in ADAPTIVE_STYLES
                                and values["audio_sync_palette"] == "screen-sync"
                                and self.screen_sync.palette_samples
                            )
                            else screen_sync_base.frame
                            if audio_screen_capture and screen_sync_base.frame is not None
                            else None
                        ),
                        artwork_colours=artwork_colours,
                    )
                audio_palette_source = self.audio_sync.status(
                    values["audio_sync_reactivity"],
                )["palette_source"]
                audio_transition_ready = self._audio_transition_ready(
                    audio_sync_base, audio_screen_capture, audio_palette_source,
                )
                if (context_transition_active and not launch_transition_active
                        and now >= context_palette_not_before):
                    transition_complete = (
                        audio_sync_requested and audio_transition_ready
                        or not audio_sync_requested
                    )
                    if transition_complete:
                        with self._lock:
                            if self._game.appid == game.appid:
                                self._context_transition_active = False
                        context_transition_active = False
                if signal_critical:
                    self.events.clear_transients()
                    self.controllers.clear_transients()
                if event_interrupted:
                    self.events.clear_transients()
                    self.controllers.clear_transients()
                    self.launch_artwork.cancel()
                event = self.events.output()
                controller_event = self.controllers.event_output()
                if preview_preset == "signals" and controller_event.frame is None:
                    # Keep the onboarding preview visibly representative even
                    # before a controller has been paired. This reuses the
                    # real two-controller animation and physical render path.
                    self.controllers.preview(
                        "duo", values, values.get("controller_duo_variant", "double-welcome"),
                        count=2, target=1,
                    )
                    controller_event = self.controllers.event_output()
                controller_base = self.controllers.persistent_output(provider_values, game.running)
                screen_sync_ownership_allowed = (
                    not stripmine_active
                    or values["stripmine_priority_screen_sync"] == "signalbar"
                )
                launch_transition_pending = launch_transition_status["pending"]
                screen_sync_fallback_active = self._screen_sync_fallback_should_run(
                    screen_sync_requested,
                    screen_sync_ownership_allowed,
                    screen_sync_base.frame,
                    launch_transition_pending,
                )
                customization_base = self.customization.output(
                    values,
                    enabled=(
                        current_display == "customization" and values["mode"] != "disabled"
                        or screen_sync_fallback_active
                    ),
                )
                brief_alert = any(output is not None and output.frame is not None for output in (
                    event, controller_event,
                ))
                launch_display_allowed = (
                    self.launch_artwork.previewing
                    or values["mode"] != "disabled" and game.running
                )
                launch_ownership_allowed = (
                    not stripmine_active
                    or values["stripmine_priority_game_launches"] == "signalbar"
                )
                if self.launch_artwork.active and (
                    signal_critical or not launch_display_allowed or not launch_ownership_allowed
                    or steam_priority or not (ownership_allowed or stripmine_active)
                ):
                    self.launch_artwork.cancel()
                launch_artwork = self.launch_artwork.output(
                    game.appid,
                    allow_start=(
                        launch_display_allowed and now >= self._launch_handoff_until
                        and not signal_critical and not brief_alert
                        and not steam_priority
                        and (ownership_allowed or stripmine_active) and launch_ownership_allowed
                    ),
                    paused=brief_alert,
                )
                launch_status_after_output = self.launch_artwork.status(game.appid)
                launch_finished_this_tick = bool(
                    launch_transition_active
                    and not launch_status_after_output["pending"]
                    and not launch_status_after_output["active"]
                )
                if launch_finished_this_tick:
                    # Let Gamescope advance beyond Steam's launch surface
                    # before the first palette is accepted. Capture remains
                    # warm, so this delay does not rebuild the pipeline.
                    with self._lock:
                        if self._game.appid == game.appid:
                            self._context_palette_not_before = now + 0.45
                # Moving event waves need more than ten samples per second to
                # visibly visit all 17 positions. Normal providers stay at
                # the conservative 10 Hz cadence.
                interval = 0.06 if any(output.frame is not None for output in (
                    event, controller_event, launch_artwork, customization_base,
                    audio_sync_base,
                )) else 0.10
                effective_mode = (
                    "screen_sync" if screen_sync_requested
                    else "audio_sync" if audio_sync_requested
                    else values["mode"]
                )
                decision = self.arbiter.choose(
                    mode=effective_mode, guard_allows=ownership_allowed or stripmine_active, game=game,
                    performance=performance, artwork=artwork, idle=self.idle.output(),
                    signal=signal, event=event, signal_critical=signal_critical,
                    controller_event=controller_event, controller_base=controller_base,
                    weather_base=weather_base,
                    customization_base=customization_base,
                    screen_sync_base=screen_sync_base,
                    screen_sync_fallback=(
                        customization_base if screen_sync_fallback_active else None
                    ),
                    audio_sync_base=audio_sync_base,
                    launch_artwork=launch_artwork,
                    recording_marker=(
                        self.events.recording and values["events_enabled"]
                        and values["event_recording_enabled"]
                    ),
                    recording_marker_isolation=values["recording_marker_isolation"],
                    performance_always=values["performance_always"],
                    steam_priority=steam_priority,
                    companion_hud_active=tw3_steamrgb_active,
                )

                hold_context_frame = (
                    renderer.last_frame is not None
                    and self._hold_context_frame(
                        context_transition_active, audio_sync_requested,
                        launch_transition_active, steam_priority,
                        stripmine_active, tw3_steamrgb_active, decision,
                    )
                )

                stripmine_priority = self._stripmine_priority(decision.provider, values)
                yield_to_stripmine = (
                    stripmine_active and not steam_priority and stripmine_priority == "stripmine"
                )
                take_from_stripmine = (
                    stripmine_active and not steam_priority and stripmine_priority == "signalbar"
                )
                if stripmine_active and not yield_to_stripmine:
                    self.stripmine_claim.acknowledge(stripmine_priority, decision.provider)

                is_light_event = decision.provider.startswith("event:")
                needs_handoff = (is_light_event and not yield_to_stripmine) or take_from_stripmine
                if needs_handoff:
                    # Publish before the first LED write so StripMine can yield
                    # without treating this short, intentional takeover as a conflict.
                    self.event_lease.refresh(
                        decision.provider,
                        "light-event" if is_light_event else "priority-output",
                    )
                    if not self._light_event_announced_at:
                        self._light_event_announced_at = now
                    handoff_ready = (
                        self.event_lease.acknowledged()
                        or is_light_event and now - self._light_event_announced_at >= 0.10
                    )
                else:
                    self._light_event_announced_at = 0.0
                    handoff_ready = True
                if yield_to_stripmine:
                    if renderer.last_frame is not None:
                        renderer.relinquish(restore_if_owned=True)
                    # Grant StripMine ownership only after every possible
                    # restore write has completed. On the physical 17-LED
                    # sysfs device a restore is sequential; acknowledging
                    # first lets StripMine resume in the middle of it and
                    # misclassify our remaining writes as a third-party app.
                    self.stripmine_claim.acknowledge(stripmine_priority, decision.provider)
                    event_was_active = False
                    event_preempted_valve = False
                    owner = "Valve"
                    suspension = f"StripMine priority over {self._stripmine_family(decision.provider)}"
                elif needs_handoff and not handoff_ready:
                    # Keep the current frame untouched until StripMine confirms
                    # it has stopped writing. A short timeout preserves normal
                    # events when StripMine is not installed.
                    event_was_active = False
                    event_preempted_valve = False
                    owner = self._owner
                    suspension = "waiting for StripMine LED handoff"
                elif hold_context_frame:
                    # A missing provider frame inside a bounded Home/game
                    # transition is not a request to restore Valve's saved
                    # blue frame. Keep the exact last visible frame and, if an
                    # ordinary native write raced us, atomically reclaim it.
                    held_frame = renderer.last_frame
                    wrote = renderer.render(held_frame, force=signature_mismatch)
                    if wrote:
                        guard.note_own_write(renderer.last_signature)
                    event_was_active = False
                    event_preempted_valve = False
                    owner = "GabeCubeAura"
                    suspension = "Audio Sync context transition; holding previous frame"
                elif decision.frame is not None:
                    is_event = decision.provider.startswith(("event:", "controller:", "launch-artwork:"))
                    if is_event and not ownership_allowed:
                        event_preempted_valve = True
                    elif not is_event:
                        event_preempted_valve = False
                    solar_status = self.weather.solar_status(values)
                    target_brightness, _brightness_period = resolve_light_bar_brightness(
                        values, decision.provider, solar_status,
                    )
                    hardware_brightness = renderer.calibration_status()["supported"]
                    renderer.set_output_brightness_scale(
                        target_brightness if hardware_brightness else None
                    )
                    output_frame = (
                        decision.frame if hardware_brightness
                        else apply_rgb_brightness_fallback(decision.frame, target_brightness)
                    )
                    wrote = renderer.render(
                        output_frame,
                        force=(
                            ownership_policy != "cooperative"
                            and signature_mismatch
                            and not steam_priority
                        ),
                    )
                    if wrote:
                        guard.note_own_write(renderer.last_signature)
                        if recovering_ownership:
                            self._last_recovery_at = now
                            self._last_recovery_reason = "GabeCubeAura ownership restored"
                    owner = "GabeCubeAura"
                    suspension = (
                        "Screen Sync paused; Customization+ fallback active"
                        if effective_mode == "screen_sync"
                        and decision.provider.startswith("customization")
                        else ""
                    )
                    event_was_active = is_event
                else:
                    externally_blocked = decision.provider == "valve"
                    if renderer.last_frame is not None:
                        # After a short event over a stable Valve frame, put
                        # that exact frame back. Renderer verifies ownership
                        # first, so a concurrent native write is never undone.
                        renderer.relinquish(
                            restore_if_owned=self._restore_before_valve_handoff(
                                externally_blocked=externally_blocked,
                                event_preempted_valve=event_preempted_valve,
                                semantic_download_priority=semantic_download_priority,
                            )
                        )
                    event_was_active = False
                    event_preempted_valve = False
                    owner = "Valve"
                    suspension = guard.reason if externally_blocked else decision.reason
                if not needs_handoff or yield_to_stripmine:
                    # Relinquish/restore happens above; only then tell StripMine
                    # that it may safely reclaim its continuously animated bar.
                    self.event_lease.release()

                with self._lock:
                    # Do not report the event as physically active while the
                    # cooperative handoff is still pending. Besides being more
                    # truthful in diagnostics, this prevents callers from
                    # racing a native write against GabeCubeAura's first frame.
                    self._decision = (
                        "companion:handoff"
                        if needs_handoff and not handoff_ready
                        else "companion:stripmine"
                        if yield_to_stripmine
                        else "transition:hold"
                        if hold_context_frame
                        else decision.provider
                    )
                    self._owner = owner
                    self._suspension_reason = suspension
                    self._error = ""
                    self._decision_at = time.monotonic()
            except Exception as error:
                self.screen_sync.set_active(False)
                self.audio_sync.set_active(False)
                # A provider or renderer fault must not leave the last plugin
                # frame frozen on the strip. Renderer restores the saved
                # Valve state only if the hardware still matches our verified
                # signature; otherwise it safely leaves the external writer
                # alone.
                renderer.relinquish(restore_if_owned=True)
                self.event_lease.release()
                self.stripmine_claim.release()
                self._light_event_announced_at = 0.0
                with self._lock:
                    self._available = False
                    self._owner = "Valve"
                    self._decision = "none"
                    self._suspension_reason = "runtime failure; restored Valve and retrying"
                    self._error = str(error)
                    self._last_runtime_error = str(error)
                    self._last_runtime_error_at = time.monotonic()
                    self._decision_at = time.monotonic()
                    self._renderer = None
                    self._guard = None
                self._warn(f"render loop fault; restored Valve and retrying: {error}")
                hardware = None
                renderer = None
                guard = None
                event_was_active = False
                event_preempted_valve = False
                self._guard_was_allowed = False
                next_hardware_attempt = time.monotonic() + 0.5
                continue

        if renderer is not None:
            renderer.relinquish(restore_if_owned=True)
        self.screen_sync.set_active(False)
        self.audio_sync.set_active(False)
        self.stripmine_claim.release()

    def status(self):
        values = self.settings.all()
        now = time.monotonic()
        stripmine_detected = (
            values["stripmine_integration_enabled"]
            and self.stripmine_claim.active()
        )
        tw3_steamrgb_detected, tw3_steamrgb_active = self._tw3_steamrgb_state(
            values, self._game
        )
        sample = self.performance.sample
        thermal_status = self.thermal_protection.status(now)
        artwork_settings = self.settings.artwork_for(self._game.appid)
        art = self.artwork.status(
            values["launch_artwork_colour_count"], artwork_settings["vibrance"],
        )
        with self._lock:
            launch_artwork_status = self.launch_artwork.status(self._game.appid)
            display = self.settings.display_for(self._game.appid)
            values["mode"] = display["mode"]
            audio_context = "game" if self._game.running else "home"
            values["audio_sync_style"] = values[f"audio_sync_{audio_context}_style"]
            values["audio_sync_palette"] = values[f"audio_sync_{audio_context}_palette"]
            for role in ("low", "middle", "high"):
                values[f"audio_sync_colour_{role}"] = values[
                    f"audio_sync_{audio_context}_colour_{role}"
                ]
            status_values = dict(values)
            status_values["controller_battery_display"] = (
                "everywhere" if display["selected"] == "controller" else "off"
            )
            status_values["controller_charging_display"] = (
                "everywhere" if display["selected"] == "controller" else "off"
            )
            status_values["weather_display"] = (
                "everywhere" if display["selected"] == "weather" else "off"
            )
            countdown = self.countdown.status(
                colour=values["countdown_colour"],
                dark_edge_compensation=values["countdown_dark_edge_compensation"],
                full_bar_seconds=values["countdown_full_bar_minutes"] * 60.0,
                allow_parental=(
                    values["parental_countdown_enabled"] and self._game.running
                ),
            )
            renderer = self._renderer
            guard = self._guard
            last_write_at = renderer.last_successful_write_at if renderer else 0.0
            last_external_at = guard.last_external_at if guard else 0.0
            guard_debug = guard.debug_status() if guard else {
                "ready": False,
                "reason": "not initialized",
                "cooldown_remaining": 0.0,
                "stable_remaining": 0.0,
                "hard_priority": False,
                "hard_reason": "",
            }
            runtime_debug = dict(self._runtime_debug)
            wait_started = runtime_debug.pop("parental_wait_started_at", 0.0)
            controller_last_update_at = runtime_debug.pop("controller_last_update_at", 0.0)
            frontend_heartbeat_at = runtime_debug.pop("frontend_heartbeat_at", 0.0)
            runtime_debug["controller_last_update_age_s"] = (
                max(0.0, now - controller_last_update_at) if controller_last_update_at else None
            )
            runtime_debug["parental_wait_s"] = (
                max(0.0, now - wait_started) if wait_started else None
            )
            runtime_debug["frontend_heartbeat_age_s"] = (
                max(0.0, now - frontend_heartbeat_at) if frontend_heartbeat_at else None
            )
            logical_performance = self.performance.frame(
                metric=values["performance_metric"],
                cool_c=values["cool_temp_c"],
                hot_c=values["hot_temp_c"],
                palette=values["temperature_palette"],
                direction=values["mixed_direction"],
                dark_edge_compensation=0,
                custom_palette=(
                    values["temperature_custom_cool"],
                    values["temperature_custom_middle"],
                    values["temperature_custom_hot"],
                ),
            )
            physical_performance = self.performance.frame(
                metric=values["performance_metric"],
                cool_c=values["cool_temp_c"],
                hot_c=values["hot_temp_c"],
                palette=values["temperature_palette"],
                direction=values["mixed_direction"],
                dark_edge_compensation=values["countdown_dark_edge_compensation"],
                custom_palette=(
                    values["temperature_custom_cool"],
                    values["temperature_custom_middle"],
                    values["temperature_custom_hot"],
                ),
            )
            controller_status = self.controllers.status(status_values, self._game.running)
            weather_status = self.weather.status(status_values, self._game.running)
            night_mode_status = self.weather.solar_status(status_values)
            customization_status = self.customization.status(values)
            screen_sync_status = self.screen_sync.status()
            audio_sync_status = self.audio_sync.status(values["audio_sync_reactivity"])
            game_screen_sync = (
                values["mode"] == "screen_sync"
                and display["selected"] == "screen_sync"
                and self._game.running
            )
            activation_status = self.screen_sync_activation.status(
                game_route=game_screen_sync,
                screensaver_enabled=values["screen_sync_screensaver_enabled"],
                enabled=values["signalbar_enabled"],
            )
            fallback_active = bool(
                activation_status["requested"]
                and self._decision.startswith("customization")
            )
            if self.events.recording:
                fallback_reason = "Steam Game Recording"
            elif screen_sync_status["phase"] == "conflict":
                fallback_reason = "Another Gamescope capture consumer"
            elif screen_sync_status["phase"] == "error":
                fallback_reason = screen_sync_status["error"] or "Capture unavailable"
            elif fallback_active:
                fallback_reason = "Waiting for a fresh Screen Sync frame"
            else:
                fallback_reason = ""
            screen_sync_status.update({
                "activation": activation_status,
                "fallback_active": fallback_active,
                "fallback_reason": fallback_reason,
            })
            engine_running = bool(self._thread and self._thread.is_alive())
            calibration_status = (
                renderer.calibration_status() if renderer else {
                    "supported": False,
                    "detected_brightness": None,
                    "reference_brightness": None,
                    "applied_brightness": None,
                    "saved_steam_brightness": None,
                    "override_active": False,
                    "startup_recovered": False,
                }
            )
            brightness_target, brightness_period = resolve_light_bar_brightness(
                values, self._decision, night_mode_status,
            )
            light_bar_brightness = dict(calibration_status)
            light_bar_brightness.update({
                "control_mode": "hardware" if calibration_status["supported"] else "rgb-fallback",
                "day_brightness": values["light_bar_day_brightness"],
                "night_percentage": values["night_mode_brightness"],
                "target_brightness": brightness_target if self._owner == "GabeCubeAura" else None,
                "current_output": brightness_period if self._owner == "GabeCubeAura" else "valve",
            })
            calibration_status.update({
                "mode": "consistent",
                "reference_brightness": values["light_bar_day_brightness"],
            })
            decision_age_s = (
                max(0.0, now - self._decision_at) if self._decision_at else None
            )
            preset_preview_active = now < self._display_preset_preview_until
            return {
                "version": __version__,
                "available": self._available,
                "active": self._owner == "GabeCubeAura",
                "owner": self._owner,
                "provider": self._decision,
                "suspension_reason": self._suspension_reason,
                "error": self._error,
                "mode": values["mode"],
                "default_mode": display["default"],
                "display_override": display["override"],
                "signalbar_enabled": values["signalbar_enabled"],
                "onboarding_completed": values["onboarding_completed"],
                "display_preset": values["display_preset"],
                "display_preset_preview": {
                    "active": preset_preview_active,
                    "preset": self._display_preset_preview if preset_preview_active else "",
                    "remaining_s": max(0.0, self._display_preset_preview_until - now),
                },
                "valve_ownership_policy": values["valve_ownership_policy"],
                "led_output_calibration_mode": values["led_output_calibration_mode"],
                "led_output_calibration": calibration_status,
                "light_bar_day_brightness": values["light_bar_day_brightness"],
                "light_bar_brightness": light_bar_brightness,
                "home_display": values["home_display"],
                "game_display": values["game_display"],
                "current_display": display["selected"],
                "performance_metric": values["performance_metric"],
                "performance_smoothing": values["performance_smoothing"],
                "performance_always": values["performance_always"],
                "mixed_direction": values["mixed_direction"],
                "temperature_palette": values["temperature_palette"],
                "temperature_custom_cool": values["temperature_custom_cool"],
                "temperature_custom_middle": values["temperature_custom_middle"],
                "temperature_custom_hot": values["temperature_custom_hot"],
                "artwork_mode": artwork_settings["mode"],
                "artwork_manual_y": artwork_settings["manual_y"],
                "artwork_source": artwork_settings["source"],
                "artwork_vibrance": artwork_settings["vibrance"],
                "artwork_custom": artwork_settings["custom"],
                "artwork_default_mode": values["artwork_mode"],
                "artwork_default_manual_y": values["artwork_manual_y"],
                "artwork_default_source": values["artwork_source"],
                "artwork_default_vibrance": values["artwork_vibrance"],
                "launch_artwork_animation_enabled": values["launch_artwork_animation_enabled"],
                "launch_artwork_pattern": values["launch_artwork_pattern"],
                "launch_artwork_colour_count": values["launch_artwork_colour_count"],
                "launch_artwork_duration_seconds": values["launch_artwork_duration_seconds"],
                "launch_artwork_source": values["launch_artwork_source"],
                "launch_artwork_palette_mode": self.settings.launch_artwork_for(self._game.appid)["palette_mode"],
                "launch_artwork_custom_palettes": self.settings.launch_artwork_for(self._game.appid)["custom_palettes"],
                "customization_pattern": values["customization_pattern"],
                "customization_colour_count": values["customization_colour_count"],
                "customization_colour_1": values["customization_colour_1"],
                "customization_colour_2": values["customization_colour_2"],
                "customization_colour_3": values["customization_colour_3"],
                "customization_brightness": values["customization_brightness"],
                "customization_speed": values["customization_speed"],
                "customization_direction": values["customization_direction"],
                "screen_sync_style": values["screen_sync_style"],
                "screen_sync_brightness": values["screen_sync_brightness"],
                "screen_sync_reactivity": values["screen_sync_reactivity"],
                "screen_sync_colour_intensity": values["screen_sync_colour_intensity"],
                "screen_sync_black_threshold": values["screen_sync_black_threshold"],
                "screen_sync_ignore_black_bars": values["screen_sync_ignore_black_bars"],
                "screen_sync_screensaver_enabled": values["screen_sync_screensaver_enabled"],
                "audio_sync_style": values["audio_sync_style"],
                "audio_sync_brightness": values["audio_sync_brightness"],
                "audio_sync_reactivity": values["audio_sync_reactivity"],
                "audio_sync_palette": values["audio_sync_palette"],
                "audio_sync_home_style": values["audio_sync_home_style"],
                "audio_sync_home_palette": values["audio_sync_home_palette"],
                "audio_sync_game_style": values["audio_sync_game_style"],
                "audio_sync_game_palette": values["audio_sync_game_palette"],
                "audio_sync_lab_crest_strength": values["audio_sync_lab_crest_strength"],
                "audio_sync_lab_edge_reach": values["audio_sync_lab_edge_reach"],
                "audio_sync_lab_background": values["audio_sync_lab_background"],
                "audio_sync_hifi_lab_enabled": values["audio_sync_hifi_lab_enabled"],
                "audio_sync_home_colour_low": values["audio_sync_home_colour_low"],
                "audio_sync_home_colour_middle": values["audio_sync_home_colour_middle"],
                "audio_sync_home_colour_high": values["audio_sync_home_colour_high"],
                "audio_sync_game_colour_low": values["audio_sync_game_colour_low"],
                "audio_sync_game_colour_middle": values["audio_sync_game_colour_middle"],
                "audio_sync_game_colour_high": values["audio_sync_game_colour_high"],
                "cool_temp_c": values["cool_temp_c"],
                "hot_temp_c": values["hot_temp_c"],
                "reverse_led_order": values["reverse_led_order"],
                "parental_countdown_enabled": values["parental_countdown_enabled"],
                "countdown_colour": values["countdown_colour"],
                "countdown_full_bar_minutes": values["countdown_full_bar_minutes"],
                "countdown_dark_edge_compensation": values["countdown_dark_edge_compensation"],
                "free_timer_minutes": values["free_timer_minutes"],
                "events_enabled": values["events_enabled"],
                "event_notifications_enabled": values["event_notifications_enabled"],
                "event_achievements_enabled": values["event_achievements_enabled"],
                "event_screenshots_enabled": values["event_screenshots_enabled"],
                "event_recording_enabled": values["event_recording_enabled"],
                "recording_marker_isolation": values["recording_marker_isolation"],
                "event_notification_variant": values["event_notification_variant"],
                "event_achievement_variant": values["event_achievement_variant"],
                "event_screenshot_variant": values["event_screenshot_variant"],
                "controller_battery_display": values["controller_battery_display"],
                "controller_charging_mode": values["controller_charging_mode"],
                "controller_charging_display": values["controller_charging_display"],
                "controller_alert_context": values["controller_alert_context"],
                "controller_alerts_enabled": values["controller_alerts_enabled"],
                "controller_connect_enabled": values["controller_connect_enabled"],
                "controller_low_enabled": values["controller_low_enabled"],
                "controller_charging_enabled": values["controller_charging_enabled"],
                "controller_low_threshold": values["controller_low_threshold"],
                "controller_connect_variant": values["controller_connect_variant"],
                "controller_persistent_variant": values["controller_persistent_variant"],
                "controller_low_variant": values["controller_low_variant"],
                "controller_charging_variant": values["controller_charging_variant"],
                "controller_duo_variant": values["controller_duo_variant"],
                "controller_colour_preset": values["controller_colour_preset"],
                "controller_colour_mode": values["controller_colour_mode"],
                "controller_colour_normal": values["controller_colour_normal"],
                "controller_colour_medium": values["controller_colour_medium"],
                "controller_colour_low": values["controller_colour_low"],
                "controller_colour_charging": values["controller_colour_charging"],
                "controller_player_colour_1": values["controller_player_colour_1"],
                "controller_player_colour_2": values["controller_player_colour_2"],
                "controller_player_colour_3": values["controller_player_colour_3"],
                "controller_player_colour_4": values["controller_player_colour_4"],
                "controller_gauge_brightness": values["controller_gauge_brightness"],
                "weather_display": values["weather_display"],
                "weather_location": values["weather_location"],
                "weather_topbar_enabled": values["weather_topbar_enabled"],
                "weather_icon_style": values["weather_icon_style"],
                "weather_temperature_unit": values["weather_temperature_unit"],
                "night_mode_enabled": values["night_mode_enabled"],
                "night_mode_brightness": values["night_mode_brightness"],
                "night_mode": night_mode_status,
                "weather_brightness": values["weather_brightness"],
                "weather_shadow_cutoff": values["weather_shadow_cutoff"],
                "stripmine_integration_enabled": values["stripmine_integration_enabled"],
                "stripmine_detected": stripmine_detected,
                "tw3_steamrgb_integration_enabled": values["tw3_steamrgb_integration_enabled"],
                "tw3_steamrgb_detected": tw3_steamrgb_detected,
                "tw3_steamrgb_active": tw3_steamrgb_active,
                "stripmine_priority_artwork": values["stripmine_priority_artwork"],
                "stripmine_priority_performance": values["stripmine_priority_performance"],
                "stripmine_priority_weather": values["stripmine_priority_weather"],
                "stripmine_priority_controller": values["stripmine_priority_controller"],
                "stripmine_priority_light_events": values["stripmine_priority_light_events"],
                "stripmine_priority_game_launches": values["stripmine_priority_game_launches"],
                "stripmine_priority_customization": values["stripmine_priority_customization"],
                "stripmine_priority_screen_sync": values["stripmine_priority_screen_sync"],
                "stripmine_priority_audio_sync": values["stripmine_priority_audio_sync"],
                **{key: values[key] for key in values if key.startswith("weather_") and key.endswith("_variant")},
                "weather": weather_status,
                "customization": customization_status,
                "screen_sync": screen_sync_status,
                "audio_sync": audio_sync_status,
                "controllers": controller_status,
                "events": self.events.status(),
                "game": {"appid": self._game.appid, "title": self._game.title},
                "performance": {
                    "sample_age_s": max(0.0, now - sample.sampled_at) if sample.sampled_at else None,
                    "error": self.performance.error,
                    "gpu_load": sample.gpu_load,
                    "gpu_temperature": sample.gpu_temp_c,
                    "cpu_load": sample.cpu_load,
                    "cpu_temperature": sample.cpu_temp_c,
                    "logical_lit": sum(pixel != (0, 0, 0) for pixel in logical_performance),
                    "physical_lit": sum(pixel != (0, 0, 0) for pixel in physical_performance),
                },
                "thermal_protection": thermal_status,
                "artwork": art,
                "launch_artwork": launch_artwork_status,
                "countdown": countdown,
                "debug": {
                    "led_path": renderer.hardware.device_path if renderer else "/sys/class/leds/valve-leds[*]",
                    "last_write": renderer.last_write_at if renderer else 0.0,
                    "last_write_age_s": max(0.0, now - last_write_at) if last_write_at else None,
                    "writes": renderer.writes if renderer else 0,
                    "last_external": guard.last_external_at if guard else 0.0,
                    "last_external_age_s": max(0.0, now - last_external_at) if last_external_at else None,
                    "cooldown_remaining": guard_debug["cooldown_remaining"],
                    "stable_remaining": guard_debug["stable_remaining"],
                    "guard_state": "ready" if guard_debug["ready"] else "blocked",
                    "guard_reason": guard_debug["reason"],
                    "steam_priority": self._effective_steam_priority,
                    "steam_priority_reason": (
                        self._native_priority_reason_text
                        if self._effective_steam_priority and self._native_priority_reason_text
                        else self._steam_reason
                        if self._effective_steam_priority else ""
                    ),
                    "guard_hard_priority": guard_debug["hard_priority"],
                    "guard_hard_reason": guard_debug["hard_reason"],
                    "native_priority_kind": self._native_priority_kind,
                    "native_priority_reason": self._native_priority_reason_text,
                    "ignored_native_takeovers": self._ignored_native_takeovers,
                    "steam_lease_remaining_s": max(0.0, self._steam_active_until - now),
                    "launch_handoff_remaining_s": max(0.0, self._launch_handoff_until - now),
                    "context_transition_active": self._context_transition_active,
                    "context_transition_remaining_s": max(
                        0.0, self._context_transition_until - now,
                    ) if self._context_transition_active else 0.0,
                    "context_transition_from": self._context_transition_from,
                    "context_transition_to": self._context_transition_to,
                    "last_recovery_age_s": (
                        max(0.0, now - self._last_recovery_at)
                        if self._last_recovery_at else None
                    ),
                    "last_recovery_reason": self._last_recovery_reason,
                    "reverse_led_order": values["reverse_led_order"],
                    "engine_running": engine_running,
                    "decision_age_s": decision_age_s,
                    "last_runtime_error": self._last_runtime_error,
                    "last_runtime_error_age_s": (
                        max(0.0, now - self._last_runtime_error_at)
                        if self._last_runtime_error_at else None
                    ),
                    **runtime_debug,
                },
            }
