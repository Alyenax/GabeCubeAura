"""GabeCubeAura runtime orchestration.

Data collection stays in providers, ownership policy in Arbiter/VanillaGuard,
and all sysfs writes in Renderer.
"""

from __future__ import annotations

import os
import hashlib
import json
import threading
import time
import traceback
from signalbar.integration_api import ExternalPresentation as Assistant
from signalbar.core.profiles import Profiles
from datetime import datetime, timedelta

from signalbar import __version__
from signalbar.shutdown import ShutdownBudget
from signalbar.screen_sync_trace import ScreenSyncTrace
from signalbar.activation import ScreenSyncActivation
from signalbar.arbiter import Arbiter, VanillaGuard
from signalbar.hardware import ValveLedHardware
from signalbar.integration import LightEventLease, StripMineClaimReader, Tw3SteamRgbClaimReader
from signalbar.models import GameState, ProviderOutput, normalize_frame
from signalbar.providers import (
    ArtworkProvider, CountdownProvider, CustomizationProvider,
    EventProvider, IdleProvider, LaunchArtworkProvider, PerformanceProvider,
    ScreenSyncProvider, AudioSyncProvider,
)
from signalbar.providers.controller import ControllerProvider
from signalbar.providers.audio_sync import ADAPTIVE_STYLES
from signalbar.providers.onboarding import immersive_preview_output, synthetic_slow_prism_frame
from signalbar.providers.weather import weather_preview_condition, weather_variant_key, WeatherProvider
from signalbar.providers.faceplate_extension import FaceplateExtension
from signalbar.faceplate import (
    FaceplateCoordinator, FaceplatePreferencesStore, FaceplateSceneRouter,
    FaceplateSceneTicket, FaceplateWorker,
)
from signalbar.faceplate.scene_renderer import FaceplateRenderError, render_isolated
from signalbar.faceplate.automatic_dashboard import AutomaticDashboardBackgrounds
from signalbar.faceplate.source_projection import background_key, saturate_colours
from signalbar.faceplate.scenes import (
    SCENE_REVISION, build_dashboard_snapshot,
    solar_phase, visual_signature,
)
from signalbar.faceplate.v2_scenes import (
    V2_SCENE_REVISION, build_v2_dashboard_snapshot,
)
from signalbar.faceplate.v3_scenes import (
    V3_SCENE_REVISION, V3_THEME, build_v3_dashboard_snapshot,
)
from signalbar.faceplate.weather_artwork import (
    WEATHER_ARTWORK_THEMES, weather_artwork_cache_revision,
)
from signalbar.faceplate.coordinator import POWER_BUDGET, validate_gif
from signalbar.faceplate.artwork_dashboard import (
    REVISION as ARTWORK_DASHBOARD_REVISION,
    quantize_battery,
)
from signalbar.faceplate.status import FaceplateSteamState
from signalbar.faceplate.playtime import timer_facts
from signalbar.providers.current_players import CurrentPlayers
from signalbar.faceplate.player_city import PlayerCityCadence, REVISION as PLAYER_CITY_REVISION, content_key as player_city_key
from signalbar.renderer import Renderer
from signalbar.settings.store import DISPLAY_PRESET_RECIPES, DEFAULTS
from signalbar.thermal import ThermalProtection, THERMAL_SUSPENSION_MESSAGE

LED_OUTPUT_REFERENCE_BRIGHTNESS = 9


def faceplate_scene_cache_namespace(payload):
    """Version persistent scene files against code and compiled artwork.

    The cache survives plugin updates.  A content key describes live inputs
    such as weather and temperature, but it does not prove which installed RGB
    pack rendered the GIF.  Include both identities so an update can never
    resurrect an older V1/V2 render for an unchanged weather signature.
    """
    kind = str(payload.get("kind", ""))
    visual_theme = str(payload.get("visual_theme", ""))
    # Preserve the Lab183 pixel-cache generation; only the gain policy changed.
    parts = ["gabecubeaura", "encoded-rgb-peak-1", kind or "scene"]
    if kind == "player-city":
        parts.append(PLAYER_CITY_REVISION)
    if kind == "artwork-dashboard":
        parts.extend((ARTWORK_DASHBOARD_REVISION, str(payload.get("dashboard_pack_sha256", ""))))
    if visual_theme in WEATHER_ARTWORK_THEMES:
        parts.append(weather_artwork_cache_revision(visual_theme, kind, payload.get("condition")))
    return ":".join(parts)


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
                 event_lease=None, stripmine_claim=None, tw3_steamrgb_claim=None,
                 faceplate=None, faceplate_preferences=None,
                 faceplate_runtime_path=None, screen_sync_trace=None):
        self.settings = settings
        state_directory = os.path.dirname(getattr(settings, "path", cache_path))
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
        self._timer_power_thread = None
        self._timer_power_lock = threading.Lock()
        self.performance = PerformanceProvider()
        self.thermal_protection = ThermalProtection()
        self.screen_sync = ScreenSyncProvider()
        self.screen_sync_trace = screen_sync_trace if screen_sync_trace is not None else ScreenSyncTrace()
        self.screen_sync.capture.trace = self.screen_sync_trace
        self._screen_sync_trace_route = None
        self._screen_sync_trace_delivery = None
        self.audio_sync = AudioSyncProvider()
        self.screen_sync_activation = ScreenSyncActivation()
        self.events = EventProvider()
        self.events.set_variants(settings.all())
        self.controllers = ControllerProvider()
        self.weather = WeatherProvider(
            cache_path=os.path.join(state_directory, "weather-last-sample.json"),
        )
        initial = settings.all()
        plugin_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        self._faceplate_state_directory = state_directory
        self.faceplate_extension = FaceplateExtension(os.path.join(state_directory, 'faceplate-source-projection'))
        self._faceplate_extension_source = None
        self._faceplate_extension_device = None
        self._faceplate_extension_present = False
        self._faceplate_extension_target = None
        self._faceplate_extension_refresh = None
        self._faceplate_extension_delivery_basis = None
        self._faceplate_runtime_path = os.fspath(
            faceplate_runtime_path or os.path.join(
                state_directory, "faceplate-runtime.json",
            )
        )
        self._faceplate_control_path = os.path.join(
            os.path.dirname(self._faceplate_runtime_path), "faceplate-control.json",
        )
        self._faceplate_control_id = ""
        self._faceplate_scene_cache = os.path.join(
            state_directory, "faceplate-scene-cache",
        )
        self.faceplate_preferences = faceplate_preferences or FaceplatePreferencesStore(
            os.path.join(state_directory, "faceplate-preferences.json"),
            calibrated=getattr(settings, "_first_install_defaults", False),
        )
        self.faceplate_router = FaceplateSceneRouter(self.faceplate_preferences)
        self._faceplate_configuration_lock = threading.RLock()
        self._faceplate_configuration_error = ""
        self._faceplate_home_artwork_prepared = False
        self.faceplate = faceplate or FaceplateCoordinator(
            os.path.join(plugin_root, "assets", "faceplate"),
            os.path.join(state_directory, "faceplate-lab-state.json"),
            logger,
        )
        self._automatic_dashboard_backgrounds = AutomaticDashboardBackgrounds()
        self.faceplate.configure(
            initial["faceplate_lab_enabled"], initial["faceplate_brightness"],
        )
        if isinstance(self.faceplate, FaceplateCoordinator):
            self.faceplate.flash.configure(initial.get("faceplate_flash_protection_enabled", True))
        if hasattr(self.faceplate, "configure_artwork"):
            self.faceplate.configure_artwork(
                initial["faceplate_artwork_style"],
                initial["faceplate_logo_position"],
                initial["faceplate_artwork_profiles"],
                initial["faceplate_rotate_180"],
            )
        self.faceplate_worker = FaceplateWorker(
            self._handle_faceplate_scene,
            enabled=initial["faceplate_lab_enabled"],
            logger=logger,
            on_complete=self._write_faceplate_runtime_status,
            on_idle=self._flush_faceplate_statistics,
        )
        self.faceplate_steam_state = FaceplateSteamState()
        self._faceplate_status_base_keys = {}
        self._faceplate_status_recent = {}
        self._faceplate_status_battery = {}
        self._faceplate_follow_key = None
        self._faceplate_next_reconcile = 0.0
        self._faceplate_preview_until = 0.0
        self._faceplate_timer_end = None
        self._faceplate_timer_finished_id = ""
        self._faceplate_runtime_serialized = ""
        self._faceplate_runtime_running = False
        self._faceplate_weather_summary = {}
        self.current_players = CurrentPlayers(transport='decky')
        self.player_city = PlayerCityCadence(os.path.join(state_directory, 'player-city-state.json'))
        self._player_city_context = 0
        self._player_city_screensaver_active = False
        self._faceplate_scene_retry_at = 0.0
        self._faceplate_suspended = False
        self._assistant_system_suspended = False
        self._onboarding_applying = False
        self._faceplate_power_target = None
        self._display_power_lock = threading.RLock()
        self._assistant_route_lock = threading.RLock()
        self._display_faceplate_off = False
        self._display_faceplate_restore = False
        self._display_faceplate_connected = False
        self._faceplate_resume_requested = False
        self._faceplate_power_retry_at = 0.0
        self._faceplate_power_status = {
            "target": None, "ok": True, "attempts": 0,
            "reason": "startup", "error": "",
        }
        self._faceplate_cached_weather_key = ""
        self._faceplate_clock_anchor = None
        self._faceplate_local_offset = None
        self._faceplate_native_epoch = 0
        self._faceplate_device_signature = None
        self._faceplate_dashboard_target_minute = None
        self._faceplate_artwork_dashboard_target_minute = None
        self._faceplate_artwork_dashboard_session_minute = 0
        self._faceplate_artwork_dashboard_battery = None
        self._faceplate_artwork_dashboard_lead_seconds = 0.0
        from signalbar.steam.dashboard_stats import DashboardStats
        self.dashboard_stats = DashboardStats()
        self._faceplate_game_started_monotonic = None
        self._session_start_known = False
        self._game_context_observed = False
        self.launch_artwork.configure(
            initial["launch_artwork_animation_enabled"], initial["launch_artwork_pattern"],
            initial["launch_artwork_colour_count"], initial["launch_artwork_duration_seconds"],
        )
        self.weather.configure(
            initial["weather_location"], initial["weather_display"],
            initial["weather_topbar_enabled"], initial["night_mode_enabled"],
            self._faceplate_weather_required(initial),
        )
        self.idle = IdleProvider()
        self.arbiter = Arbiter()
        self._lock = threading.RLock()
        self._settings_apply_lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._runtime_failures = []
        self._faceplate_maintenance_retry_at = 0.0
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
        self._display_preset_preview_started_at = 0.0
        self._display_preset_preview_until = 0.0
        self._display_preset_preview_owner = ''
        self._display_preset_preview_colors = []
        self._display_preset_preview_on_bar = False
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
        self.ambience = Profiles(state_directory, settings, self._apply_ambience)
        initial = self.settings.all()
        self._assistant_wake_allowed = self._assistant_wake_policy(initial)
        self.assistant = Assistant(
            state_directory, os.path.join(plugin_root, "assets", "faceplate"),
            lambda: {},
            self.faceplate_game_snapshot, self._assistant_acquire,
            self._assistant_release, self._assistant_preflight,
            get_facts=self._assistant_facts,
            get_face_state=self._assistant_face_state,
            execute_utility=self._assistant_utility,
            wake_allowed=self._assistant_wake_permitted,
            wake_reason=self._assistant_wake_reason,
            visual_capabilities=self._assistant_visual_capabilities,
        )

    def _apply_ambience(self, overlay):
        previous = self.settings.all()
        values = self.settings.set_overlay(overlay)
        changes = {key: value for key, value in values.items() if previous.get(key) != value}
        if changes:
            self._apply_settings(values, changes)

    def _assistant_utility(self, action, argument):
        if action == 'timer_start':
            self.start_free_timer(int(argument))
            return {'seconds': int(argument)*60}
        if action == 'timer_add':
            return {'active': self.countdown.extend_personal(int(argument)*60), 'seconds': int(argument)*60}
        if action == 'timer_cancel':
            active = self.countdown.personal_status()['active']
            self.stop_free_timer()
            return {'active': active}
        if action == 'profile_auto':
            self.ambience.activate('')
            return {'active': False}
        if action == 'profile_apply':
            identifier = self.ambience.named(argument)
            if not identifier: return {'found': False}
            self.ambience.activate(identifier)
            return {'found': True}
        raise ValueError('Unsupported local utility')

    def _assistant_face_state(self):
        # Snapshot only: never probe USB or take the serial lock at LED cadence.
        return {'asset':self.faceplate.last_asset,'confirmed':self.faceplate.last_synchronized,
                'powered':self.faceplate.powered,
                'generation':self.faceplate_worker.completed_generation}

    def _assistant_facts(self):
        """Read existing samples once per spoken request; never start a sensor job."""
        values = self.settings.all()
        weather = self.weather.status(values)
        sample = self.performance.sample
        age = time.monotonic()-sample.sampled_at if sample.sampled_at else None
        fresh = age is not None and 0 <= age < 30
        controllers = self.controllers.status(values).get("controllers", [])
        started = getattr(self, '_faceplate_game_started_monotonic', None)
        # Detection begins at this plugin's observed session, never from a GIF
        # clock prediction. A recovered already-running game has unknown age.
        duration = int(max(0, time.monotonic()-started)) if started is not None and getattr(self, '_session_start_known', False) else None
        return {"local_time":time.strftime("%H:%M"), "session_seconds": duration,
            "personal_timer": self.countdown.personal_status() if hasattr(self, 'countdown') else {'active': False, 'remaining_seconds': 0},
            "weather":{key:weather.get(key) for key in ("phase","condition","temperature_c","age_s")},
            "system_status":{key:getattr(sample,key,None) if fresh else None
                             for key in ("cpu_load","gpu_load","cpu_temp_c","gpu_temp_c")},
            "controllers":[{"player":index+1,"battery_percent":controller.get("percent"),"charging":controller.get("charging")}
                           for index,controller in enumerate(controllers[:4])]}

    def _assistant_preflight(self):
        if (self._stop.is_set() or getattr(self, '_assistant_system_suspended', False)
                or getattr(self, '_onboarding_recovery_blocked', False)
                or getattr(self, '_onboarding_applying', False)
                or self.thermal_protection.status().get("active")):
            raise RuntimeError("Assistant suspendu ou protection thermique active.")
        return self._assistant_visual_capabilities()

    def _screensaver_owns_matrix(self):
        adapter = getattr(self, 'jsaux_broker_adapter', None)
        return bool(adapter is not None and adapter.holds_display())

    def _assistant_visual_capabilities(self):
        """Decorative leases are optional; never probe or open USB for the voice."""
        values = self.settings.all()
        safe = not self._stop.is_set() and not self.thermal_protection.active
        return {
            'bar_available': bool(safe and self._available
                and values.get('mode') != 'disabled' and not values.get('steam_control_enabled')
                and not self._display_bar_off(values)),
            'matrix_available': bool(safe and not self._screensaver_owns_matrix() and values.get('faceplate_lab_enabled')
                and not self._display_panel_off(values) and not self._faceplate_suspended
                and getattr(self, '_faceplate_extension_present', False)
                and self.faceplate.powered is not False),
        }

    def _assistant_detach_visuals(self, reason, *, matrix=True, bar=True):
        detach = getattr(self.assistant, 'detach_visuals', None)
        if callable(detach):
            detach(reason, matrix=matrix, bar=bar)

    def _assistant_holds_matrix(self):
        assistant = getattr(self, 'assistant', None)
        return bool(not self._screensaver_owns_matrix() and assistant is not None and getattr(assistant, 'active', False) and
                    (getattr(assistant, 'visual_available', False) or getattr(assistant, 'leased', False)))

    def _assistant_wake_permitted(self):
        if (not self._assistant_wake_allowed or self._stop.is_set()
                or getattr(self, '_onboarding_recovery_blocked', False)
                or getattr(self, '_onboarding_applying', False)
                or getattr(self, '_assistant_system_suspended', False) or self.thermal_protection.active):
            return False
        return True

    def _assistant_wake_reason(self):
        if self._stop.is_set():return 'stopping'
        if getattr(self,'_assistant_system_suspended',False):return 'system-suspended'
        if self.thermal_protection.active:return 'thermal'
        if getattr(self,'_onboarding_recovery_blocked',False) or getattr(self,'_onboarding_applying',False):return 'setup'
        if not self._assistant_wake_allowed:return 'user-disabled'
        return ''

    def _assistant_wake_policy(self, values):
        # Only settings/context changes compute policy. The 50-ms wake loop
        # reads a boolean and hardware flags, never deep-copies all settings.
        return bool(values.get('gabe_assistant', {}).get('enabled')
                    and not getattr(self, '_onboarding_recovery_blocked', False)
                    and not getattr(self, '_assistant_system_suspended', False))

    def _assistant_acquire(self, data, manifest, cancel):
        # submit(cancel_active=True) cancels the previous route and replaces
        # its pending request atomically. Retain one live worker/serial owner.
        from signalbar.core.cancellation import Cancelled
        # A cancelled uploader must never enqueue after the restoration route.
        # Hold only during queue hand-off, never during a USB transfer/ACK.
        with self._assistant_route_lock:
            if cancel.is_set():
                raise Cancelled()
            if self._screensaver_owns_matrix():
                # Capability may have changed since preflight. Drop decoration
                # without replacing the delegated GIF or cancelling the voice.
                self._assistant_detach_visuals('screensaver-owns-matrix', matrix=True, bar=False)
                return
            self.faceplate_worker.configure(True)
            scene = 'external:'+manifest.get('scene_id','presentation')
            generation = self.faceplate_worker.submit(scene, {
                "kind": "external", "data": data, "manifest": manifest,
                "session_cancel": cancel,
            }, {"scene_class": "external", "cancel_active": True})
        if not generation: raise RuntimeError("La file faceplate est indisponible.")
        try:
            receipt = self.faceplate_worker.wait_for_completion(generation, cancel, 30)
        except TimeoutError as error:
            raise RuntimeError("La faceplate n’a pas confirmé le visage à temps.") from error
        if receipt is None or cancel.is_set():
            raise Cancelled()
        result = receipt["result"]
        if receipt["scene"] != scene or receipt["error"] or result.get("error") or not result.get("synchronized"):
            raise RuntimeError("Le visage n’a pas pu être confirmé sur la faceplate.")

    def _assistant_release(self):
        with self._assistant_route_lock:
            self.faceplate_worker.cancel_scene_class("external")
            values = self.settings.all()
            self.faceplate_worker.configure(bool(values["faceplate_lab_enabled"] and not self._faceplate_suspended and not self._stop.is_set()))
            self._faceplate_follow_key = None
            self._faceplate_next_reconcile = 0.0
            if not self._stop.is_set():
                return self._reconcile_faceplate("external-finished-current-route", force=True)

    def _info(self, message):
        if self.log:
            self.log.info(f"[GabeCubeAura] {message}")

    def _warn(self, message):
        if self.log:
            self.log.warning(f"[GabeCubeAura] {message}")

    def _faceplate_weather_required(self, values):
        """Weather fetching follows Faceplate routes, never LED selection."""
        if not values.get("faceplate_lab_enabled"):
            return False
        preferences = self.faceplate_preferences.read()
        from signalbar.dashboard_settings import dashboard_context
        for game, scene in ((False, preferences.home_scene), (True, preferences.game_scene)):
            if not game and scene in {'artwork', 'artwork-dashboard'}:
                appid = int(values.get('faceplate_dashboard_home_appid', 0) or 0)
                library = getattr(self.faceplate, 'steamgriddb', None)
                if not appid or library is None or not library.home_dashboard_manifest(appid):
                    return True  # The missing-artwork fallback needs a weather provider too.
            if scene in {'weather', 'dashboard', 'player-city'}:
                return True
            if scene == 'artwork-dashboard':
                content = dashboard_context(values, game)
                if content['show_weather'] or (content['show_bottom_row']
                        and content['bottom_mode'] in {'next_hour', 'today'}
                        and (not game or content['game_row'] == 'existing')):
                    return True
        return False

    def update_faceplate_routing(self, home_scene=None, game_scene=None,
                                 expected_revision=None, performance_risk_accepted=False):
        with self._faceplate_configuration_lock:
            return self._commit_faceplate_routing(home_scene, game_scene, expected_revision,
                                                   performance_risk_accepted)

    def _commit_faceplate_routing(self, home_scene, game_scene, expected_revision, performance_risk_accepted):
        if "performance" in (home_scene, game_scene):
            raise ValueError("CPU/GPU is available on the light bar and in the interface, not on the JSAUX matrix")
        snapshot = self.faceplate_preferences.update(
            home_scene=home_scene, game_scene=game_scene,
            expected_revision=expected_revision,
        )
        # An explicit route choice establishes setup; a revision alone never does.
        self.settings.update({"faceplate_setup_completed": True})
        if home_scene in {"dashboard", "artwork-dashboard"}:
            self.settings.update({"faceplate_dashboard_home_source": "artwork" if home_scene == "artwork-dashboard" else "weather"})
        # Persistence above is the commit point. Never roll back a newer writer
        # when propagation fails. A retry/restart applies the latest snapshot.
        try:
            values = self.settings.all()
            self.weather.configure(
                values["weather_location"], values["weather_display"],
                values["weather_topbar_enabled"], values["night_mode_enabled"],
                self._faceplate_weather_required(values),
            )
            self._faceplate_next_reconcile = 0.0
            self._reconcile_faceplate("routing-change", force=True)
            self._faceplate_configuration_error = ""
        except Exception:
            self._faceplate_configuration_error = "Saved display preferences could not be applied. Retry or restart GabeCubeAura."
            raise RuntimeError(self._faceplate_configuration_error)
        return snapshot.as_dict()

    def update_faceplate_visual_theme(self, visual_theme, expected_revision=None):
        """Compatibility setter: apply one legacy renderer to every scene."""
        snapshot = self.faceplate_preferences.update(
            visual_theme=visual_theme,
            expected_revision=expected_revision,
        )
        self._faceplate_next_reconcile = 0.0
        self._reconcile_faceplate("visual-theme-change", force=True)
        return snapshot.as_dict()

    def update_faceplate_scene_theme(self, scene_kind, scene_theme,
                                     expected_revision=None):
        """Persist one renderer choice without altering the other scenes."""
        snapshot = self.faceplate_preferences.update(
            scene_kind=scene_kind, scene_theme=scene_theme,
            expected_revision=expected_revision,
        )
        self._faceplate_next_reconcile = 0.0
        self._reconcile_faceplate(f"{scene_kind}-theme-change", force=True)
        return snapshot.as_dict()

    def faceplate_game_snapshot(self):
        """Return only the game identity needed by isolated artwork jobs."""
        with self._lock:
            return {"appid": self._game.appid, "title": self._game.title}

    def refresh_faceplate(self, reason="external-change"):
        return self._reconcile_faceplate(str(reason)[:96], force=True)

    def _player_city_status(self):
        cadence, provider = getattr(self, 'player_city', None), getattr(self, 'current_players', None)
        return cadence.status(provider.status()) if cadence is not None and provider is not None else {}

    def claim_player_city_poll(self):
        # Configure from the real current route/device, never a library page.
        self._configure_player_city()
        return self.current_players.claim()

    def complete_player_city_poll(self, request_id, appid, payload=None, error_code=''):
        self._configure_player_city()
        accepted = self.current_players.complete(request_id, appid, payload, error_code)
        if accepted:
            self._faceplate_next_reconcile = 0.0
            self._reconcile_faceplate('player-city-measurement')
            self._write_faceplate_runtime_status()
        return accepted

    def faceplate_delivery_status(self):
        """Current queued/delivered state without a new USB probe or render."""
        values = self.settings.all()
        paused = (
            "disabled" if not values.get("faceplate_lab_enabled") or self._display_panel_off(values)
            else "suspended" if self._faceplate_suspended
            else "external" if self._assistant_holds_matrix()
            else "power-recovery" if self._faceplate_power_target is not None
            else ""
        )
        return {
            **self.faceplate.cached_status(),
            "home_artwork_prepared": getattr(self, '_faceplate_home_artwork_prepared', False),
            "automation": self.faceplate_worker.status(),
            "routing": self.faceplate_router.status(),
            "player_city": self._player_city_status(),
            "steam_status": self.faceplate_steam_state.snapshot().as_dict(),
            "power_recovery": {
                **self._faceplate_power_status,
                "suspended": self._faceplate_suspended,
                "retry_pending": self._faceplate_power_target is not None,
                'route_state': getattr(self, '_faceplate_route_recovery', {}).get('state', 'idle'),
                'route_attempts': getattr(self, '_faceplate_route_recovery', {}).get('attempts', 0),
            },
            "apply_deferred_reason": paused,
        }

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self.weather.start()
            self.dashboard_stats.start()
            values = self.settings.all()
            self._assistant_wake_allowed = self._assistant_wake_policy(values)
            if (values.get("faceplate_lab_enabled")
                    and values.get("faceplate_power_mode") == "auto"):
                # Do not block Decky startup on USB. The engine loop performs
                # the first attempt immediately and keeps retrying if the
                # panel enumerates a little later than the plugin.
                self._faceplate_power_target = True
                self._faceplate_power_retry_at = 0.0
            self._faceplate_runtime_running = True
            self._write_faceplate_runtime_status()
            self._thread = threading.Thread(target=self._run, name="signalbar-engine", daemon=True)
            self._thread.start()
        self.assistant.start()

    def _flush_faceplate_statistics(self):
        if isinstance(self.faceplate, FaceplateCoordinator):
            self.faceplate.flash.flush()
            self.faceplate.flush_statistics()

    def stop(self, timeout=None):
        budget = ShutdownBudget(timeout)
        self._stop.set()
        self.faceplate_router.invalidate("plugin-stopped")
        self.countdown.end_action.cancel('plugin-stopped')
        adapter = getattr(self, 'jsaux_broker_adapter', None)
        if isinstance(getattr(self.faceplate,'_continuous_return',None),dict):
            generation=self.faceplate_worker.submit('return-stop',{'kind':'return-stop'},
                {'scene_class':'control','cancel_active':True,'reason':'plugin-stopped'})
            if generation:self.faceplate_worker.wait_for_completion(generation,threading.Event(),budget.remaining(.8))
        if adapter is not None:
            adapter.stop()
        budget.call(self.assistant.stop)
        power_thread = self._timer_power_thread
        if power_thread and power_thread.is_alive():
            power_thread.join(timeout=budget.remaining(.5))
        budget.call(self.dashboard_stats.stop)
        budget.call(self.weather.stop)
        if getattr(self, 'current_players', None) is not None:
            budget.call(self.current_players.stop)
        budget.call(self.faceplate_worker.stop)
        if isinstance(self.faceplate, FaceplateCoordinator):
            self.faceplate.flash.flush(force=True)
            self.faceplate.flush_statistics(force=True)
        budget.call(self.faceplate_extension.stop)
        self._faceplate_runtime_running = False
        self._write_faceplate_runtime_status()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=budget.remaining(2.0))
        budget.call(self.screen_sync.stop)
        self.screen_sync_trace.close(timeout=budget.remaining(0.5))
        budget.call(self.audio_sync.stop)
        self.screen_sync_activation.stop_preview()
        with self._lock:
            self.events.clear_transients()
            self.launch_artwork.cancel()
            self.events.clear_recording()
            self.faceplate_steam_state.mark_unknown()
            self.controllers.clear()
            if self._renderer:
                self._renderer.relinquish(restore_if_owned=True)
            self.event_lease.release()
            self.stripmine_claim.release()
            self._light_event_announced_at = 0.0
            self._owner = "Valve"
            self._decision = "none"
            self._decision_at = time.monotonic()

    def report_dashboard_stats(self, appid, stats):
        with self._lock:
            if type(appid) is not int or appid <= 0 or appid != self._game.appid:
                return False
            return self.dashboard_stats.update_live(appid, stats)

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
                self.dashboard_stats.select_game(appid)
                # A Steam Families deadline belongs to the game session that
                # produced it. Never leak it into the next game or after exit.
                self.countdown.stop("parental")
                self.events.clear_recording()
                self.faceplate_steam_state.mark_unknown()
                self.launch_artwork.cancel()
                self._launch_handoff_until = 0.0
                now = time.monotonic()
                self._faceplate_game_started_monotonic = now if appid > 0 else None
                self._session_start_known = bool(appid > 0 and (launch or self._game_context_observed))
                self._faceplate_artwork_dashboard_target_minute = None
                self._faceplate_artwork_dashboard_session_minute = 0
                self._faceplate_artwork_dashboard_battery = None
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
            self._game_context_observed = True
            self.controllers.cancel_for_settings(self.settings.all(), self._game.running)
            if changed and self._game.running and bool(launch):
                self._launch_handoff_until = time.monotonic() + 1.0
                self._refresh_launch_palettes(self._game.appid)
                self.launch_artwork.arm(self._game.appid)
        if changed:
            if appid and getattr(self,'assistant',None): self.assistant.remember_game(appid)
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
            self._faceplate_follow_key = None
            self._faceplate_next_reconcile = 0.0
            self._sync_display_power_policy()
            # The render loop may already have reconciled the new context
            # while capture/power teardown ran. Reuse its identical ticket.
            self._reconcile_faceplate("automatic-game-change")

    def _apply_faceplate_power(self, enabled, reason, attempts=1):
        """Apply a volatile panel state with a bounded, observable retry."""
        result = {"ok": False, "powered": None, "error": "not attempted"}
        for attempt in range(max(1, int(attempts))):
            result = self.faceplate.set_power(
                bool(enabled), str(reason)[:96], lock_timeout=0.5,
            )
            self._faceplate_power_status = {
                "target": bool(enabled), "ok": bool(result.get("ok")),
                "attempts": attempt + 1, "reason": str(reason)[:96],
                "error": str(result.get("error", ""))[:180],
                'deferred_to_route': bool(result.get('deferred_to_route')),
            }
            if result.get('deferred_to_route'):
                with self._display_power_lock:
                    if self._faceplate_power_target is True:
                        self._faceplate_power_target = None
                        self._faceplate_power_retry_at = 0.0
                self._faceplate_resume_requested = True
                self._faceplate_follow_key = None
                self._faceplate_next_reconcile = 0.0
                return result
            if result.get("ok"):
                with self._display_power_lock:
                    if self._faceplate_power_target is None or self._faceplate_power_target == bool(enabled):
                        self._faceplate_power_target = None
                        self._faceplate_power_retry_at = 0.0
                return result
            if attempt + 1 < attempts:
                time.sleep(0.1)
        with self._display_power_lock:
            if self._faceplate_power_target is None or self._faceplate_power_target == bool(enabled):
                self._faceplate_power_target = bool(enabled)
                self._faceplate_power_retry_at = time.monotonic() + 2.0
        return result

    def _service_faceplate_power_retry(self, now=None):
        now = time.monotonic() if now is None else float(now)
        target = self._faceplate_power_target
        if target is None or now < self._faceplate_power_retry_at:
            return False
        try:
            result = self._apply_faceplate_power(
                target, "automatic power recovery", attempts=1,
            )
        except Exception as error:
            # This runs before the LED loop's renderer try/except. A serial
            # driver/adapter fault must never silently kill both displays.
            with self._display_power_lock:
                self._faceplate_power_status = {'target': target, 'ok': False,
                    'attempts': 1, 'reason': 'automatic power recovery',
                    'error': f'{type(error).__name__}: {error}'[:180]}
                if self._faceplate_power_target == target:
                    self._faceplate_power_retry_at = time.monotonic() + 2.0
            self._warn('Faceplate power failure isolated: ' + str(error)[:120])
            return False
        if result.get("ok") and target:
            self._faceplate_follow_key = None
            self._faceplate_next_reconcile = 0.0
        return bool(result.get("ok"))

    def _display_bar_off(self, values=None):
        values = values or self.settings.all()
        return not values['signalbar_enabled'] or self.settings.display_for(self._game.appid)['selected'] in {'bar_off', 'displays_off'}

    def _display_panel_off(self, values=None):
        values = values or self.settings.all()
        return not values['signalbar_enabled'] or self.settings.display_for(self._game.appid)['selected'] == 'displays_off'

    def _sync_display_power_policy(self, presence=None):
        with self._display_power_lock:
            self._sync_display_power_policy_locked(presence)

    def _sync_display_power_policy_locked(self, presence=None):
        """Queue volatile power on the existing loop, never USB in an RPC.

        Saved routes, brightness and independent manual/sleep suspension are
        untouched. Overlapping Off reasons share one restoration lease.
        """
        values = self.settings.all()
        off = self._display_panel_off(values)
        bar_off = self._display_bar_off(values)
        self._assistant_wake_allowed = self._assistant_wake_policy(values)
        if bar_off or values.get('steam_control_enabled'):
            self._assistant_detach_visuals('bar-unavailable', matrix=False, bar=True)
        if off:
            self._assistant_detach_visuals('matrix-off', matrix=True, bar=False)
            if not self._display_faceplate_off:
                self._display_faceplate_restore = self.faceplate.powered is not False and not self._faceplate_suspended
                self._display_faceplate_off = True
                self.faceplate_worker.configure(False)
                if self._faceplate_power_target is True:
                    self._faceplate_power_target = None
            if presence is not None:
                connected = bool(presence.get('available'))
                reconnected = connected and not self._display_faceplate_connected
                self._display_faceplate_connected = connected
                if connected and (self.faceplate.powered is not False or reconnected) and self._faceplate_power_target is not False:
                    self._faceplate_power_target = False
                    self._faceplate_power_retry_at = 0.0
        elif self._display_faceplate_off:
            self._display_faceplate_off = False
            self._display_faceplate_connected = False
            if not self._faceplate_suspended:
                self._faceplate_power_target = None
                self._faceplate_power_retry_at = 0.0
                if self._display_faceplate_restore:
                    self._faceplate_power_target = True
                    self._faceplate_resume_requested = bool(values['faceplate_lab_enabled'])
            self._display_faceplate_restore = False
            self.faceplate_worker.configure(bool(values['faceplate_lab_enabled'] and not self._faceplate_suspended))
            self._faceplate_follow_key = None
            self._faceplate_next_reconcile = 0.0

    def suspend_faceplate(self, kind="sleep"):
        """Cancel scene traffic and reliably darken the USB-powered panel."""
        self._faceplate_suspended = True
        self.faceplate_router.invalidate("system-suspended")
        self._assistant_system_suspended = True
        self.assistant.cancel()
        self.faceplate_worker.configure(False)
        return self._apply_faceplate_power(
            False, f"automatic {str(kind)[:32]}", attempts=4,
        )

    def set_faceplate_power(self, enabled, reason="Decky control"):
        """Honor an explicit user choice over any automatic pending retry."""
        if enabled and self._display_panel_off():
            return {"ok": False, "powered": self.faceplate.powered,
                    "error": "Enable GabeCubeAura and select an active display before powering on the Faceplate"}
        self._faceplate_power_target = None
        if not enabled:
            self._display_faceplate_restore = False
            self._faceplate_suspended = True
            self.faceplate_router.invalidate("manual-off")
            self._assistant_detach_visuals('matrix-off', matrix=True, bar=False)
        self._faceplate_power_retry_at = 0.0
        if enabled:
            self._faceplate_suspended = False
            self.faceplate_worker.configure(bool(
                self.settings.all().get("faceplate_lab_enabled")
            ))
        result = self.faceplate.set_power(bool(enabled), reason)
        self._faceplate_power_status = {
            "target": bool(enabled), "ok": bool(result.get("ok")),
            "attempts": 1, "reason": str(reason)[:96],
            "error": str(result.get("error", ""))[:180],
            'deferred_to_route': bool(result.get('deferred_to_route')),
        }
        if (result.get("ok") or result.get('deferred_to_route')) and enabled:
            if result.get('deferred_to_route') and isinstance(self.faceplate, FaceplateCoordinator):
                self.faceplate.retry_uncertain_restore()
            self._faceplate_resume_requested = True
            self._faceplate_follow_key = None
            self._faceplate_next_reconcile = 0.0
            self._reconcile_faceplate("manual-power-on", force=True)
        return result

    def activate_faceplate_setup(self):
        """Apply explicit setup consent through the same path as Decky On.

        Called after the settings commit, never under its lock. A queued
        intention is not a transfer receipt. The UI waits for the current
        route's confirmed delivery; failed power commands use the normal loop.
        """
        with self._display_power_lock:
            values = self.settings.all()
            if (not values.get('faceplate_lab_enabled') or self._display_panel_off(values)
                    or self._assistant_system_suspended):
                return False
            self.faceplate_router.invalidate('faceplate-setup')
            self._faceplate_route_recovery = {}
        try:
            # Keep a stale autonomous image dark until the current route ACK.
            result = self.set_faceplate_power(True, 'automatic power recovery')
        except Exception as error:
            result = {'ok': False, 'error': type(error).__name__}
        if result.get('ok') or result.get('deferred_to_route'):
            return True
        with self._display_power_lock:
            if not self._faceplate_suspended and not self._display_panel_off():
                self._faceplate_power_target = True
                self._faceplate_power_retry_at = time.monotonic() + 2.0
                self._faceplate_power_status = {
                    'target': True, 'ok': False, 'attempts': 1,
                    'reason': 'Faceplate setup', 'error': str(result.get('error', ''))[:180],
                }
        return False

    def resume_faceplate(self):
        """Power on, re-enable the worker and reassert the current scene."""
        self.countdown.end_action.cancel('system-resumed')
        values = self.settings.all()
        self.set_screen_sync_context('steam-screensaver',False,'waiting','resume')
        self._assistant_system_suspended = False
        self._assistant_wake_allowed = self._assistant_wake_policy(values)
        if not values.get("faceplate_lab_enabled") or values.get("faceplate_power_mode") != "auto":
            return {"ok": True, "powered": None, "skipped": True, "error": ""}
        self._faceplate_suspended = False
        self._sync_display_power_policy()
        if self._display_panel_off(values):
            return self._apply_faceplate_power(False, 'resume with displays off', attempts=3)
        self.faceplate_worker.configure(bool(values.get("faceplate_lab_enabled")))
        adapter=getattr(self,'jsaux_broker_adapter',None)
        dark_restore=adapter is not None and adapter.requires_exit_blank() is True
        result = self._apply_faceplate_power(
            not dark_restore, "screensaver-exit" if dark_restore else "automatic resume", attempts=3,
        )
        self._faceplate_follow_key = None
        self._faceplate_next_reconcile = 0.0
        # Resume is already an explicit resynchronisation event. Reset the
        # clock baseline so the journal keeps the more useful resume reason.
        self._faceplate_clock_anchor = None
        self._faceplate_artwork_dashboard_target_minute = None
        if result.get("ok") or result.get('deferred_to_route'):
            self._reconcile_faceplate("steam-machine-resume", force=True)
        return result

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
        if active and not getattr(self, '_player_city_screensaver_active', False):
            city = getattr(self, 'player_city', None)
            if city is not None:
                city.allow_screensaver_refresh(self._game.appid)
        self._player_city_screensaver_active = bool(active)
        self.screen_sync_activation.set_screensaver(active, state, detail)
        adapter = getattr(self, 'jsaux_broker_adapter', None)
        if adapter is not None:
            adapter.observe_steam(active, state,source=detail)
        return True

    def _broker_allowed(self, values):
        return self._broker_decision(values)[0]

    def _broker_decision(self, values):
        """Ordered, short-circuit matrix admission; retain the first blocker.

        Provider status methods can advance their own queues. Do not poll them
        again for diagnostics or evaluate predicates the old chain skipped.
        """
        countdown = self.countdown.status(allow_parental=values.get('parental_countdown_enabled', True) and self._game.running)
        timer_priority = countdown.get('active') and countdown.get('remaining_seconds', float('inf')) <= 300
        event_evidence={}
        def event_active():
            status=self.events.status()
            kind=status.get('kind')
            if kind in ('notification','achievement','screenshot','record-start','record-stop'):
                event_evidence['kind']=kind
            if status.get('active') and kind in ('notification','achievement','screenshot'):
                # These short signals own only the LED bar during a live Steam
                # screensaver. Do not revoke its matrix lease (which fences
                # this activation). Read the existing bounded context only;
                # no new event poll, Steam query, hardware read or GIF write.
                activation=getattr(self,'screen_sync_activation',None)
                if self._screensaver_owns_matrix() or activation is not None and activation.status().get('screensaver_active'):
                    return False
            return status.get('active')
        checks=(
            ('plugin-disabled',lambda:not values.get('signalbar_enabled')),
            ('faceplate-disabled',lambda:not values.get('faceplate_lab_enabled')),
            ('onboarding-recovery',lambda:getattr(self,'_onboarding_recovery_blocked',False)),
            ('onboarding-applying',lambda:getattr(self,'_onboarding_applying',False)),
            ('mode-disabled',lambda:values.get('mode')=='disabled'),
            ('panel-route-off',lambda:self._display_panel_off(values)),
            ('faceplate-suspended',lambda:self._faceplate_suspended),
            ('power-target-off',lambda:self._faceplate_power_target is False),
            ('panel-powered-off',lambda:self.faceplate.powered is False),
            ('engine-stopping',lambda:self._stop.is_set()),
            ('thermal-protection',lambda:self.thermal_protection.active),
            ('steam-explicit-lease',lambda:time.monotonic()<self._steam_active_until),
            ('steam-effective-priority',lambda:getattr(self,'_effective_steam_priority',False)),
            ('countdown-last-5-min',lambda:timer_priority),
            ('external-matrix-hold',lambda:self._assistant_holds_matrix()),
            ('light-event-active',event_active),
            ('launch-artwork-active',lambda:self.launch_artwork.status(self._game.appid).get('active')),
            ('launch-artwork-pending',lambda:self.launch_artwork.status(self._game.appid).get('pending')))
        sampled=getattr(self,'_broker_steam_inputs_at',None)
        evidence=dict(first_blocker='none',evaluated={},steam_inputs=dict(getattr(self,'_broker_steam_inputs',{})),
            steam_inputs_age_ms=None if sampled is None else max(0,min(2147483647,round((time.monotonic()-sampled)*1000))),
            light_event=event_evidence,
            countdown_source=countdown.get('source') if countdown.get('source') in ('preview','parental','free') else 'none')
        for name,check in checks:
            blocked=bool(check());evidence['evaluated'][name]=blocked
            if blocked:
                evidence['first_blocker']=name
                return False,evidence
        return True,evidence

    def _reconcile_cinema(self, values, reason):
        # Kept as an inert compatibility shim for an old Decky frontend. The
        # Studio relay cannot acquire hardware after the plugin separation.
        return False

    def preview_screen_sync(self, seconds=15.0):
        enabled = self.settings.all()["signalbar_enabled"]
        seconds = max(3.0, min(30.0, float(seconds)))
        capture = self.screen_sync.capture.status()
        self.screen_sync_trace.begin_preview(seconds, enabled=enabled,
            engine_alive=bool(self._thread and self._thread.is_alive()),
            capture_phase=capture['phase'], selector=capture['capture_selector'])
        if not enabled:
            self.screen_sync_trace.record("preview-rejected", reason="master-disabled")
            self.screen_sync_trace.end_preview("master-disabled")
            return False
        self.screen_sync.capture.request_retry()
        return self.screen_sync_activation.preview(seconds)

    def _trace_screen_sync_route(self, reason, active, *, requested, recording,
                                 stripmine_active, steam_priority, signal_critical,
                                 ownership_allowed, assistant_holds_bar):
        values = (reason, active, requested, recording, stripmine_active, steam_priority,
                  signal_critical, ownership_allowed, assistant_holds_bar)
        if values == self._screen_sync_trace_route:
            return
        previous = self._screen_sync_trace_route
        self._screen_sync_trace_route = values
        self.screen_sync_trace.record("capture-routing", reason=reason,
            requested=requested, capture_active=active, recording=recording,
            stripmine_active=stripmine_active, steam_priority=steam_priority,
            signal_critical=signal_critical, ownership_allowed=ownership_allowed,
            assistant_holds_bar=assistant_holds_bar)
        if previous and previous[0] == 'manual-preview' and reason != 'manual-preview':
            self.screen_sync_trace.end_preview("activation-ended")

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
                self.faceplate_steam_state.heartbeat()
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

    def start_free_timer(self, minutes, end_action='none'):
        if type(minutes) is not int or not 1 <= minutes <= 240:
            raise ValueError('Choose 1..240 whole minutes')
        if end_action not in ('none', 'sleep', 'shutdown'):
            raise ValueError('Unsupported timer end action')
        values = self.settings.update({"free_timer_minutes": minutes})
        duration = values["free_timer_minutes"] * 60.0
        self.countdown.stop('free')
        self.countdown.start("free", duration, total_seconds=duration, label="Free timer", end_action=end_action)

    def stop_free_timer(self):
        self.countdown.stop("free")

    def extend_free_timer(self, minutes=15):
        if type(minutes) is not int or not 1 <= minutes <= 240:
            raise ValueError('Choose 1..240 whole minutes')
        if not self.countdown.extend_personal(minutes * 60):
            raise RuntimeError('No personal timer is running')

    def preview_countdown(self):
        self.countdown.start("preview", 15.0, total_seconds=15.0, label="Preview")

    def _service_timer_end_action(self):
        # Runs even with the panel closed, LEDs off or no LED hardware. Reuse
        # existing single-use Steam sleep / logind PowerOff, never a reboot.
        if self._stop.is_set() or self._assistant_system_suspended:
            self.countdown.end_action.cancel('system-unavailable')
            return
        with self._timer_power_lock:
            if self._timer_power_thread and self._timer_power_thread.is_alive():
                return
            request = self.countdown.claim_end_action()
            if request is None:
                return
            generation, action, cancel = request
            def dispatch():
                accepted = False
                try:
                    if self._stop.is_set() or self._assistant_system_suspended:
                        cancel.set()
                    if not cancel.is_set():
                        self.assistant.actions.request(action, 0, cancel)
                        accepted = True
                except Exception as error:
                    self._warn(f'Personal timer {action} not confirmed: {type(error).__name__}')
                finally:
                    self.countdown.end_action.finish(generation, accepted)
            self._timer_power_thread = threading.Thread(target=dispatch, name='personal-timer-power', daemon=True)
            self._timer_power_thread.start()

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

    def preview_display_preset(self, preset, seconds=10.0, *, owner=''):
        if preset not in {"moderate", "atmosphere", "signals", "immersive"}:
            return False
        with self._lock:
            now = time.monotonic()
            self._display_preset_preview = preset
            self._display_preset_preview_started_at = now
            self._display_preset_preview_until = now + max(3.0, min(20.0, float(seconds)))
            self._display_preset_preview_owner = owner
            self._display_preset_preview_colors = []
            self._display_preset_preview_on_bar = False
        return True

    def stop_display_preset_preview(self, owner):
        with self._lock:
            if not owner or owner != self._display_preset_preview_owner:
                return False
            signals = self._display_preset_preview == 'signals'
            self._display_preset_preview_until = 0.0
            self._display_preset_preview_owner = ''
            self._display_preset_preview_colors = []
            self._display_preset_preview_on_bar = False
            if signals:
                self.controllers.stop_preview(owner)
            return True

    def trigger_event(self, kind, preview=False, variant=""):
        values = self.settings.all()
        kind = str(kind or "")
        setting = {
            "notification": "event_notifications_enabled",
            "achievement": "event_achievements_enabled",
            "screenshot": "event_screenshots_enabled",
            "record-start": "event_recording_enabled",
            "record-stop": "event_recording_enabled",
        }.get(kind)
        recording_changed = False
        if not preview and kind=='achievement':
            self.dashboard_stats.invalidate(self._game.appid)
        if not preview and kind in {"record-start", "record-stop"}:
            # Capture safety follows recording even when its optional visual
            # event or persistent marker is disabled.
            self.events.set_recording(kind == "record-start")
            self.screen_sync_trace.record("steam-recording-context", active=kind == "record-start")
            recording_changed = self.faceplate_steam_state.observe_event(kind)
        elif (not preview and values.get("events_enabled") and setting
              and values.get(setting)):
            # Recent notifications are facts, not an unread counter.  They are
            # held for the next normal Dashboard refresh and never force their
            # own flash write.
            self.faceplate_steam_state.observe_event(kind)
        if recording_changed:
            self._queue_faceplate_recording_transition(kind)
        if values["mode"] == "disabled":
            return False
        if self.controllers.event_output().provider == "controller:low":
            return False
        if not preview:
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

    def _queue_faceplate_recording_transition(self, kind):
        """Queue at most one Faceplate refresh per real REC state transition."""
        values = self.settings.all()
        if not values.get("faceplate_lab_enabled"):
            return 0
        with self._lock:
            context = "game" if self._game.running else "home"
        scene = self.faceplate_preferences.read().scene_for(context)
        if scene not in {"dashboard", "artwork-dashboard"}:
            return 0
        self._faceplate_next_reconcile = 0.0
        return self._reconcile_faceplate(
            f"steam-{str(kind)[:32]}", force=True,
        )

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
        adapter = getattr(self, 'jsaux_broker_adapter', None)
        if adapter is not None and adapter.holds_display():
            return False
        if self._assistant_holds_matrix() or bool(getattr(getattr(self, 'assistant', None), 'holds_bar', False)):
            return False
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

    def _handle_faceplate_scene(self, request):
        payload = request.get("payload") or {}
        if isinstance(self.faceplate,FaceplateCoordinator) and self.faceplate._continuous_return:
            self.faceplate._return_event('worker-start',queue_ms=max(0,round((time.monotonic()-request.get('queued_at',time.monotonic()))*1000)))
        if payload.get("kind") == "performance":
            raise ValueError("CPU/GPU is not available on the JSAUX matrix")
        payload["_upload_reason"] = (request.get("metadata") or {}).get("reason", "")
        # Safety stop must still execute when setup/display guards block scenes.
        if payload.get('kind') == 'return-stop':
            return self.faceplate.stop_continuous_return()
        if (getattr(self, '_onboarding_recovery_blocked', False) or getattr(self, '_onboarding_applying', False)) and not (
                payload.get('kind') == 'control' and payload.get('powered') is False):
            return {"attempted": False, "superseded": True, "error": "Setup recovery required"}
        if self._display_panel_off():
            return {"attempted": False, "superseded": True, "error": "Displays are off"}
        if payload.get("kind") == "broker":
            adapter = getattr(self, 'jsaux_broker_adapter', None)
            if adapter is None:
                return {"attempted": False, "superseded": True}
            return adapter.execute(request)
        if payload.get('kind') == 'broker-exit':
            adapter=getattr(self,'jsaux_broker_adapter',None)
            return adapter.execute_exit(request) if adapter is not None else {'superseded':True}
        if payload.get('kind')=='external' and getattr(self.faceplate,'_continuous_return',None) is not None:
            self.faceplate.stop_continuous_return('priority')
        if payload.get("kind") == "external":
            cancelled = request.get("_cancelled")
            session_cancel = payload["session_cancel"]
            manifest = payload["manifest"]
            return self.faceplate.synchronize_scene(
                payload["data"], scene="external", signature=manifest["signature"],
                peak_load=manifest["peak_load"], reason="External presentation",
                cancelled=lambda: session_cancel.is_set() or (cancelled is not None and cancelled.is_set()),
            )
        if self._assistant_holds_matrix() and payload.get("kind") != "control":
            return {"attempted": False, "superseded": True}
        if payload.get("kind") == "control":
            if "brightness" in payload:
                return self.faceplate.set_brightness(
                    payload["brightness"], "Pixel Studio",
                )
            if "powered" in payload:
                return self.faceplate.set_power(
                    bool(payload["powered"]), "Pixel Studio",
                )
            return {"ok": False, "error": "empty Faceplate control"}
        if payload.get('kind') == 'weather-preview':
            if not self._weather_preview_allowed():
                return {'attempted': False, 'superseded': True, 'error': 'Display priority changed'}
            cancelled = request.get('_cancelled')
            result = self.faceplate.synchronize_scene(
                payload['data'], 'weather', payload['signature'],
                peak_load=payload.get('peak_load', POWER_BUDGET),
                reason='weather-preview', cancelled=lambda: bool(cancelled and cancelled.is_set())
                    or not self._weather_preview_allowed(),
            )
            if result.get('synchronized'):
                self.weather.preview(payload['condition'], payload['variant'],
                    started_at=getattr(self.weather, '_clock', time.monotonic)(),
                    frame_step_seconds=.05 if payload['condition'] in ('snow', 'storm') else .1,
                    is_day=payload.get('is_day'))
            return result
        if payload.get("kind") == "cache_weather":
            ticket = FaceplateSceneTicket(
                generation=0, scene="weather", context="cache",
                content_key=str(payload.get("content_key", "")),
                preference_revision=0,
            )
            render_payload = dict(payload)
            render_payload["kind"] = "weather"
            data, manifest = self._render_faceplate_scene(render_payload, ticket)
            self._faceplate_cached_weather_key = ticket.content_key
            return {"cached": True, "size_bytes": len(data),
                    "signature": manifest.get("signature", "")}
        ticket = payload.get("ticket")
        if ticket is None or not self.faceplate_router.mark_preparing(ticket):
            return {"attempted": False, "superseded": True}
        cancelled = request.get("_cancelled")
        kind = str(payload.get("kind", ""))
        visual_theme = str(payload.get("visual_theme", "integrated"))
        source_manifest = {}
        projection_source = None
        refresh = {'key': payload.get('_extension_background_key'), 'generation': ticket.generation}
        self._faceplate_extension_refresh = refresh
        try:
            if kind == "native-clock":
                def native_cancelled():
                    return ((cancelled is not None and cancelled.is_set())
                            or self._stop.is_set()
                            or self._faceplate_suspended or self._display_panel_off()
                            or self.faceplate_router.status()["generation"] != ticket.generation)
                result = self.faceplate.synchronize_native_clock(
                    sync_key=ticket.content_key, reason=payload["_upload_reason"],
                    cancelled=native_cancelled,
                )
                successful = bool(result.get("synchronized")) and not result.get("error")
            elif kind == "cinema":
                return {'attempted': False, 'superseded': True}
            elif kind == "artwork":
                result = self._synchronize_artwork_with_projection(payload, ticket, cancelled)
                projection_source = result.get('projection_source')
                successful = bool(result.get("synchronized")) and not result.get("error")
            elif kind == "artwork-dashboard":
                def dashboard_cancelled():
                    return ((cancelled is not None and cancelled.is_set())
                            or self._stop.is_set() or self._faceplate_suspended
                            or self._display_panel_off()
                            or self.faceplate_router.status()["generation"] != ticket.generation)
                if dashboard_cancelled():
                    return {"attempted": False, "superseded": True, "cancelled_before_serial": True}
                prepared = self._dashboard_background(
                    payload.get("appid", 0), payload.get("source", "hero"),
                    home=bool(payload.get("home_dashboard", False)),
                )
                if dashboard_cancelled():
                    return {"attempted": False, "superseded": True, "cancelled_before_serial": True}
                if prepared is None:
                    if payload.get("home_dashboard"):
                        result = self._synchronize_artwork_with_projection(payload, ticket, cancelled)
                        result["fallback"] = "artwork"
                        projection_source = result.get("projection_source")
                        successful = bool(result.get("synchronized")) and not result.get("error")
                    else:
                        result = {"attempted": False, "found": False,
                                  "error": "No local Steam artwork is available; keeping the last picture"}
                        successful = False
                else:
                    prepared_manifest, background_fields, projection_source = prepared
                    self._publish_faceplate_extension_source(payload, ticket, {}, projection_source, prepared=True)
                    render_payload = {
                        **{key: value for key, value in payload.items() if key != "ticket"},
                        "kind": "artwork-dashboard",
                        **background_fields,
                        "dashboard_pack_frames": prepared_manifest.get(
                            "dashboard_pack_frames", 0,
                        ),
                        "dashboard_pack_sha256": prepared_manifest.get(
                            "dashboard_pack_sha256", "",
                        ),
                        "source_frame_count": prepared_manifest.get("frames", 0),
                        "dashboard_treatment": prepared_manifest.get(
                            "dashboard_treatment", "none",
                        ),
                        "dashboard_compression": prepared_manifest.get(
                            "dashboard_compression", "compatible",
                        ),
                        "dashboard_show_clock": bool(
                            payload.get("home_dashboard", False)
                            and payload.get("dashboard_show_clock", False)
                        ),
                        "dashboard_clock_size": prepared_manifest.get(
                            "dashboard_clock_size", "large",
                        ),
                        "dashboard_show_status_rail": bool(payload.get(
                            "dashboard_show_status_rail", True,
                        )),
                        "dashboard_show_session": (
                            prepared_manifest.get("dashboard_show_session", True)
                            and not payload.get("home_dashboard", False)
                        ),
                        "dashboard_show_battery": prepared_manifest.get(
                            "dashboard_show_battery", True,
                        ),
                    }
                    data, rendered_manifest = self._render_faceplate_scene(
                        render_payload, ticket,
                    )
                    source_manifest = rendered_manifest
                    if dashboard_cancelled():
                        return {"attempted": False, "superseded": True,
                                "cancelled_before_serial": True}
                    result = self._synchronize_faceplate_handoff(data, kind, rendered_manifest, ticket, request)
                    result.update({
                        "frames": rendered_manifest.get("frames", 0),
                        "refresh_policy": payload.get("refresh_policy", "economy"),
                        "automatic_background": bool(prepared_manifest.get("automatic_background")),
                    })
                    successful = bool(result.get("synchronized")) and not result.get("error")
            else:
                if (not payload.get('weather_unavailable') and payload.get('_extension_background_key') and kind in ('weather', 'dashboard')
                        and visual_theme in WEATHER_ARTWORK_THEMES):
                    from signalbar.faceplate.weather_artwork import select_weather_artwork
                    selection = select_weather_artwork(payload['condition'], int(payload['variant']),
                        payload['phase'], visual_theme=visual_theme)
                    if selection.preset_id:
                        self._publish_faceplate_extension_source(payload, ticket,
                            {'preset_id': selection.preset_id}, prepared=True)
                # Multi-frame Weather and Weather-backed Dashboard scenes stay
                # in the isolated renderer. Performance and the legacy static
                # Dashboard builders remain cheap enough to render here.
                if payload.get("weather_unavailable"):
                    from signalbar.faceplate.scenes import build_weather_unavailable
                    rendered = build_weather_unavailable(payload)
                    data = rendered.gif()
                    manifest = {"kind": kind, "signature": rendered.signature,
                                "size_bytes": len(data), "fallback": "weather-unavailable"}
                elif kind == "dashboard" and visual_theme in WEATHER_ARTWORK_THEMES:
                    data, manifest = self._render_faceplate_scene(payload, ticket)
                elif kind == "dashboard":
                    arguments = (
                        payload["display_at"], payload["condition"],
                        int(payload["variant"]), payload["temperature_c"],
                        payload["unit"], payload["sunrise"], payload["sunset"],
                    )
                    keywords = {
                        "city": payload.get("city", ""),
                        "precipitation_probability": payload.get("precipitation_probability"),
                        "clock_24h": bool(payload.get("clock_24h", True)),
                        "status": payload.get("status"),
                        "battery": payload.get("battery"),
                    }
                    if visual_theme == "integrated":
                        rendered = build_dashboard_snapshot(*arguments, **keywords)
                    elif visual_theme == V3_THEME:
                        rendered = build_v3_dashboard_snapshot(
                            visual_theme, *arguments, **keywords,
                        )
                    else:
                        rendered = build_v2_dashboard_snapshot(
                            visual_theme, *arguments, **keywords,
                        )
                    data = rendered.gif()
                    manifest = {
                        "kind": kind, "signature": rendered.signature,
                        "size_bytes": len(data),
                    }
                else:
                    data, manifest = self._render_faceplate_scene(payload, ticket)
                if cancelled is not None and cancelled.is_set():
                    return {"attempted": False, "superseded": True,
                            "cancelled_before_serial": True}
                if not self.faceplate_router.mark_preparing(ticket):
                    return {"attempted": False, "superseded": True}
                if kind == 'player-city':
                    if self._game.appid != payload['appid'] or not self.faceplate_router.mark_preparing(ticket):
                        return {'attempted': False, 'superseded': True}
                    self.player_city.reserve(payload)
                try:
                    result = self._synchronize_faceplate_handoff(data, kind, manifest, ticket, request)
                except Exception as error:
                    if kind == 'player-city':
                        self.player_city.receipt(payload, {'error': str(error)})
                    raise
                if kind == 'player-city':
                    self.player_city.receipt(payload, result)
                source_manifest = manifest
                successful = bool(result.get("synchronized")) and not result.get("error")
            if (cancelled is not None and cancelled.is_set()) or self._stop.is_set() or self._faceplate_suspended or self.faceplate_router.status()['generation'] != ticket.generation:
                return {**result, 'synchronized': False, 'superseded': True}
            if result.get("superseded"):
                self._write_faceplate_runtime_status()
                return result
            if result.get("deferred"):
                self.faceplate_router.fail(ticket, "Flash protection: latest route pending")
                self._faceplate_scene_retry_at = time.monotonic() + max(1.0, result.get("retry_after", 30))
            elif result.get('sent_unconfirmed'):
                self.faceplate_router.sent_unconfirmed(ticket, result.get('error'))
                # One bounded current-route recovery may follow this receipt.
                # Never retry GIF_END alone or relight an unconfirmed image.
                self._faceplate_scene_retry_at = time.monotonic() + 30.0
            elif successful:
                completion_id = (request.get("metadata") or {}).get("timer_completion_id")
                with self._lock:
                    ending = self._faceplate_timer_end
                    if completion_id and ending and ending["id"] == completion_id and ending["ack_at"] is None:
                        ending["ack_at"] = time.monotonic()
                committed = self.faceplate_router.commit(ticket)
                if payload.get('_extension_background_key'):
                    # A newer minute/rail ticket may supersede this GIF without
                    # superseding its original background. Accept that current
                    # background independently of the full-scene clock receipt.
                    self._publish_faceplate_extension_source(payload, ticket, source_manifest, projection_source)
                elif committed:
                    self._remember_faceplate_extension_source(payload, ticket, source_manifest, projection_source)
                self._faceplate_scene_retry_at = 0.0
            else:
                self.faceplate_router.fail(
                    ticket, result.get("error") or f"{kind} scene is unavailable",
                )
                self._faceplate_scene_retry_at = time.monotonic() + 60.0
            adapter = getattr(self, 'jsaux_broker_adapter', None)
            if adapter is not None:
                adapter.normal_completed(result)
            self._write_faceplate_runtime_status()
            return result
        except (FaceplateRenderError, OSError, TypeError, ValueError) as error:
            transition=getattr(self.faceplate,'_continuous_return',None)
            if isinstance(transition,dict):transition['stop']=True
            self.faceplate_router.fail(ticket, error)
            self._faceplate_scene_retry_at = time.monotonic() + 60.0
            self._write_faceplate_runtime_status()
            raise
        finally:
            # A controlled same-background upload may temporarily replace the
            # GIF signature or lack a final ACK. It is not a new RGB background.
            delivery = getattr(self.faceplate, 'delivery', {}) or {}
            if refresh['key'] and delivery.get('scene') in ('weather', 'dashboard', 'artwork', 'artwork-dashboard', 'player-city'):
                self._faceplate_extension_delivery_basis = {**refresh,
                    'signature': delivery.get('signature'), 'scene': delivery.get('scene')}
            if self._faceplate_extension_refresh is refresh:
                self._faceplate_extension_refresh = None

    def _synchronize_artwork_with_projection(self, payload, ticket, cancelled=None):
        keywords = {}
        if payload.get("home_artwork"):
            keywords["home"] = True
        if isinstance(self.faceplate, FaceplateCoordinator):
            keywords["reason"] = payload.get("_upload_reason") or "artwork"
            # Serial callbacks may only read events/route state, never acquire
            # the engine or settings locks.
            keywords['cancelled'] = lambda: bool(cancelled and cancelled.is_set()) or self._stop.is_set() or self._faceplate_suspended or self._display_faceplate_off or self.faceplate_router.status()['generation'] != ticket.generation
        if getattr(self.faceplate, 'supports_source_projection_callback', False) is True:
            def source_ready(original):
                self.faceplate_router.mark_prepared(ticket)
                return self._publish_faceplate_extension_source(payload, ticket, {}, original, prepared=True)
            keywords['source_ready'] = source_ready
        return self.faceplate.synchronize_artwork(payload.get('appid', 0),
            str(payload.get('source', 'hero')), **keywords)

    def _dashboard_background(self, appid, source="hero", *, home=False, mode="", draft=False):
        """Resolve only in a worker/explicit preview, never the game callback."""
        library = getattr(self.faceplate, "steamgriddb", None)
        prepared = None
        if library is not None:
            if draft:
                prepared = library.selected_dashboard_pack_reference(appid, mode, draft=True)
            elif home and hasattr(library, "home_dashboard_pack_reference"):
                prepared = library.home_dashboard_pack_reference(appid)
            else:
                prepared = library.selected_dashboard_pack_reference(appid)
        if prepared is not None:
            manifest, path = prepared
            return manifest, {"dashboard_pack_path": str(path)}, {
                "kind": "artwork", "path": str(path), "root": str(library.artwork_root),
                "frames": manifest.get("dashboard_pack_frames", 0),
                "sha256": manifest.get("dashboard_pack_sha256", ""),
            }
        if home or draft:
            return None
        values = self.settings.all()
        profile = values.get("faceplate_artwork_profiles", {}).get(str(appid), {})
        local = self._automatic_dashboard_backgrounds.get(
            appid, source, profile.get("style", values.get("faceplate_artwork_style", "logo_dim")),
            profile.get("position", values.get("faceplate_logo_position", "bottom")),
        )
        if local is None:
            return None
        rgb, _path, actual_source = local
        digest = hashlib.sha256(rgb).hexdigest()
        from signalbar.faceplate.source_projection import project_backgrounds
        projection = {"kind": "artwork-strip", "sha256": digest,
                      "colours": {mapping + ("-rotated" if rotated else ""):
                          project_backgrounds((rgb,), mapping, rotated)
                          for mapping in ("bottom", "whole") for rotated in (False, True)}}
        return {
            "dashboard_pack_frames": 1, "dashboard_pack_sha256": digest, "frames": 1,
            "automatic_background": True, "local_source": actual_source,
        }, {"dashboard_background_rgb": rgb.hex()}, projection

    def _publish_faceplate_extension_source(self, payload, ticket, manifest, projection_source=None, *, prepared=False):
        """Only publish the current route's original, not its minute/GIF ACK.

        Prepared references are verified by the isolated colour reducer before
        output. Publishing one does not commit the scene or assert USB success.
        """
        target = getattr(self, '_faceplate_extension_target', None)
        key = payload.get('_extension_background_key')
        if not key or not target or key != target['key'] or ticket.context != target['context']:
            return False
        if ticket.context == 'game' and payload.get('kind') in ('artwork', 'artwork-dashboard', 'player-city') \
                and payload.get('appid') != target['appid']:
            return False
        self._remember_faceplate_extension_source(payload, ticket, manifest, projection_source, prepared=prepared)
        return True

    def _remember_faceplate_extension_source(self, payload, ticket, manifest, projection_source=None, *, prepared=False):
        """Capture a validated source reference, never composed screen pixels."""
        source = None
        kind = payload.get('kind')
        if kind in ('artwork', 'artwork-dashboard') and isinstance(projection_source, dict):
            source = dict(projection_source)
        elif kind in ('weather', 'dashboard') and manifest.get('preset_id'):
            from signalbar.faceplate.weather_artwork import _preset
            theme = payload.get('visual_theme')
            if theme in WEATHER_ARTWORK_THEMES:
                try:
                    metadata = _preset(manifest['preset_id'], theme, payload.get('phase'))
                    source = {'kind': 'weather', 'theme': theme, 'preset_id': manifest['preset_id'],
                              'phase': payload.get('phase'),
                              'sha256': metadata['background_raw_sha256'],
                              'revision': metadata['background_pack_sha256']}
                except (OSError, ValueError, KeyError):
                    # Optional strip failure must never invalidate the ACK or
                    # cause a repeat upload of the already confirmed matrix.
                    source = None
        elif kind == 'player-city':
            from signalbar.faceplate.player_city import population_tier
            from signalbar.faceplate.player_city_animation import projection_source as city_source
            try:
                source = city_source(payload['weather'], payload['phase'], population_tier(payload['players']))
            except (OSError, ValueError, KeyError):
                source = None
        if source:
            source.update(asset=None if prepared else getattr(self.faceplate, 'last_asset', ''), context=ticket.context,
                          appid=int(payload.get('appid', 0)),
                          background_key=payload.get('_extension_background_key'),
                          background_generation=getattr(ticket, 'generation', 0),
                          prepared=bool(prepared),
                          route_appid=(getattr(self, '_faceplate_extension_target', None) or {}).get('appid', payload.get('appid', 0)),
                          delivery_signature=(getattr(self.faceplate, 'delivery', {}) or {}).get('signature'))
        self._faceplate_extension_source = source
        self._faceplate_extension_device = getattr(self.faceplate, 'device_token', None)

    def _faceplate_extension_output(self, values, game, current_display, now, screensaver=False):
        available = bool(values['faceplate_lab_enabled'] and not self._faceplate_suspended
            and self._faceplate_extension_present and self.faceplate.powered is not False)
        if not available:
            # Clear delegated and normal projections together. The arbiter uses
            # current-game Artwork without changing the saved route or brightness.
            self._faceplate_extension_recovering = True
            self.faceplate_extension.configure(False, None)
            return None
        if screensaver:
            adapter=getattr(self,'jsaux_broker_adapter',None)
            frame=adapter.extension_frame(now,values.get('faceplate_extension_mapping','bottom')) if adapter is not None else None
            # A requested screensaver never borrows Home's weather palette.
            # Only the confirmed delegated content supplies colours; missing
            # projection data is black until that exact content becomes ready.
            frame=((0,0,0),)*17 if frame is None else saturate_colours(frame,values.get('faceplate_extension_saturation',100))
            return ProviderOutput('faceplate-extension:screensaver',normalize_frame(frame),
                'Prepared GIF projection follows routing; optical alignment unmeasured')
        source = self._faceplate_extension_source
        delivery = getattr(self.faceplate, 'delivery', {}) or {}
        target = getattr(self, '_faceplate_extension_target', None)
        exact = bool(source and getattr(self.faceplate, 'last_synchronized', False)
            and source['asset'] == self.faceplate.last_asset
            and source.get('delivery_signature') == delivery.get('signature'))
        pending = False
        if source and target is not None:
            current_target = bool(target['key'] and target['context'] == ('game' if game.running else 'home')
                and target['appid'] == game.appid and source.get('background_key')
                and source.get('background_generation', 0) <= target['generation'])
            refresh = getattr(self, '_faceplate_extension_refresh', None)
            basis = getattr(self, '_faceplate_extension_delivery_basis', None)
            known_transfer = bool(delivery.get('scene') in ('weather', 'dashboard', 'artwork', 'artwork-dashboard', 'player-city')
                and ((refresh and refresh['key'] in (source.get('background_key'), target['key']))
                     or (basis and basis['signature'] == delivery.get('signature')
                         and basis['scene'] == delivery.get('scene')
                         and basis['key'] in (source.get('background_key'), target['key']))))
            requested_original = bool(current_target and source.get('prepared')
                and source['background_key'] == target['key'] and source['context'] == target['context']
                and source.get('route_appid') == target['appid'])
            content_allowed = current_target and (requested_original or exact or known_transfer)
            pending = bool(content_allowed and not requested_original
                and (source['background_key'] != target['key'] or not exact))
        else:
            # Conservative compatibility/startup path until an upstream route
            # has supplied its background identity. Unknown transfers stay black.
            content_allowed = bool(exact and source and source['context'] == ('game' if game.running else 'home')
                and (not game.running or source['appid'] in (0, game.appid)))
        eligible = bool(source and values['faceplate_lab_enabled'] and not self._faceplate_suspended
            and self._faceplate_extension_present and self.faceplate.powered is not False
            and (source.get('prepared') or self._faceplate_extension_device == getattr(self.faceplate, 'device_token', None))
            and content_allowed)
        self.faceplate_extension.configure(current_display == 'faceplate_extension' and values['signalbar_enabled'],
            source if eligible else None, values['faceplate_extension_mapping'], values['faceplate_rotate_180'],
            saturation=values.get('faceplate_extension_saturation', 100), pending=pending and eligible)
        output = self.faceplate_extension.output(now)
        if getattr(self, '_faceplate_extension_recovering', False):
            if output is None or output.provider == 'faceplate-extension:waiting':
                return None
            self._faceplate_extension_recovering = False
        return output

    def _faceplate_extension_status(self):
        state = self.faceplate_extension.status()
        source = getattr(self, '_faceplate_extension_source', None) or {}
        target = getattr(self, '_faceplate_extension_target', None) or {}
        delivery = getattr(self.faceplate, 'delivery', {}) or {}
        state.update(context=source.get('context', ''), appid=source.get('route_appid', source.get('appid', 0)),
            faceplate_confirmed=bool(source and not source.get('prepared')
                and getattr(self.faceplate, 'last_synchronized', False) and source.get('asset') == getattr(self.faceplate, 'last_asset', '')
                and source.get('delivery_signature') == delivery.get('signature')
                and source.get('background_key') == target.get('key')))
        return state

    def _synchronize_faceplate_handoff(self, data, kind, manifest, ticket, request):
        """Restore the current full animation once, without an extra flash write."""
        cancelled = request.get('_cancelled')
        check = cancelled.is_set if cancelled is not None else None
        if kind == 'player-city':
            payload_appid = request['payload']['appid']
            check = lambda: bool(cancelled and cancelled.is_set()) or self._stop.is_set() or self._faceplate_suspended or self._display_faceplate_off or self._game.appid != payload_appid or self.faceplate_router.status()['generation'] != ticket.generation
        if not self.faceplate_router.mark_prepared(ticket):
            return {'attempted': False, 'superseded': True}
        reason = str((request.get('metadata') or {}).get('reason', kind))
        fast = reason == 'external-finished-current-route'
        if fast:
            if (check and check()) or not self.faceplate_router.mark_preparing(ticket):
                return {'attempted': False, 'superseded': True}
        started = request.get('queued_at', time.monotonic())
        result = self.faceplate.synchronize_scene(data, kind,
            manifest.get('signature', ticket.content_key),
            peak_load=manifest.get('peak_load', POWER_BUDGET),
            reason='player-city-confirmed-restore' if kind == 'player-city' and (request.get('metadata') or {}).get('player_city_restore') else reason,
            cancelled=check)
        if fast and getattr(self, 'assistant', None) is not None:
            origin=(request.get('metadata') or {}).get('external_origin',{})
            self.assistant._event('face_restore_confirmed',
                success=bool(result.get('synchronized')) and not result.get('error'),
                bytes=len(data), duration_ms=round((time.monotonic()-started)*1000), kind=kind,
                generation=request.get('generation',0),**origin)
        return result

    def _render_faceplate_scene(self, payload, ticket):
        """Read-through bounded cache around the isolated scene renderer."""
        render_started=time.monotonic()
        def record_render(cache_hit):
            panel=getattr(self,'faceplate',None)
            if isinstance(panel,FaceplateCoordinator) and panel._continuous_return:
                panel._return_event('render-ready',cache_hit=cache_hit,render_ms=round((time.monotonic()-render_started)*1000))
        cache_namespace = faceplate_scene_cache_namespace(payload)
        cache_key = hashlib.sha256(
            f"{cache_namespace}:{ticket.scene}:{ticket.content_key}".encode("utf-8"),
        ).hexdigest()
        root = self._faceplate_scene_cache
        gif_path = os.path.join(root, cache_key + ".gif")
        manifest_path = os.path.join(root, cache_key + ".json")
        try:
            if os.path.getsize(gif_path) <= 2 * 1024 * 1024:
                with open(manifest_path, encoding="utf-8") as stream:
                    manifest = json.load(stream)
                with open(gif_path, "rb") as stream:
                    data = stream.read(2 * 1024 * 1024 + 1)
                validate_gif(data)
                if not isinstance(manifest, dict):
                    raise ValueError("invalid scene cache manifest")
                legacy_profile = manifest.get("power_profile")
                cached_sha = manifest.get("gif_sha256") or (
                    legacy_profile.get("sha256") if isinstance(legacy_profile, dict) else ""
                )
                if (manifest.get("content_key") == ticket.content_key
                        and manifest.get("cache_namespace") == cache_namespace
                        and manifest.get("signature")
                        and cached_sha == hashlib.sha256(data).hexdigest()):
                    os.utime(gif_path, None)
                    record_render(True)
                    return data, manifest
        except (OSError, ValueError, TypeError):
            pass
        data, rendered = render_isolated(
            {key: value for key, value in payload.items() if key != "ticket"},
            temporary_root=self._faceplate_state_directory,
        )
        validate_gif(data)
        record_render(False)
        manifest = {
            **rendered, "gif_sha256": hashlib.sha256(data).hexdigest(),
            "content_key": ticket.content_key,
            "cache_namespace": cache_namespace,
            "cached_at": time.time(),
        }
        try:
            os.makedirs(root, exist_ok=True)
            temporary_gif = gif_path + ".tmp"
            temporary_manifest = manifest_path + ".tmp"
            with open(temporary_gif, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            with open(temporary_manifest, "w", encoding="utf-8") as stream:
                json.dump(manifest, stream, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_gif, gif_path)
            os.replace(temporary_manifest, manifest_path)
            entries = sorted(
                (os.stat(os.path.join(root, name)).st_mtime, name)
                for name in os.listdir(root) if name.endswith(".gif")
            )
            for _, name in entries[:-48]:
                stem = name[:-4]
                for suffix in (".gif", ".json"):
                    try:
                        os.unlink(os.path.join(root, stem + suffix))
                    except OSError:
                        pass
        except OSError as error:
            self._warn("could not cache Faceplate scene: " + str(error)[:120])
        return data, manifest

    @staticmethod
    def _faceplate_city(weather_status):
        location = weather_status.get("location")
        return str(location.get("name", ""))[:80] if isinstance(location, dict) else ""

    def _faceplate_weather_payload(self, values, game_running):
        status = self.weather.status(values, game_running)
        weather_state = str(status.get("faceplate_weather_state", "unavailable"))
        self._faceplate_weather_summary = {
            "location": self._faceplate_city(status),
            "phase": status.get("phase", "off"),
            "condition": status.get("condition") or "",
            "age_s": status.get("age_s"),
            "error": status.get("error", ""),
            "fallback": weather_state,
        }
        condition = status.get("condition")
        temperature = status.get("temperature_c")
        if temperature is None and status.get("faceplate_fallback_available"):
            temperature = status.get("cached_temperature_c")
        if temperature is None and status.get("faceplate_background_only"):
            temperature = status.get("cached_temperature_c")
        try:
            sunrise = datetime.fromisoformat(str(status.get("sunrise_at", "")))
            sunset = datetime.fromisoformat(str(status.get("sunset_at", "")))
            if sunrise.tzinfo:
                now = datetime.now(tz=sunrise.tzinfo)
            else:
                now = datetime.utcfromtimestamp(
                    time.time() + int(status.get("utc_offset_seconds", 0) or 0),
                )
            # A persisted sample may outlive the calendar day on which it was
            # fetched. Reuse only its local sunrise/sunset wall times so the
            # last known visual stays coherent instead of being forced into an
            # impossible multi-day solar interval.
            if status.get("faceplate_background_only"):
                sunrise = now.replace(
                    hour=sunrise.hour, minute=sunrise.minute,
                    second=0, microsecond=0,
                )
                sunset = now.replace(
                    hour=sunset.hour, minute=sunset.minute,
                    second=0, microsecond=0,
                )
            phase = solar_phase(now, sunrise, sunset)
            if condition in ("rain", "snow", "storm"):
                # These scenes have two phases. Use the same fresh daylight
                # observation as the LED provider, rather than the ±45 min
                # dawn/dusk artwork window. Old background-only data uses
                # today's local solar interval instead of its stale flag.
                daylight = status.get("is_day")
                if not isinstance(daylight, bool) or status.get("faceplate_background_only"):
                    daylight = sunrise <= now < sunset
                phase = "day" if daylight else "night"
            variant = int(values[weather_variant_key(condition, phase in ("dawn", "day"))])
            if temperature is None:
                raise ValueError("weather temperature is unavailable")
            signature = visual_signature(
                condition, variant, temperature, values["weather_temperature_unit"],
                phase, self._faceplate_city(status),
            ) + ":" + weather_state
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            return None, status, str(error)
        return {
            "condition": condition, "variant": variant,
            "temperature_c": temperature,
            "unit": values["weather_temperature_unit"], "phase": phase,
            "city": self._faceplate_city(status), "now": now.isoformat(),
            "sunrise": sunrise.isoformat(), "sunset": sunset.isoformat(),
            "precipitation_probability": status.get("precipitation_probability"),
            "weather_code": status.get("weather_code"),
            "wind_speed_kmh": status.get("wind_speed_kmh"),
            "fallback_state": weather_state,
            "signature": signature,
        }, status, ""

    def _faceplate_playtime_facts(self, values, game_running):
        """Reuse Playtime deadlines; only minute/state changes enter GIF identity."""
        if not values.get("faceplate_playtime_enabled", True):
            with self._lock:
                self._faceplate_timer_end = None
            return {}
        snapshot = self.countdown.faceplate_snapshot(
            allow_parental=bool(values["parental_countdown_enabled"] and game_running),
        )
        now = time.monotonic()
        with self._lock:
            if snapshot.get("active"):
                self._faceplate_timer_end = None
                return timer_facts(snapshot["remaining_seconds"])
            completion_id = snapshot.get("completion_id")
            if not completion_id or completion_id == self._faceplate_timer_finished_id:
                self._faceplate_timer_end = None
                return {}
            ending = self._faceplate_timer_end
            if not ending or ending["id"] != completion_id:
                ending = {"id": completion_id, "queued_at": now, "ack_at": None}
                self._faceplate_timer_end = ending
            acknowledged = ending["ack_at"]
            if (acknowledged is not None and now - acknowledged >= 8) or now - ending["queued_at"] >= 60:
                self._faceplate_timer_finished_id = completion_id
                self._faceplate_timer_end = None
                return {}
            return {"state": "ended"}

    def _faceplate_player_city_facts(self, values):
        """Only visible, quantised rail data may refresh the City GIF."""
        countdown = self._faceplate_playtime_facts(values, True)
        mode = values.get('faceplate_player_city_row', 'count')
        if countdown:
            return {'mode':'dashboard', 'countdown': countdown} if mode == 'dashboard' else {'countdown': countdown}
        facts = {'mode': mode}
        if mode == 'dashboard':
            choice = values.get('faceplate_player_city_dashboard_row', 'controllers')
            native = choice in ('controllers', 'next_hour', 'today')
            context = dict(show_bottom_row=True, show_weather=False, show_session=False,
                bottom_mode=choice if native else 'controllers', game_row='existing' if native else choice,
                battery_style=values.get('faceplate_player_city_battery_style', 'percent'))
            city_values = dict(values, faceplate_dashboard_contexts={'game':context}, faceplate_dashboard_game_session=False)
            dashboard = self._faceplate_artwork_dashboard_facts(city_values, True, city_row=True, countdown_override={})
            keys = ['bottom_mode', 'game_running', 'game_row']
            if choice in ('controllers', 'a', 'c', 'e'):
                keys.extend(('controllers','battery_style','show_p2','connected_controller_count','ux_enabled'))
            if choice in ('a','c'):
                keys.append('session_minutes')
            if choice in ('a','b','d','e'):
                keys.append('game_stats')
            if choice in ('next_hour','today'):
                keys.extend(('forecast','unit','ux_enabled'))
            facts['dashboard'] = {key:dashboard[key] for key in keys if key in dashboard}
        elif mode == 'controllers':
            connected = self.controllers.faceplate_batteries(1)
            battery = quantize_battery(connected[0].get('percent'), connected[0].get('charging'),
                step=5 if values.get('faceplate_flash_protection_enabled', True) else 1) if connected else None
            facts['percent'] = battery.get('percent') if battery else None
            facts['battery_style'] = values.get('faceplate_player_city_battery_style', 'percent')
        elif mode == 'session':
            started = self._faceplate_game_started_monotonic
            facts['session_minutes'] = (max(0, int((time.monotonic()-started)//300)*5)
                if self._session_start_known and started is not None else None)
        elif mode in ('achievements', 'total'):
            stats = self.dashboard_stats.snapshot(self._game.appid)
            if mode == 'achievements':
                facts.update({key:stats[key] for key in ('achieved','achievements_total') if key in stats})
            elif 'total_minutes' in stats:
                facts['total_minutes'] = stats['total_minutes']//60*60
        return facts

    def _faceplate_artwork_dashboard_facts(self, values, game_running, *, city_row=False, countdown_override=None):
        """Snapshot the tiny, bounded data contract used by Dashboard V2."""
        weather, weather_status, _error = self._faceplate_weather_payload(
            values, game_running,
        )
        weather = weather or {}
        from signalbar.dashboard_settings import dashboard_context
        content = dashboard_context(values, game_running)
        bottom_mode = content['bottom_mode']
        show_game_session = False  # Session has its own explicit row choice.
        background_only = bool(weather_status.get("faceplate_background_only"))
        if background_only and not city_row:
            bottom_mode = "controllers"
        facts = {
            "dashboard_show_clock": bool(
                not game_running and values.get("faceplate_dashboard_show_clock", False)
            ),
            "countdown": self._faceplate_playtime_facts(values, game_running) if countdown_override is None else countdown_override,
            "ux_enabled": bool(values.get("lab58_ux_enabled")),
            "weather": {
                "condition": weather.get("condition"),
                "temperature_c": weather.get("temperature_c"),
            },
            "dashboard_show_status_rail": content['show_bottom_row'],
            "bottom_mode": bottom_mode,
            "unit": values.get("weather_temperature_unit", "celsius"),
            "show_weather_notch": bool(
                not background_only
                and content['show_weather']
            ),
            "clock_24h": values.get("faceplate_dashboard_clock_format", "24h") == "24h",
            "clock_position": values.get("faceplate_dashboard_clock_position", "left"),
            "game_running": bool(game_running),
            "show_game_session": show_game_session,
            "session_minutes": 0,
            "weather_fallback_state": weather_status.get(
                "faceplate_weather_state", "unavailable",
            ),
        }
        facts['weather_position'] = content.get('weather_position', 'right') if facts['show_weather_notch'] and not facts['dashboard_show_clock'] else 'right'
        if not facts['show_weather_notch']:
            facts['weather'] = {}
        if facts["countdown"]:
            # Hidden battery/session/forecast changes must not produce timer
            # GIF writes. The saved normal row is read again on restoration.
            facts.update({"bottom_mode": "countdown", "show_game_session": False})
            return facts
        if not facts["dashboard_show_status_rail"]:
            # Hidden normal data must not trigger new GIFs. Timers above retain priority.
            facts.update({"bottom_mode": "hidden", "show_game_session": False})
            return facts
        variant = content.get('game_row', 'existing') if game_running else 'existing'
        if variant in ('a', 'b', 'c', 'd', 'e'):
            facts.update(game_row=variant, bottom_mode='controllers', show_game_session=False)
            if variant in ('a', 'c', 'e'):
                connected = self.controllers.faceplate_batteries(1)
                facts.update(controllers=[quantize_battery(item.get('percent'), item.get('charging'),
                    step=5 if values.get('faceplate_flash_protection_enabled', True) else 1)
                    or {'percent': None, 'charging': item.get('charging') is True}
                    for item in connected[:1]],
                    connected_controller_count=min(1,len(connected)), battery_style=content['battery_style'],
                    show_p2=False, session_minutes=None)
                if variant == 'a' and content['battery_style'] == 'percent':
                    for battery in facts['controllers']:
                        if battery.get('percent') is not None:
                            battery['percent'] = min(99,battery['percent'])
                started = self._faceplate_game_started_monotonic
                if variant in ('a', 'c') and self._session_start_known and started is not None:
                    facts['session_minutes'] = max(0, int((time.monotonic()-started)//300)*5)
            if variant in ('a', 'b', 'd', 'e'):
                stats = self.dashboard_stats.snapshot(self._game.appid)
                facts['game_stats'] = {key: stats[key] for key in ('achieved', 'achievements_total') if key in stats}
                if variant in ('b', 'e') and 'total_minutes' in stats:
                    facts['game_stats']['total_minutes'] = stats['total_minutes']//60*60
            return facts
        if bottom_mode == "controllers":
            controllers = []
            connected = self.controllers.faceplate_batteries(2)
            for item in connected[:2]:
                battery = quantize_battery(
                    item.get("percent"), item.get("charging", False),
                    step=5 if values.get("faceplate_flash_protection_enabled", True) else 1,
                )
                controllers.append(battery or {
                    "level": None, "charging": item.get("charging") is True,
                    "percent": None,
                })
            facts.update({
                "controllers": controllers,
                "connected_controller_count": len(connected),
                "battery_style": content['battery_style'],
                "show_p2": True,
            })
        elif bottom_mode == "next_hour":
            facts["forecast"] = {
                key: weather_status.get(key) for key in (
                    "next_hour_temperature_c", "next_hour_condition",
                    "next_hour_precipitation_probability",
                )
            }
        elif bottom_mode == "today":
            facts["forecast"] = {
                key: weather_status.get(key) for key in (
                    "morning_temperature_c", "afternoon_temperature_c",
                    "today_condition",
                )
            }
        return facts

    def faceplate_weather_preview(self, condition, variant, visual_theme=None):
        """Return the exact cached 64x54 GIF used by the hardware Weather route."""
        values = self.settings.all()
        visual_theme = str(
            visual_theme or self.faceplate_preferences.read().theme_for("weather")
        )
        if visual_theme not in WEATHER_ARTWORK_THEMES:
            raise ValueError("unknown Faceplate Weather collection")
        with self._lock:
            game_running = self._game.running
        weather, status, _error = self._faceplate_weather_payload(
            values, game_running,
        )
        if weather is None:
            weather = {
                "temperature_c": 18.0,
                "unit": values["weather_temperature_unit"],
                "phase": "day", "city": "Preview",
            }
        condition, forced_daylight = weather_preview_condition(condition)
        if forced_daylight is not None:
            weather = {**weather, "phase": "day" if forced_daylight else "night"}
        variant = int(variant)
        signature = visual_signature(
            condition, variant, weather["temperature_c"], weather["unit"],
            weather["phase"], weather.get("city", ""),
        )
        artwork_revision = weather_artwork_cache_revision(visual_theme, "weather", condition)
        countdown = self._faceplate_playtime_facts(values, game_running)
        content_key = (
            f"weather-preview:{visual_theme}:{artwork_revision}:" + signature
            + ":timer:" + json.dumps(countdown, sort_keys=True)
        )
        ticket = FaceplateSceneTicket(
            generation=0, scene="weather", context="preview",
            content_key=content_key, preference_revision=0,
        )
        data, manifest = self._render_faceplate_scene({
            "kind": "weather", "condition": condition, "variant": variant,
            "temperature_c": weather["temperature_c"], "unit": weather["unit"],
            "phase": weather["phase"], "city": weather.get("city", ""),
            "weather_code": weather.get("weather_code"),
            "wind_speed_kmh": weather.get("wind_speed_kmh"),
            "visual_theme": visual_theme,
            "countdown": countdown,
        }, ticket)
        return {
            "gif": data, "condition": condition, "variant": variant,
            "temperature_c": weather["temperature_c"], "unit": weather["unit"],
            "phase": weather["phase"], "size_bytes": len(data),
            "signature": manifest.get("signature", signature),
            "visual_theme": visual_theme,
            "live_weather": bool(status.get("condition")),
            "preset_id": manifest.get("preset_id", ""),
            "variant_name": manifest.get("variant_name", ""),
            "source_scene": manifest.get("source_scene", ""),
            "selection_status": manifest.get("selection_status", ""),
            "collection_revision": manifest.get("collection_revision", ""),
            "peak_load": manifest.get("peak_load", POWER_BUDGET),
            "fallback_reason": manifest.get(
                "fallback_reason", manifest.get("selection_reason", ""),
            ),
        }

    def faceplate_dashboard_preview(self, condition, variant, visual_theme=None):
        """Render the exact Home Dashboard style selected in Pixel Studio."""
        values = self.settings.all()
        visual_theme = str(
            visual_theme or self.faceplate_preferences.read().theme_for("dashboard")
        )
        if visual_theme not in WEATHER_ARTWORK_THEMES:
            raise ValueError("unknown Faceplate Dashboard collection")
        with self._lock:
            game_running = self._game.running
        weather, status, _error = self._faceplate_weather_payload(values, game_running)
        if weather is None:
            now = datetime.now().astimezone().replace(second=0, microsecond=0)
            sunrise = now.replace(hour=7, minute=30)
            sunset = now.replace(hour=19, minute=15)
            weather = {
                "temperature_c": 18.0,
                "unit": values["weather_temperature_unit"],
                "city": "Preview", "now": now.isoformat(),
                "sunrise": sunrise.isoformat(), "sunset": sunset.isoformat(),
                "precipitation_probability": None,
            }
        condition, forced_daylight = weather_preview_condition(condition)
        variant = int(variant)
        display_at, _lead = self._faceplate_dashboard_target(
            datetime.fromisoformat(str(weather["now"])),
            interval_minutes=self._faceplate_refresh_interval(values),
        )
        if forced_daylight is not None:
            rise = datetime.fromisoformat(str(weather["sunrise"]))
            set_at = datetime.fromisoformat(str(weather["sunset"]))
            display_at = (rise + (set_at - rise) / 2) if forced_daylight else set_at + timedelta(hours=1)
        display_at = display_at.replace(second=0, microsecond=0)
        display_at -= timedelta(minutes=display_at.minute % self._faceplate_refresh_interval(values))
        primary = self.controllers.primary_battery()
        battery = quantize_battery(
            primary.get("percent") if primary else None,
            primary.get("charging") if primary else False,
            step=5 if values.get("faceplate_flash_protection_enabled", True) else 1,
        )
        steam_state = self.faceplate_steam_state.snapshot().render_payload("")
        dashboard_facts = self._faceplate_artwork_dashboard_facts(
            values, game_running,
        )
        artwork_revision = weather_artwork_cache_revision(visual_theme, "dashboard", condition)
        content_key = (
            f"dashboard-preview:{visual_theme}:{artwork_revision}:{condition}:{variant}:"
            f"{display_at.isoformat()}"
            + ":facts:" + hashlib.sha256(json.dumps(
                dashboard_facts, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest()[:20]
        )
        ticket = FaceplateSceneTicket(
            generation=0, scene="dashboard", context="preview",
            content_key=content_key, preference_revision=0,
        )
        data, manifest = self._render_faceplate_scene({
            "kind": "dashboard", "condition": condition, "variant": variant,
            "dashboard_show_clock": bool(values.get("faceplate_dashboard_show_clock", False)),
            "temperature_c": weather["temperature_c"], "unit": weather["unit"],
            "display_at": display_at.isoformat(), "city": weather.get("city", ""),
            "sunrise": weather["sunrise"], "sunset": weather["sunset"],
            "precipitation_probability": weather.get("precipitation_probability"),
            "clock_24h": values.get("faceplate_dashboard_clock_format", "24h") == "24h",
            "status": steam_state, "battery": battery,
            "visual_theme": visual_theme,
            **dashboard_facts,
        }, ticket)
        return {
            "gif": data, "condition": condition, "variant": variant,
            "temperature_c": weather["temperature_c"], "unit": weather["unit"],
            "size_bytes": len(data), "signature": manifest.get("signature", ""),
            "visual_theme": visual_theme, "live_weather": bool(status.get("condition")),
            "preset_id": manifest.get("preset_id", ""),
            "variant_name": manifest.get("variant_name", ""),
            "source_scene": manifest.get("source_scene", ""),
            "selection_status": manifest.get("selection_status", ""),
            "collection_revision": manifest.get("collection_revision", ""),
            "fallback_reason": manifest.get(
                "fallback_reason", manifest.get("selection_reason", ""),
            ),
        }

    def faceplate_artwork_dashboard_preview(self, appid, mode="", draft=False, home=False):
        """Preview the prepared or automatic local Dashboard without USB."""
        values = self.settings.all()
        appid = max(0, int(appid or 0))
        prepared = self._dashboard_background(
            appid, self.settings.artwork_for(appid).get("source", "hero"),
            home=home, mode=mode, draft=draft,
        )
        if not prepared:
            if home or draft:
                raise ValueError("Prepare and activate artwork for this game first")
            raise ValueError("No local Steam artwork is available for this game")
        manifest, background_fields, _projection = prepared
        primary = self.controllers.primary_battery()
        battery = quantize_battery(
            primary.get("percent") if primary else None,
            primary.get("charging") if primary else False,
            step=5 if values.get("faceplate_flash_protection_enabled", True) else 1,
        )
        facts = self._faceplate_artwork_dashboard_facts(
            values, not home,
        )
        display_at, _lead = self._faceplate_dashboard_target(datetime.now().astimezone(),
            interval_minutes=self._faceplate_refresh_interval(values))
        content_key = (
            f"artwork-dashboard-preview:{ARTWORK_DASHBOARD_REVISION}:"
            f"{manifest.get('dashboard_pack_sha256', '')}:{display_at.isoformat()}:"
            f"{manifest.get('dashboard_treatment', 'none')}:"
            f"{manifest.get('dashboard_compression', 'compatible')}:"
            + hashlib.sha256(json.dumps(
                facts, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest()[:20]
        )
        ticket = FaceplateSceneTicket(
            generation=0, scene="artwork-dashboard", context="preview",
            content_key=content_key, preference_revision=0,
        )
        data, rendered = self._render_faceplate_scene({
            "kind": "artwork-dashboard", "display_at": display_at.isoformat(),
            "session_minutes": 0, "battery": battery,
            **background_fields,
            "dashboard_pack_frames": manifest.get("dashboard_pack_frames", 0),
            "dashboard_pack_sha256": manifest.get("dashboard_pack_sha256", ""),
            "source_frame_count": manifest.get("frames", 0),
            "dashboard_treatment": manifest.get("dashboard_treatment", "none"),
            "dashboard_compression": manifest.get(
                "dashboard_compression", "compatible",
            ),
            "dashboard_show_clock": bool(
                home and values.get("faceplate_dashboard_show_clock", False)
            ),
            "dashboard_clock_size": manifest.get("dashboard_clock_size", "large"),
            "dashboard_show_status_rail": bool(values.get(
                "faceplate_dashboard_show_bottom_row", True,
            )),
            "dashboard_show_session": manifest.get("dashboard_show_session", True),
            "dashboard_show_battery": manifest.get("dashboard_show_battery", True),
            "status": self.faceplate_steam_state.snapshot().render_payload(),
            **facts,
        }, ticket)
        return {
            "gif": data, "frames": rendered.get("frames", 0),
            "delay_cs": rendered.get("delay_cs", 0), "size_bytes": len(data),
            "signature": rendered.get("signature", ""),
            "treatment": manifest.get("dashboard_treatment", "none"),
            "compression": manifest.get(
                "dashboard_compression", "compatible",
            ),
        }

    @staticmethod
    def _faceplate_refresh_interval(values):
        return 5 if values.get("faceplate_flash_protection_enabled", True) else 1

    @staticmethod
    def _faceplate_dashboard_target(requested_at, ack_ms=0, *, interval_minutes=1):
        """Prepare the selected minute boundary with a bounded USB lead."""
        try:
            ack_seconds = max(0.0, float(ack_ms or 0) / 1000.0)
        except (TypeError, ValueError, OverflowError):
            ack_seconds = 0.0
        lead_seconds = max(3.0, min(10.0, ack_seconds + 2.0))
        interval = 5 if interval_minutes == 5 else 1
        display_at = requested_at.replace(second=0, microsecond=0)
        display_at -= timedelta(minutes=display_at.minute % interval)
        next_boundary = display_at + timedelta(minutes=interval)
        if requested_at >= next_boundary - timedelta(seconds=lead_seconds):
            display_at = next_boundary
        return display_at, lead_seconds

    @staticmethod
    def _faceplate_dashboard_nonregressing(candidate, previous=None):
        """Keep an early next-minute upload from being followed by the old minute."""
        # Weather uses the provider's local wall time; Artwork uses the
        # machine's zoned time. A source change starts a new clock domain.
        # Comparing these two representations raises TypeError, and applying
        # an assumed local timezone would shift the selected city's clock.
        if previous is not None and ((candidate.utcoffset() is None)
                                     != (previous.utcoffset() is None)):
            return candidate
        if previous is not None and candidate < previous:
            return previous
        return candidate

    @staticmethod
    def _faceplate_artwork_dashboard_target(requested_at, interval_minutes,
                                            handler_ms=0):
        """Target a monotone refresh whose full-GIF commit should land on a boundary."""
        interval = 1 if int(interval_minutes) <= 1 else 5
        try:
            measured = max(0.0, float(handler_ms or 0) / 1000.0)
        except (TypeError, ValueError, OverflowError):
            measured = 0.0
        # Multi-frame artwork is materially larger than the Dashboard snapshot.
        # Use the measured full handler duration with a bounded safety margin.
        lead_seconds = max(4.0, min(45.0, measured * 1.15 + 2.0))
        floor_minute = requested_at.replace(second=0, microsecond=0)
        floor_minute -= timedelta(minutes=floor_minute.minute % interval)
        next_boundary = floor_minute + timedelta(minutes=interval)
        target = next_boundary if requested_at >= next_boundary - timedelta(
            seconds=lead_seconds,
        ) else floor_minute
        return target, lead_seconds

    def _artwork_route_key(self, appid, source):
        steamgriddb = getattr(self.faceplate, "steamgriddb", None)
        root = getattr(steamgriddb, "artwork_root", None)
        active_token = ""
        if root is not None:
            active = os.path.join(os.fspath(root), str(int(appid)), "active.json")
            try:
                stat = os.stat(active)
                active_token = f":{stat.st_mtime_ns}:{stat.st_size}"
            except OSError:
                pass
        return f"artwork:{int(appid)}:{str(source)}{active_token}"

    def _write_faceplate_runtime_status(self):
        hardware = self.faceplate.status()
        value = {
            "schema": 1, "updated_at": time.time(),
            "flash_protection": hardware.get("flash_protection", {}),
            "running": self._faceplate_runtime_running,
            "routing": self.faceplate_router.status(),
            "worker": self.faceplate_worker.status(),
            "weather": dict(self._faceplate_weather_summary),
            "player_city": self._player_city_status(),
            "device": {
                "available": bool(hardware.get("available")),
                "port": str(hardware.get("port", "")),
                "busy": bool(hardware.get("busy")),
                "phase": str(hardware.get("phase", "")),
                "brightness_control": hardware.get("brightness_control", {}),
            },
            "uploads": hardware.get("upload_observability", {}),
            "steam_status": self.faceplate_steam_state.snapshot().as_dict(),
            "artwork_dashboard": {
                "target_minute": (
                    self._faceplate_artwork_dashboard_target_minute.isoformat()
                    if self._faceplate_artwork_dashboard_target_minute else ""
                ),
                "session_minutes": self._faceplate_artwork_dashboard_session_minute,
                "lead_seconds": round(self._faceplate_artwork_dashboard_lead_seconds, 2),
                "battery": self._faceplate_artwork_dashboard_battery,
            },
        }
        serialized = json.dumps(value, sort_keys=True, separators=(",", ":"))
        # updated_at changes every call; compare the semantic portion instead.
        steam_status_semantic = {
            key: value["steam_status"].get(key)
            for key in (
                "recording", "recording_sequence", "observer_fresh",
                "recent_event", "event_sequence",
            )
        }
        city_semantic = {k:v for k,v in value["player_city"].items() if k not in {'display_age_s', 'next_refresh_s'}}
        city_semantic['sample'] = {k:v for k,v in city_semantic.get('sample',{}).items()
                                   if k not in ('sample_age_s','next_poll_s')}
        semantic = json.dumps(
            {"running": value["running"], "routing": value["routing"], "worker": value["worker"],
             "weather": {k:v for k,v in value["weather"].items() if k != 'age_s'}, "device": value["device"],
             "player_city": city_semantic,
             "uploads": value["uploads"],
             "steam_status": steam_status_semantic,
             "artwork_dashboard": value["artwork_dashboard"]},
            sort_keys=True, separators=(",", ":"),
        )
        if semantic == self._faceplate_runtime_serialized:
            return
        self._faceplate_runtime_serialized = semantic
        try:
            os.makedirs(os.path.dirname(self._faceplate_runtime_path), exist_ok=True)
            temporary = self._faceplate_runtime_path + ".tmp"
            with open(temporary, "w", encoding="utf-8") as stream:
                stream.write(serialized + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._faceplate_runtime_path)
        except OSError as error:
            self._warn("could not persist Faceplate runtime status: " + str(error)[:120])

    def _faceplate_continuity(self, *, wall_clock=None, monotonic_clock=None,
                              hardware=None, local_offset=None):
        """Detect clock corrections and USB sessions that need reasserting.

        Dashboard time is encoded in the GIF and the controller can retain an
        asset across USB sessions. Comparing wall time with monotonic time
        catches NTP/manual clock jumps. The explicit resume hook clears this
        baseline before its own forced reconciliation. The device signature
        makes reconnect recovery explicit while keeping the existing
        CRC-based no-rewrite path in the coordinator.
        """
        now_wall = time.time() if wall_clock is None else float(wall_clock)
        now_monotonic = (
            time.monotonic() if monotonic_clock is None else float(monotonic_clock)
        )
        reason = ""
        if self._faceplate_clock_anchor is not None:
            previous_wall, previous_monotonic = self._faceplate_clock_anchor
            wall_delta = now_wall - previous_wall
            monotonic_delta = now_monotonic - previous_monotonic
            if abs(wall_delta - monotonic_delta) > 5.0:
                reason = "clock-discontinuity"
        self._faceplate_clock_anchor = (now_wall, now_monotonic)
        offset = (datetime.fromtimestamp(now_wall).astimezone().utcoffset()
                  if local_offset is None else local_offset)
        if self._faceplate_local_offset is not None and offset != self._faceplate_local_offset:
            reason = "local-timezone-change"
        self._faceplate_local_offset = offset

        if hardware is None:
            probe = getattr(self.faceplate, "device_status", None)
            status = probe() if callable(probe) else self.faceplate.status()
        else:
            status = hardware
        status = status if isinstance(status, dict) else {}
        signature = (
            bool(status.get("available")), str(status.get("port", "")),
            bool(status.get("busy")), status.get("device_identity"),
        )
        previous = self._faceplate_device_signature
        changed = previous is not None and signature != previous
        if previous is not None and signature[0] and (
                not previous[0] or signature[1] != previous[1]
                or signature[3] != previous[3]
                or (previous[2] and not signature[2])):
            reason = "faceplate-reconnected"
        self._faceplate_device_signature = signature
        return reason, changed

    def _configure_player_city(self, hardware=None):
        provider = getattr(self, 'current_players', None)
        if provider is not None:
            values = self.settings.all()
            with self._lock:
                game = self._game
            preferences = self.faceplate_preferences.read()
            scene = preferences.scene_for("game" if game.running else "home")
            eligible = (scene == 'player-city' and game.running and values.get('faceplate_lab_enabled')
                and not self._faceplate_suspended and not self._stop.is_set() and not self._display_panel_off(values))
            available = (hardware if hardware is not None else self.faceplate.status()).get('available', False) if eligible else False
            appid = game.appid if eligible and available else 0
            if self._player_city_context != appid:
                if self._player_city_context:
                    self.faceplate_router.invalidate('player-city-context-changed')
                    self.faceplate_worker.cancel_scene_class('player-city')
                self._player_city_context = appid
            provider.configure(appid)

    def _admit_faceplate_route_recovery(self, reason, hardware=None):
        """Bound automatic replacement attempts while a delegated GIF is held dark.

        One missing final ACK permits one delayed ordinary transfer retry.
        This never powers on, fabricates confirmation or overrides explicit
        Off. Only the normal worker can commit and relight.
        """
        if not isinstance(self.faceplate, FaceplateCoordinator): return True
        pending = self.faceplate.restoration_status().get('pending', False)
        if not pending:
            self._faceplate_route_recovery = {}
            return True
        values = self.settings.all()
        if (self._faceplate_suspended or self._display_panel_off(values)
                or self._faceplate_power_target is False or not values.get('faceplate_lab_enabled')):
            return False
        preferences = self.faceplate_preferences.read()
        # Observe the USB session before admission. The old gate could block
        # forever before the coordinator got a chance to notice a reconnect.
        presence = hardware if hardware is not None else self.faceplate.device_status()
        if not presence.get('available') or presence.get('busy'):
            return False
        token = presence.get('device_identity', self.faceplate.device_token)
        key = (getattr(self.settings, '_commit_serial', 0), preferences.revision,
               self._game.appid, token)
        recovery = getattr(self, '_faceplate_route_recovery', {})
        if recovery.get('key') != key or reason == 'manual-power-on':
            recovery = {'key': key, 'attempts': 0, 'state': 'pending'}
            self._faceplate_route_recovery = recovery
        route = self.faceplate_router.status()
        state = route['preparation']['state']
        worker = self.faceplate_worker.status()
        if worker.get('busy') or worker.get('queued'):
            recovery['state'] = 'restoring'
            return False
        now = time.monotonic()
        if recovery['attempts'] and (state == 'unconfirmed' or self.faceplate.delivery.get('state') == 'unconfirmed'):
            if recovery['attempts'] >= 2 or recovery.get('confirmation_retry_used'):
                recovery['state'] = 'unconfirmed'
                return False
            if now < self._faceplate_scene_retry_at:
                recovery['state'] = 'retry-waiting'
                return False
            if not self.faceplate.retry_uncertain_restore():
                recovery['state'] = 'unconfirmed'
                return False
            recovery['confirmation_retry_used'] = True
            self._warn('Retrying current Faceplate image once after missing final USB confirmation')
        if recovery['attempts'] and now < self._faceplate_scene_retry_at:
            recovery['state'] = 'waiting'
            return False
        if recovery['attempts'] >= 3:
            recovery['state'] = 'exhausted'
            return False
        recovery.update(attempts=recovery['attempts'] + 1, state='restoring')
        # Also pace failures that occur before a worker request can be queued.
        self._faceplate_scene_retry_at = now + 60.0
        self._faceplate_resume_requested = True
        return True

    def _reconcile_faceplate(self, reason="periodic", force=False, hardware=None):
        self._configure_player_city(hardware)
        if getattr(self, '_onboarding_applying', False) or getattr(self, '_onboarding_recovery_blocked', False):
            return 0
        preview_until = getattr(self, '_faceplate_preview_until', 0.)
        if preview_until > time.monotonic():
            return 0
        if preview_until:
            self._faceplate_preview_until = 0.
            self._faceplate_resume_requested = True
        if self._assistant_holds_matrix():
            return 0
        values = self.settings.all()
        if self._display_panel_off(values):
            self._faceplate_next_reconcile = time.monotonic() + 2.0
            return 0
        if not values.get("faceplate_lab_enabled") or self._faceplate_suspended:
            return 0
        if self._faceplate_power_target is True:
            return 0
        adapter = getattr(self, 'jsaux_broker_adapter', None)
        if adapter is not None and adapter.holds_display():
            return 0
        if hardware is None:
            probe = getattr(self.faceplate, 'device_status', None)
            hardware = probe() if callable(probe) else self.faceplate.status()
        continuity_reason, device_changed = self._faceplate_continuity(hardware=hardware)
        if not self._admit_faceplate_route_recovery(reason, hardware):
            return 0
        if self._faceplate_resume_requested:
            force = True
            reason = 'current-route-restore'
        if continuity_reason:
            self._faceplate_native_epoch += 1
            force = True
            reason = continuity_reason
            if continuity_reason == "clock-discontinuity":
                self._faceplate_dashboard_target_minute = None
                self._faceplate_artwork_dashboard_target_minute = None
        self.weather.configure(
            values["weather_location"], values["weather_display"],
            values["weather_topbar_enabled"], values["night_mode_enabled"],
            self._faceplate_weather_required(values),
        )
        with self._lock:
            game = self._game
        preferences = self.faceplate_preferences.read()
        scene = preferences.scene_for("game" if game.running else "home")
        # Coalesce before rendering as well as at the serial gate. A periodic
        # telemetry tick must not repeatedly encode a GIF while the shared
        # budget is empty. Explicit/new context requests still reach the gate.
        if scene not in {"native-clock", "player-city"} and not force and reason == "periodic" and isinstance(self.faceplate, FaceplateCoordinator):
            priority = self.faceplate._upload_priority(scene, reason)
            if self.faceplate.flash.delay(priority) > 0:
                return 0
        visual_theme = preferences.theme_for(scene)
        weather_visual_theme = preferences.theme_for("weather")
        if scene not in {"dashboard", "artwork-dashboard"}:
            self._faceplate_dashboard_target_minute = None
        if scene != "artwork-dashboard" or not game.running:
            self._faceplate_artwork_dashboard_target_minute = None
            self._faceplate_artwork_dashboard_battery = None
        if scene not in {"weather", "dashboard", "native-clock"} and not game.running:
            weather, _, _ = self._faceplate_weather_payload(values, game.running)
            if weather is not None:
                artwork_revision = weather_artwork_cache_revision(
                    weather_visual_theme, "weather", weather["condition"],
                )
                cache_key = (
                    f"weather:{weather_visual_theme}:{artwork_revision}:"
                    + weather["signature"]
                )
                worker = self.faceplate_worker.status()
                if (cache_key != self._faceplate_cached_weather_key
                        and not worker["busy"] and not worker["queued"]):
                    self.faceplate_worker.submit(
                        f"cache-weather:{weather['signature'][-24:]}",
                        {"kind": "cache_weather", "content_key": cache_key,
                         "visual_theme": weather_visual_theme, **weather},
                        {"reason": "weather-cache-refresh", "scene_class": "cache"},
                    )
        payload = {"kind": scene, "visual_theme": visual_theme}
        metadata = {"reason": str(reason)[:96], "scene_class": scene}
        background_fingerprint = ''
        background_layout = None
        error = ""
        if scene == 'player-city':
            sample = self.current_players.status()
            weather, _, _weather_error = self._faceplate_weather_payload(values, game.running)
            candidate = self.player_city.plan(game.appid, sample, weather, restore=force)
            row = self._faceplate_player_city_facts(values)
            row_target = getattr(self, '_player_city_row_target', None)
            replace_row = bool(force or row_target and row_target['appid'] == game.appid and row_target['row'] != row)
            row_candidate = self.player_city.plan_row(game.appid, row, replace=replace_row)
            if candidate is None or (row_candidate and player_city_key(candidate) == player_city_key(row_candidate)
                    and not candidate.get('_screensaver_refresh')):
                if row_candidate and candidate and candidate.get('_confirmed_restore'):
                    row_candidate['_confirmed_restore'] = True
                candidate = row_candidate
            if candidate is None:
                # Waiting for Steam must still publish the selected game route
                # and fence the previous Home ticket. Never fabricate pixels.
                route = self.faceplate_router.status()
                if route['context'] != 'game' or route['desired_scene'] != scene:
                    self.faceplate_router.reconcile(game_running=game.running,
                        content_key=f'player-city:waiting:{game.appid}', reason=reason)
                self._write_faceplate_runtime_status()
                return 0
            confirmed_restore = candidate.pop('_confirmed_restore', False)
            payload.update(candidate)
            payload['row'] = row
            self._player_city_row_target = {'appid': game.appid, 'row': row}
            # The GIF rail changes independently of the frozen hourly picture.
            payload['countdown'] = row.get('countdown', {})
            content_key = PLAYER_CITY_REVISION + ':' + player_city_key(candidate) + ':row:' + json.dumps(row, sort_keys=True)
            metadata.update(upload_interval_seconds=60 if candidate.get('_row_refresh') else 3600, persistent_write=True,
                player_city_restore=confirmed_restore)
        elif scene == "native-clock":
            # No time/minute bucket: the MCU owns the ticking clock. Only real
            # continuity events change this key; unrelated forced reconciles
            # are deduplicated again inside the coordinator's serial lock.
            content_key = f"native-clock:{self._faceplate_native_epoch}:{values.get('faceplate_rotate_180', False)}"
        elif scene == "artwork-dashboard" and game.running:
            if game.appid <= 0:
                error = "Artwork Dashboard requires a running Steam game"
                content_key = "artwork-dashboard:no-game"
            else:
                artwork_settings = self.settings.artwork_for(game.appid)
                source = artwork_settings.get("source", "hero")
                base = self._artwork_route_key(game.appid, source)
                library = getattr(self.faceplate, "steamgriddb", None)
                ready = (
                    library.selected_dashboard_manifest(game.appid)
                    if library is not None else {}
                )
                background_fingerprint = ready.get('dashboard_pack_sha256') or base
                if not ready:
                    background_layout = values.get('faceplate_artwork_profiles', {}).get(str(game.appid), {
                        'style': values.get('faceplate_artwork_style'), 'position': values.get('faceplate_logo_position')})
                interval = self._faceplate_refresh_interval(values)
                policy = "economy" if interval == 5 else "minute"
                requested_at = datetime.now().astimezone()
                worker_status = self.faceplate_worker.status()
                display_at, lead_seconds = self._faceplate_artwork_dashboard_target(
                    requested_at, interval, worker_status.get("handler_ema_ms", 0),
                )
                display_at = self._faceplate_dashboard_nonregressing(
                    display_at, self._faceplate_artwork_dashboard_target_minute,
                )
                target_changed = display_at != self._faceplate_artwork_dashboard_target_minute
                self._faceplate_artwork_dashboard_target_minute = display_at
                self._faceplate_artwork_dashboard_lead_seconds = lead_seconds
                if target_changed:
                    primary = self.controllers.primary_battery()
                    self._faceplate_artwork_dashboard_battery = quantize_battery(
                        primary.get("percent") if primary else None,
                        primary.get("charging") if primary else False,
                        step=5 if values.get("faceplate_flash_protection_enabled", True) else 1,
                    )
                started = self._faceplate_game_started_monotonic
                elapsed = max(0.0, time.monotonic() - started) if started else 0.0
                projected = max(0.0, (display_at - requested_at).total_seconds())
                if target_changed:
                    self._faceplate_artwork_dashboard_session_minute = max(
                        self._faceplate_artwork_dashboard_session_minute,
                        int((elapsed + projected) // 60),
                    )
                session_minutes = self._faceplate_artwork_dashboard_session_minute
                battery_key = json.dumps(
                    self._faceplate_artwork_dashboard_battery,
                    sort_keys=True, separators=(",", ":"),
                )
                content_key = (
                    f"artwork-dashboard:{ARTWORK_DASHBOARD_REVISION}:"
                    f"{base}:{'prepared' if ready else 'automatic'}:{policy}:"
                    "clock-off:"
                    f"{ready.get('dashboard_treatment', 'none')}:"
                    f"{ready.get('dashboard_compression', 'compatible')}"
                )
                payload.update({
                    "appid": game.appid, "source": source,
                    "display_at": display_at.isoformat(),
                    "session_minutes": session_minutes,
                    "battery": self._faceplate_artwork_dashboard_battery,
                    "refresh_policy": policy,
                    "clock_lead_seconds": lead_seconds,
                })
                dashboard_facts = self._faceplate_artwork_dashboard_facts(
                    values, game.running,
                )
                payload.update(dashboard_facts)
                facts_key = hashlib.sha256(json.dumps(
                    dashboard_facts, sort_keys=True, separators=(",", ":"),
                ).encode("utf-8")).hexdigest()[:20]
                content_key += ":facts:" + facts_key
                metadata.update({
                    "refresh_policy": policy,
                    "upload_interval_seconds": interval * 60,
                    "persistent_write": True,
                })
        elif scene == "artwork" and not game.running:
            appid = int(values.get("faceplate_dashboard_home_appid", 0) or 0)
            library = getattr(self.faceplate, "steamgriddb", None)
            ready = library.home_dashboard_manifest(appid) if library is not None and appid > 0 else {}
            self._faceplate_home_artwork_prepared = bool(ready)
            if ready:
                payload.update({"appid": appid, "home_artwork": True})
                content_key = f"home-artwork:{appid}:{ready.get('sha256', '')}"
                background_fingerprint = ready.get('dashboard_pack_sha256', '')
            else:
                weather, _, error = self._faceplate_weather_payload(values, False)
                content_key = "home-artwork:weather-unavailable"
                if weather:
                    payload.update(weather, kind="weather")
                    content_key = "home-artwork:fallback:" + weather["signature"]
        elif scene == "artwork":
            if game.appid <= 0:
                error = "Artwork requires a running Steam game"
                content_key = "artwork:no-game"
            else:
                artwork_settings = self.settings.artwork_for(game.appid)
                source = artwork_settings.get("source", "hero")
                content_key = self._artwork_route_key(game.appid, source)
                background_fingerprint = content_key
                background_layout = values.get('faceplate_artwork_profiles', {}).get(str(game.appid), {
                    'style': values.get('faceplate_artwork_style'), 'position': values.get('faceplate_logo_position')})
                payload.update({"appid": game.appid, "source": source})
        elif scene in {"weather", "dashboard", "artwork-dashboard"}:
            # Realistic Weather is the sole collection renderer. An artwork
            # chosen explicitly by the user remains a first-class Dashboard
            # Home background and intentionally takes priority over it.
            home_artwork_appid = (
                int(values.get("faceplate_dashboard_home_appid", 0) or 0)
                if (not game.running and (scene == "artwork-dashboard" or
                    scene == "dashboard" and values.get("faceplate_dashboard_home_source") == "artwork"))
                else 0
            )
            library = getattr(self.faceplate, "steamgriddb", None)
            home_ready = (
                (library.home_dashboard_manifest(home_artwork_appid)
                 if hasattr(library, "home_dashboard_manifest")
                 else library.selected_dashboard_manifest(home_artwork_appid))
                if library is not None and home_artwork_appid > 0 else {}
            )
            self._faceplate_home_artwork_prepared = bool(home_ready)
            fallback_weather = None
            if scene in {"dashboard", "artwork-dashboard"}:
                fallback_weather, _, _ = self._faceplate_weather_payload(
                    values, game.running,
                )
                if (fallback_weather
                        and fallback_weather.get("fallback_state") == "background-only"):
                    # The explicit >2 h degraded contract is one last-known
                    # weather background, clock and controllers. A user-picked
                    # Home artwork remains selected and returns automatically
                    # as soon as fresh weather is available again.
                    home_ready = {}
            if home_ready:
                background_fingerprint = home_ready.get('dashboard_pack_sha256', '')
                requested_at = datetime.now().astimezone()
                worker_status = self.faceplate_worker.status()
                display_at, lead_seconds = self._faceplate_dashboard_target(
                    requested_at, worker_status.get("ack_ema_ms", 0),
                    interval_minutes=self._faceplate_refresh_interval(values),
                )
                display_at = self._faceplate_dashboard_nonregressing(
                    display_at, self._faceplate_dashboard_target_minute,
                )
                self._faceplate_dashboard_target_minute = display_at
                payload.update({
                    "kind": "artwork-dashboard", "appid": home_artwork_appid,
                    "display_at": display_at.isoformat(), "session_minutes": 0,
                    "home_dashboard": True, "clock_lead_seconds": lead_seconds,
                })
                dashboard_facts = self._faceplate_artwork_dashboard_facts(
                    values, game.running,
                )
                payload.update(dashboard_facts)
                facts_key = hashlib.sha256(json.dumps(
                    dashboard_facts, sort_keys=True, separators=(",", ":"),
                ).encode("utf-8")).hexdigest()[:20]
                content_key = (
                    f"dashboard-home-artwork:{ARTWORK_DASHBOARD_REVISION}:"
                    f"{home_artwork_appid}:"
                    f"{home_ready.get('dashboard_pack_sha256', '')}:"
                    f"{home_ready.get('dashboard_treatment', 'none')}:"
                    f"{home_ready.get('dashboard_compression', 'compatible')}:"
                    f"{display_at.isoformat() if dashboard_facts['dashboard_show_clock'] else 'clock-off'}:facts:{facts_key}"
                )
                metadata.update({
                    "home_artwork_appid": home_artwork_appid,
                    "upload_interval_seconds": self._faceplate_refresh_interval(values) * 60, "persistent_write": True,
                })
            else:
                weather = fallback_weather
                if weather is None:
                    weather, _, error = self._faceplate_weather_payload(
                        values, game.running,
                    )
                else:
                    error = ""
                if weather is None:
                    content_key = f"{scene}:weather-unavailable"
                else:
                    fallback_dashboard = bool(
                        weather.get("fallback_state") == "background-only"
                    )
                    dashboard_scene = scene in {"dashboard", "artwork-dashboard"} or fallback_dashboard
                    scene_weather = dict(weather)
                    if dashboard_scene:
                        scene_weather.pop("weather_code", None)
                        scene_weather.pop("wind_speed_kmh", None)
                    payload.update(scene_weather)
                    if dashboard_scene:
                        payload["kind"] = "dashboard"
                    artwork_revision = weather_artwork_cache_revision(
                        visual_theme, "dashboard" if dashboard_scene else scene, weather["condition"],
                    )
                    background_fingerprint = artwork_revision
                    content_key = (
                        f"{'weather-fallback-dashboard' if fallback_dashboard else scene}:"
                        f"{visual_theme}:{artwork_revision}:"
                        f"{weather['signature']}"
                    )
                    if dashboard_scene:
                        dashboard_facts = self._faceplate_artwork_dashboard_facts(
                            values, game.running,
                        )
                        payload.update(dashboard_facts)
                        requested_at = datetime.fromisoformat(weather["now"])
                        worker_status = self.faceplate_worker.status()
                        display_at, lead_seconds = self._faceplate_dashboard_target(
                            requested_at, worker_status.get("ack_ema_ms", 0),
                            interval_minutes=self._faceplate_refresh_interval(values),
                        )
                        display_at = self._faceplate_dashboard_nonregressing(
                            display_at, self._faceplate_dashboard_target_minute,
                        )
                        self._faceplate_dashboard_target_minute = display_at
                        display_minute = display_at.isoformat()
                        payload["display_at"] = display_minute
                        payload["dashboard_show_clock"] = dashboard_facts["dashboard_show_clock"]
                        payload["clock_24h"] = (
                            values.get("faceplate_dashboard_clock_format", "24h") == "24h"
                        )
                        payload["clock_lead_seconds"] = lead_seconds
                        facts_key = hashlib.sha256(json.dumps(
                            dashboard_facts, sort_keys=True, separators=(",", ":"),
                        ).encode("utf-8")).hexdigest()[:20]
                        content_key += ":" + (display_minute if payload["dashboard_show_clock"] else "clock-off") + ":facts:" + facts_key
        else:
            error = f"unsupported Faceplate route {scene}"
            content_key = f"unsupported:{scene}"

        if content_key.endswith(":weather-unavailable"):
            # Missing city/solar data must not strand an exited autonomous GIF.
            # A stable neutral frame replaces it through the normal ACK gate;
            # no invented location, weather, sunrise or temperature is used.
            payload.update(kind="dashboard" if scene in {"dashboard", "artwork-dashboard"} else "weather",
                           weather_unavailable=True, display_at=self._faceplate_dashboard_target(
                               datetime.now().astimezone(), interval_minutes=self._faceplate_refresh_interval(values))[0].isoformat())
            payload.update(self._faceplate_artwork_dashboard_facts(values, game.running))
            if payload["kind"] == "weather":
                payload.update(dashboard_show_clock=False, dashboard_show_status_rail=False,
                               show_weather_notch=False)
            payload["clock_24h"] = values.get("faceplate_dashboard_clock_format", "24h") == "24h"
            error = ""
            payload["unit"] = values.get("weather_temperature_unit", "celsius")
            metadata["fallback"] = "weather-unavailable"
            content_key += ":neutral-v1:" + hashlib.sha256(json.dumps(
                {k:v for k,v in payload.items() if k != "display_at"},
                sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]
            if payload.get("dashboard_show_clock"):
                content_key += ":" + payload["display_at"][:16]

        if not error and scene == "weather" and "countdown" not in payload:
            payload["countdown"] = self._faceplate_playtime_facts(values, game.running)
            content_key += ":timer:" + json.dumps(payload["countdown"], sort_keys=True)
        if payload.get("countdown", {}).get("state") == "ended":
            with self._lock:
                ending = self._faceplate_timer_end
                if ending:
                    metadata["timer_completion_id"] = ending["id"]
                    content_key += ":timer-end:" + ending["id"]
        if not error and scene in {"dashboard", "artwork-dashboard"}:
            # Notifications never create an immediate write.  They become
            # visible only when the scene's ordinary minute/five-minute base
            # key changes. REC transitions are different: their tri-state is
            # always part of the key, so start/stop can each queue one update.
            slot = ("game" if game.running else "home") + ":" + scene
            base_content_key = content_key
            natural_refresh = (
                self._faceplate_status_base_keys.get(slot) != base_content_key
            )
            status_snapshot = self.faceplate_steam_state.snapshot()
            if natural_refresh:
                self._faceplate_status_base_keys[slot] = base_content_key
                self._faceplate_status_recent[slot] = (
                    status_snapshot.recent_event,
                    status_snapshot.event_sequence if status_snapshot.recent_event else 0,
                )
                if scene == "dashboard" or not game.running:
                    primary = self.controllers.primary_battery()
                    self._faceplate_status_battery[slot] = quantize_battery(
                        primary.get("percent") if primary else None,
                        primary.get("charging") if primary else False,
                        step=5 if values.get("faceplate_flash_protection_enabled", True) else 1,
                    )
            recent_event, recent_sequence = self._faceplate_status_recent.get(
                slot, ("", 0),
            )
            status_payload = status_snapshot.render_payload(recent_event)
            status_payload["event_sequence"] = recent_sequence if recent_event else 0
            if (payload.get("kind") == "artwork-dashboard"
                    and status_payload.get("recent_event") == "notification"):
                status_payload["recent_event"] = ""
                status_payload["event_sequence"] = 0
            if scene == "artwork-dashboard" and game.running:
                battery = payload.get("battery")
            else:
                battery = self._faceplate_status_battery.get(slot)
                payload["battery"] = battery
            payload["status"] = status_payload
            status_key = hashlib.sha256(json.dumps(
                {"battery": battery, "status": status_payload},
                sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            content_key = f"{base_content_key}:status:{status_key}"
            metadata.update({
                "recording_state": status_payload["recording"],
                "status_event": status_payload["recent_event"],
            })

        route_status = self.faceplate_router.status()
        previous_generation = route_status["generation"]
        if scene == 'player-city' and route_status['preparation']['state'] == 'unconfirmed':
            # plan() has already enforced the single hourly retry interval.
            force = True
        if (route_status["preparation"]["state"] == "error"
                and time.monotonic() >= self._faceplate_scene_retry_at):
            force = True
        ticket = self.faceplate_router.reconcile(
            game_running=game.running, content_key=content_key,
            reason=reason, force=force,
        )
        source_key = None if error or scene == "native-clock" else background_key(payload, ticket.context, game.appid,
            background_fingerprint, background_layout)
        self._faceplate_extension_target = {'key': source_key, 'context': ticket.context,
            'appid': game.appid, 'generation': ticket.generation}
        payload['_extension_background_key'] = source_key
        if ticket.generation == previous_generation and not force:
            if device_changed:
                self._write_faceplate_runtime_status()
            return 0
        payload["ticket"] = ticket
        if error:
            self.faceplate_router.fail(ticket, error)
            self._write_faceplate_runtime_status()
            return 0
        if reason == 'external-finished-current-route':
            metadata=dict(metadata,external_origin=dict(self.assistant.restore_origin))
        # Establish the fallback deadline before the worker can finish. Its
        # specific receipt (confirmed/unconfirmed/deferred) owns the next one.
        self._faceplate_scene_retry_at = time.monotonic() + 60.0
        generation = self.faceplate_worker.submit(
            f"{scene}:{content_key[-32:]}", payload, metadata,
        )
        if not generation:
            rejection = self.faceplate_worker.status().get("last_rejection")
            self.faceplate_router.fail(
                ticket, rejection or "Faceplate scene worker is unavailable",
            )
            self._faceplate_scene_retry_at = time.monotonic() + 60.0
        else:
            self._faceplate_resume_requested = False
        self._write_faceplate_runtime_status()
        return generation

    def _consume_faceplate_control(self):
        try:
            from pathlib import Path
            path = Path(self._faceplate_control_path)
            if path.is_file() and not path.is_symlink():
                archive = path.with_name('faceplate-control.retired-' + str(time.time_ns()) + '.json')
                path.rename(archive)
                os.chmod(archive, 0o600)
        except OSError:
            pass
        return 0

    def preview_weather(self, condition, variant, visual_theme=None):
        if not self._weather_preview_allowed():
            return False
        values = self.settings.all()
        base_condition, preview_daylight = weather_preview_condition(condition)
        if values["faceplate_lab_enabled"]:
            rendered = self.faceplate_weather_preview(
                condition, variant, visual_theme,
            )
            preview_daylight = rendered['phase'] in ('dawn', 'day')
            self._faceplate_preview_until = time.monotonic() + 15.
            generation = self.faceplate_worker.submit(
                'weather-preview:' + rendered['signature'][-24:],
                {'kind': 'weather-preview', 'data': rendered['gif'],
                 'signature': rendered['signature'], 'condition': base_condition, 'variant': variant,
                 'is_day': preview_daylight,
                 'peak_load': rendered.get('peak_load', POWER_BUDGET)},
                {'reason': 'weather-preview', 'scene_class': 'preview'},
            )
            if not generation:
                self._faceplate_preview_until = 0.
                return False
        return self.weather.preview(base_condition, variant, is_day=preview_daylight)

    def stop_weather_preview(self):
        self.weather.stop_preview()
        if getattr(self, '_faceplate_preview_until', 0):
            self._faceplate_preview_until = 0.
            self._faceplate_resume_requested = True
            self._faceplate_next_reconcile = 0.
        return True

    def patch_assistant_settings(self, patch):
        from signalbar.core.legacy_preferences import settings
        with self.settings._lock:
            current = self.settings.base_all().get('gabe_assistant', {})
            self.settings.update({'gabe_assistant': settings({**current, **patch})})
        return self.refresh_settings({'gabe_assistant': True})

    def update_settings(self, changes):
        previous = self.settings.all()
        values = self.settings.update(changes)
        changes = {**changes, **{key: value for key, value in values.items() if previous.get(key) != value}}
        return self.refresh_settings(changes)

    def refresh_settings(self, changes):
        # Serialize provider application, then read the current snapshot. A
        # delayed setup/update can never reapply an older committed revision.
        with self._settings_apply_lock:
            return self._refresh_settings(changes)

    def _refresh_settings(self, changes):
        values = self.settings.all()
        if set(changes) == {'free_timer_end_action'}:
            if values['free_timer_end_action'] == 'none':
                self.countdown.end_action.cancel('user-disabled')
            return values
        if set(changes) == {"ui_language"}:
            return values
        if set(changes) == {"gabe_assistant"}:
            return values
        # Interface language must not reconfigure providers or touch hardware.
        if set(changes) not in ({"ui_language"}, {"free_timer_end_action"}):
            self._apply_settings(values, changes)
        return values

    def import_configuration(self, global_values, display_profiles, artwork_profiles,
                             launch_artwork_profiles=None, *, _reset=False):
        self.countdown.end_action.cancel('configuration-import')
        previous = self.settings.all()
        values = self.settings.reset_configuration() if _reset else self.settings.replace_configuration(
            global_values, display_profiles, artwork_profiles, launch_artwork_profiles,
        )
        changes = {key: value for key, value in values.items() if previous.get(key) != value}
        if getattr(self, "assistant", None) is not None:
            self.assistant.cancel()
            self.assistant.configure({})
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

    def set_steam_control(self, enabled):
        """Native bar ownership independent of saved content and matrix power."""
        if type(enabled) is not bool:
            raise ValueError('Steam control requires a boolean')
        if not enabled:
            # Lab 99 stored Steam as content. Only an explicit reclaim migrates
            # that legacy context; new native control never rewrites routes.
            values = self.settings.all()
            appid = self._game.appid
            display = self.settings.display_for(appid)
            if display['selected'] == 'steam':
                if appid > 0 and display['override'] == 'steam':
                    self.settings.update_display(appid, 'inherit')
                if self.settings.display_for(appid)['selected'] == 'steam':
                    key = 'game_display' if appid > 0 else 'home_display'
                    prior = values.get('display_preset_restore', {}).get(key)
                    self.settings.update({key: prior if prior and prior != 'steam' else DEFAULTS[key]})
        self.update_settings({'steam_control_enabled': enabled})

    def display_control_snapshot(self):
        """Small diagnostic snapshot; no serial probe, decoding or inventory."""
        values = self.settings.all()
        capture = self.screen_sync.status()
        activation = self.screen_sync_activation.status(
            game_route=bool(values['mode'] == 'screen_sync' and self._game.running),
            screensaver_enabled=values['screen_sync_screensaver_enabled'],
            enabled=values['signalbar_enabled'])
        return {'enabled': bool(values['signalbar_enabled']),
                'screensaver_light_bar_mode':values['screensaver_light_bar_mode'],
                'steam_control': bool(values.get('steam_control_enabled')),
                'selected': self.settings.display_for(self._game.appid)['selected'],
                'home_display': values['home_display'], 'game_display': values['game_display'],
                'owner': self._owner, 'provider': self._decision,
                'suspension': str(self._suspension_reason)[:180],
                'engine_alive': bool(self._thread and self._thread.is_alive()),
                'stop_requested': self._stop.is_set(),
                'runtime_failures': [dict(item) for item in self._runtime_failures],
                'faceplate_suspended': self._faceplate_suspended,
                'power_target': self._faceplate_power_target,
                'power_recovery': dict(self._faceplate_power_status),
                'faceplate_powered': self.faceplate.powered,
                'restoration': self.faceplate.restoration_status() if isinstance(self.faceplate,FaceplateCoordinator) else {},
                'delivery': dict(getattr(self.faceplate, 'delivery', {})),
                'game': {'appid': self._game.appid, 'running': self._game.running},
                'player_city': self._player_city_status(),
                'faceplate_extension': self._faceplate_extension_status(),
                'native_clock': dict(getattr(self.faceplate, 'native_clock', {})),
                'routing': self.faceplate_router.status(),
                'screen_sync': {
                    **{key: capture.get(key) for key in ('phase', 'error', 'frame_age_s',
                       'active', 'revision', 'capture_identity', 'capture_selector',
                       'conflicting_consumers', 'frames_per_second', 'runtime_dir',
                       'discovery_detail', 'last_release_error', 'attempt',
                       'recent_failures', 'capture_sessions_released',
                       'orphan_processes_cleaned', 'retry_paused', 'unhealthy_sessions')},
                    'activation': activation,
                    'fallback_active': bool(activation['requested'] and self._decision.startswith('customization')),
                    'fallback_pattern': values.get('customization_pattern') if
                        activation['requested'] and self._decision.startswith('customization') else None,
                },
                'last_transfer': {key: value for key, value in self.faceplate.last_transfer.items()
                    if key in {'configured_profile', 'active_profile', 'end_timeout_seconds',
                               'chunks', 'chunks_ms', 'finalize_ms', 'total_ms', 'cancelled',
                               'failed_chunk', 'chunk_status', 'payload_bytes_confirmed',
                               'payload_complete', 'end_sent', 'sent_unconfirmed',
                               'already_stored', 'begin_status', 'end_status', 'stored_activation_required',
                               'restore_repacked', 'restore_begin_status', 'source_begin_status'}}}

    def reset_configuration(self):
        self.countdown.end_action.cancel('configuration-reset')
        return self.import_configuration({}, {}, {}, _reset=True)

    def reset_settings_only(self):
        """Reset preferences; never clear saved media, recipes or credentials."""
        with self._settings_apply_lock:
            values = self.reset_configuration()
            self.faceplate_preferences.reset()
            self.faceplate_router.invalidate("settings-reset")
            # Follow remains checked, but discard work from the forgotten setup.
            # Applying the new guided setup reconfigures the worker normally.
            self.faceplate_worker.configure(False)
            self._faceplate_follow_key = None
            self._faceplate_resume_requested = False
            self._faceplate_route_recovery = {}
            self.faceplate.steamgriddb.set_preference("animated_any")
            return values

    def _apply_settings(self, values, changes):
        if isinstance(self.faceplate, FaceplateCoordinator):
            self.faceplate.flash.configure(values.get("faceplate_flash_protection_enabled", True))
            if "faceplate_flash_protection_enabled" in changes:
                self._faceplate_dashboard_target_minute = None
                self._faceplate_artwork_dashboard_target_minute = None
                self._faceplate_artwork_dashboard_battery = None
                self._faceplate_scene_retry_at = 0.0
                self._faceplate_next_reconcile = 0.0
        self._assistant_wake_allowed = self._assistant_wake_policy(values)
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
            self._faceplate_weather_required(values),
        )
        # These configure methods share the serial lock. A master/game toggle
        # must cancel/queue power immediately, not wait for an unrelated GIF.
        if any(key in changes for key in ('faceplate_lab_enabled', 'faceplate_brightness')):
            self.faceplate.configure(
                values["faceplate_lab_enabled"], values["faceplate_brightness"],
            )
        if hasattr(self.faceplate, "configure_artwork") and any(key in changes for key in (
                'faceplate_artwork_style', 'faceplate_logo_position',
                'faceplate_artwork_profiles', 'faceplate_rotate_180')):
            self.faceplate.configure_artwork(
                values["faceplate_artwork_style"],
                values["faceplate_logo_position"],
                values["faceplate_artwork_profiles"],
                values["faceplate_rotate_180"],
            )
        if any(key in changes for key in (
                "faceplate_rotate_180", "faceplate_artwork_style",
                "faceplate_logo_position", "faceplate_artwork_profiles")):
            self._faceplate_follow_key = None
            self._faceplate_next_reconcile = 0.0
            if values["faceplate_lab_enabled"]:
                self._reconcile_faceplate("faceplate-presentation-change", force=True)
        self.faceplate_worker.configure(bool(values["faceplate_lab_enabled"] and not self._display_panel_off(values) and not self._faceplate_suspended))
        self._sync_display_power_policy()
        if not values["faceplate_lab_enabled"]:
            self._faceplate_follow_key = None
            self._faceplate_clock_anchor = None
            self._faceplate_device_signature = None
            self._faceplate_artwork_dashboard_target_minute = None
            self._faceplate_artwork_dashboard_battery = None
            self._write_faceplate_runtime_status()
        elif "faceplate_lab_enabled" in changes:
            self._faceplate_next_reconcile = 0.0
            self._reconcile_faceplate("faceplate-enabled", force=True)
        if any(key in changes for key in ('faceplate_player_city_row',
                'faceplate_player_city_dashboard_row', 'faceplate_player_city_battery_style')):
            self._faceplate_next_reconcile = 0.0
            if values['faceplate_lab_enabled']:
                self._reconcile_faceplate('city-row-change')
        if 'faceplate_dashboard_contexts' in changes:
            # Re-evaluate the current context on the normal scheduler. Editing
            # Home while in a game must not force an unchanged GIF upload.
            self._faceplate_next_reconcile = 0.0
        if any(key in changes for key in (
                "lab58_ux_enabled",
                "faceplate_dashboard_show_bottom_row",
                "faceplate_dashboard_bottom_mode",
                "faceplate_dashboard_battery_style",
                "faceplate_dashboard_show_p2",
                "faceplate_dashboard_clock_format",
                "faceplate_dashboard_show_weather",
                "faceplate_dashboard_show_clock",
                "faceplate_dashboard_clock_position",
                "faceplate_dashboard_game_session",
                "faceplate_playtime_enabled",
                "weather_temperature_unit")):
            self._faceplate_dashboard_target_minute = None
            self._faceplate_artwork_dashboard_target_minute = None
            self._faceplate_next_reconcile = 0.0
            if values["faceplate_lab_enabled"]:
                self._reconcile_faceplate("dashboard-layout-change", force=True)
        if any(key in changes for key in (
                "faceplate_dashboard_home_appid",
                "faceplate_dashboard_home_source")):
            self._faceplate_dashboard_target_minute = None
            self._faceplate_next_reconcile = 0.0
            if (values["faceplate_lab_enabled"]
                    and self.faceplate_preferences.read().home_scene in {"dashboard", "artwork-dashboard", "artwork"}):
                self._reconcile_faceplate("dashboard-home-artwork", force=True)
        if ("faceplate_brightness" in changes and values["faceplate_lab_enabled"]
                and not self._faceplate_suspended and not self._display_panel_off(values)
                and hasattr(self.faceplate, "set_brightness")):
            # A gain command applies to the MCU's current pixels. Do not
            # invalidate the scene/CRC or rewrite its persistent GIF.
            self.faceplate.set_brightness(values["faceplate_brightness"], "settings")
            self._write_faceplate_runtime_status()
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
        if provider.startswith('faceplate-extension:'):
            return 'weather' if provider.startswith('faceplate-extension:weather') else 'artwork'
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
                               companion_hud_active=False, recording=False):
        return bool(
            values["signalbar_enabled"]
            and requested
            and not signal_critical
            and not steam_priority
            and not companion_hud_active
            and not recording
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

    def _record_runtime_fault(self, stage, error):
        """Capture the real traceback without locals, USB probes or a watcher."""
        detail = f'{type(error).__name__}: {error}'[:240]
        failure = {'stage': str(stage)[:48], 'error': detail, 'at': time.time(),
                   'traceback': ''.join(traceback.format_exception(type(error), error, error.__traceback__))[-4000:],
                   'stack': [{'file': os.path.basename(frame.filename), 'line': frame.lineno,
                              'function': frame.name} for frame in traceback.extract_tb(error.__traceback__)[-12:]]}
        with self._lock:
            self._last_runtime_error = detail
            self._last_runtime_error_at = time.monotonic()
            self._runtime_failures.append(failure)
            del self._runtime_failures[:-4]
        self._warn(f'Isolated runtime fault [{stage}]: {detail}')

    def _safe_runtime_cleanup(self):
        renderer = self._renderer
        for name, cleanup in (
            ('assistant-cancel', self.assistant.cancel),
            ('screen-sync-stop', lambda: self.screen_sync.set_active(False)),
            ('audio-sync-stop', lambda: self.audio_sync.set_active(False)),
            ('restore-native-bar', lambda: renderer.relinquish(restore_if_owned=True) if renderer else None),
            ('event-lease', self.event_lease.release),
            ('stripmine-lease', self.stripmine_claim.release),
        ):
            try:
                cleanup()
            except Exception as error:
                self._record_runtime_fault(name, error)
        with self._lock:
            self._available = False
            self._owner = 'Valve'
            self._decision = 'none'
            self._suspension_reason = 'Runtime recovery'
            self._error = self._last_runtime_error
            self._renderer = None
            self._guard = None

    def _run(self):
        # The existing engine thread supervises all stages, not just drawing.
        # No new process, watchdog thread or status polling is introduced.
        try:
            while not self._stop.is_set():
                try:
                    self._run_loop()
                    break
                except Exception as error:
                    self._record_runtime_fault('engine', error)
                    self._safe_runtime_cleanup()
                    if self._stop.wait(0.5):
                        break
        finally:
            self._safe_runtime_cleanup()
            self._faceplate_runtime_running = False

    def _run_loop(self):
        hardware = None
        renderer = None
        guard = None
        interval = 0.10
        event_was_active = False
        event_preempted_valve = False
        next_hardware_attempt = 0.0
        while not self._stop.is_set():
            self._service_timer_end_action()
            return_adapter=getattr(self,'jsaux_broker_adapter',None)
            if return_adapter is not None:return_adapter.service_continuous_return()
            # Telemetry must not depend on LED ownership, hardware availability,
            # the chosen display, or whether a Decky panel is open.
            self.performance.refresh(self.settings.all()["performance_smoothing"])
            now_monotonic = time.monotonic()
            self._sync_display_power_policy()
            self._service_faceplate_power_retry(now_monotonic)
            if now_monotonic >= max(self._faceplate_next_reconcile, self._faceplate_maintenance_retry_at):
                self._faceplate_next_reconcile = now_monotonic + 1.0
                try:
                    self._consume_faceplate_control()
                    probe = getattr(self.faceplate, 'device_status', None)
                    faceplate_presence = probe() if callable(probe) else self.faceplate.status()
                    self._faceplate_extension_present = bool(faceplate_presence.get('available'))
                    if not self._faceplate_extension_present:
                        # A new physical session must confirm its own original.
                        self._faceplate_extension_source = None
                        self._faceplate_extension_delivery_basis = None
                    self._sync_display_power_policy(faceplate_presence)
                    self._service_faceplate_power_retry(now_monotonic)
                    if self.assistant.active and not faceplate_presence.get("available"):
                        self._assistant_detach_visuals("usb-disconnected", matrix=True, bar=False)
                    self._reconcile_faceplate("periodic", hardware=faceplate_presence)
                except Exception as error:
                    self._record_runtime_fault('faceplate-maintenance', error)
                    self._faceplate_maintenance_retry_at = time.monotonic() + 2.0
            thermal_active = self.thermal_protection.update(
                self.performance.sample, now=time.monotonic(),
            )
            if thermal_active:
                self.assistant.cancel("thermal-protection")
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
                    if (self._display_preset_preview_until
                            and now >= self._display_preset_preview_until):
                        if self._display_preset_preview == 'signals':
                            self.controllers.stop_preview(self._display_preset_preview_owner or 'legacy-setup')
                        self._display_preset_preview_until = 0.0
                    preview_owner = self._display_preset_preview_owner or 'legacy-setup'
                    preview_preset = (
                        self._display_preset_preview
                        if now < self._display_preset_preview_until else ""
                    )
                    preview_started_at = self._display_preset_preview_started_at
                    preview_duration = max(
                        0.0,
                        self._display_preset_preview_until - preview_started_at,
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
                guided_preview = (
                    immersive_preview_output(
                        now - preview_started_at, preview_duration,
                    )
                    if preview_preset == "immersive" else None
                )
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
                if preview_preset == 'atmosphere' and not game.running and weather_base.frame is None:
                    # First setup has no city yet. Demonstrate its Slow Prism
                    # fallback without opening an audio capture just for setup.
                    guided_preview = ProviderOutput('audio-sync:slow-prism-demo',
                        synthetic_slow_prism_frame(now - preview_started_at),
                        'Guided Atmosphere fallback preview')
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
                # Diagnostic metadata only, sampled from this existing LED loop.
                # Never retain the free-form native/Steam reason string.
                self._broker_steam_inputs=dict(policy=ownership_policy,download_lease=bool(explicit),
                    native_effect=bool(native_priority_kind),guard_hard_priority=bool(guard.hard_priority),
                    guard_reason={'startup settle':'startup-settle','repeated native LED activity':'repeated-led-activity',
                        'external LED change detected':'external-led-change'}.get(guard.hard_reason,'other'))
                self._broker_steam_inputs_at=now
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
                    and guided_preview is None
                )
                activation_reason = self.screen_sync_activation.resolve(
                    game_route=game_screen_sync,
                    screensaver_enabled=values["screen_sync_screensaver_enabled"],
                    enabled=values["signalbar_enabled"],
                )
                screen_sync_requested = bool(activation_reason)
                screensaver_extension_requested=bool(
                    values.get('screensaver_light_bar_mode')=='faceplate_extension'
                    and values['signalbar_enabled'] and self._faceplate_extension_present
                    and self.screen_sync_activation.status()['screensaver_active']
                    and guided_preview is None)
                atmosphere_weather_fallback = bool(
                    values.get("display_preset") == "atmosphere"
                    and not game.running
                    and current_display == "weather"
                    and weather_base.frame is None
                )
                audio_sync_route = bool(
                    values["mode"] == "audio_sync" and current_display == "audio_sync"
                    or atmosphere_weather_fallback
                ) and guided_preview is None
                # A Steam screensaver request is a hard mode handoff. Stop the
                # audio reader as well as its LED output so Screen Sync owns the
                # complete visual path until Steam dismisses the screensaver.
                audio_sync_requested = bool(
                    (audio_sync_route or self.audio_sync.previewing)
                    and not (screen_sync_requested or screensaver_extension_requested)
                )
                if self.assistant.holds_bar:
                    if signal_critical or steam_priority:
                        self._assistant_detach_visuals("steam-priority", matrix=False, bar=True)
                    else:
                        screen_sync_requested = False
                        screensaver_extension_requested = False
                        audio_sync_requested = False
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
                self._trace_screen_sync_route(activation_reason, screen_sync_active,
                    requested=screen_sync_requested or audio_screen_capture, recording=recording,
                    stripmine_active=stripmine_active, steam_priority=steam_priority,
                    signal_critical=signal_critical, ownership_allowed=ownership_allowed,
                    assistant_holds_bar=self.assistant.holds_bar)
                screen_sync_base = self.screen_sync.output(values)
                audio_sync_active = self._audio_sync_should_run(
                    values, audio_sync_requested, signal_critical, ownership_allowed,
                    stripmine_active, steam_priority, tw3_steamrgb_active, recording,
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
                if guided_preview is not None:
                    if guided_preview.provider.startswith("audio-sync"):
                        audio_sync_base = guided_preview
                    else:
                        screen_sync_base = guided_preview
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
                    with self._lock:
                        # Closing setup may race this already-sampled render
                        # tick. Never restart its demo after that cancellation.
                        if (self._display_preset_preview == preview_preset
                                and self._display_preset_preview_started_at == preview_started_at
                                and time.monotonic() < self._display_preset_preview_until):
                            self.controllers.preview(
                                "duo", values, values.get("controller_duo_variant", "double-welcome"),
                                count=2, target=1, owner=preview_owner,
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
                assistant_base = self.assistant.output(now)
                extension_base = self._faceplate_extension_output(values, game, current_display, now,
                    screensaver=screensaver_extension_requested)
                if assistant_base is not None:
                    interval = .05
                effective_mode = (
                    "audio_sync" if guided_preview is not None
                    and guided_preview.provider.startswith("audio-sync")
                    else "screen_sync" if guided_preview is not None
                    else "screen_sync" if screen_sync_requested
                    else "faceplate_extension" if screensaver_extension_requested
                    else "audio_sync" if audio_sync_requested
                    else values["mode"]
                )
                if self._display_bar_off(values):
                    effective_mode = 'bar_off'
                elif values.get('steam_control_enabled'):
                    effective_mode = 'steam_control'
                decision = self.arbiter.choose(
                    faceplate_extension=extension_base,
                    assistant_base=assistant_base,
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

                stripmine_priority = 'signalbar' if effective_mode == 'bar_off' else self._stripmine_priority(decision.provider, values)
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
                            (ownership_policy != "cooperative" or effective_mode == 'bar_off')
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
                    # Explicit native control is a requested handoff, not an
                    # observed takeover. Restore Steam's saved mode/frame only
                    # if our verified signature is still physically present.
                    externally_blocked = decision.provider == "valve" and effective_mode != 'steam_control'
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
                    if (preview_preset and self._display_preset_preview == preview_preset
                            and self._display_preset_preview_started_at == preview_started_at):
                        self._display_preset_preview_on_bar = bool(owner == 'GabeCubeAura' and renderer.last_frame)
                        self._display_preset_preview_colors = (
                            [list(pixel) for pixel in renderer.last_frame]
                            if self._display_preset_preview_on_bar else [])
                    self._suspension_reason = suspension
                    self._error = ""
                    self._decision_at = time.monotonic()
                delivery = (activation_reason, self._decision, self._owner, screen_sync_fallback_active)
                if delivery != self._screen_sync_trace_delivery:
                    self._screen_sync_trace_delivery = delivery
                    if activation_reason or screen_sync_active:
                        self.screen_sync_trace.record("capture-display-decision", reason=activation_reason,
                            provider=self._decision, owner=self._owner,
                            fallback=screen_sync_fallback_active)
            except Exception as error:
                self._record_runtime_fault('bar-render', error)
                self.screen_sync.set_active(False)
                self.audio_sync.set_active(False)
                self._assistant_detach_visuals('bar-render-fault', matrix=False, bar=True)
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

    def led_preview(self, channels):
        """Small colour-only read: no device probe, capture, render or persistence."""
        allowed = {'output', 'weather', 'customization', 'events', 'controllers',
                   'countdown', 'screen_sync', 'audio_sync', 'launch_artwork',
                   'performance', 'artwork'}
        requested = set(channels[:11]) & allowed if isinstance(channels, list) and all(
            isinstance(channel, str) for channel in channels) else set()
        if not requested:
            return {}
        values = self.settings.all()
        with self._lock:
            game = self._game
            renderer = self._renderer
            output = (renderer.last_frame if renderer and self._owner == 'GabeCubeAura'
                      and values['signalbar_enabled']
                      and time.monotonic() - self._decision_at < .5 else None)
        result = {}
        for channel in requested:
            if channel == 'output':
                frame = output
            elif channel == 'weather':
                frame = self.weather.preview_frame(values)
            elif channel == 'customization':
                frame = self.customization.output(values, enabled=True).frame
            elif channel in {'screen_sync', 'audio_sync'}:
                # Copy the latest processed colours; status() also gathers
                # capture diagnostics, which do not belong in this fast path.
                frame = getattr(self, channel)._frame
            elif channel == 'events':
                frame = self.events.output().frame
            elif channel == 'controllers':
                frame = self.controllers.status(values, game.running)['colors']
            elif channel == 'countdown':
                frame = self.countdown.status(
                    colour=values['countdown_colour'],
                    full_bar_seconds=values['countdown_full_bar_minutes'] * 60,
                    allow_parental=bool(values['parental_countdown_enabled'] and game.running),
                )['colors']
            elif channel == 'launch_artwork':
                frame = self.launch_artwork.status(game.appid)['colors']
            elif channel == 'artwork':
                frame = self.artwork.status(vibrance=self.settings.artwork_for(game.appid)['vibrance']).get('colors')
            else:
                frame = self.performance.frame(
                    metric=values['performance_metric'], cool_c=values['cool_temp_c'],
                    hot_c=values['hot_temp_c'], palette=values['temperature_palette'],
                    direction=values['mixed_direction'], dark_edge_compensation=0,
                    custom_palette=tuple(values[f'temperature_custom_{role}'] for role in ('cool', 'middle', 'hot')),
                )
            result[channel] = [list(pixel) for pixel in frame] if frame else [[0, 0, 0] for _ in range(17)]
        return result

    def status(self):
        values = self.settings.all()
        # Saved preferences must not wait for USB ownership, an assistant reply,
        # suspension or the next render before a dropdown can confirm a choice.
        faceplate_routing = self.faceplate_router.preference_status()
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
            elif screen_sync_status["phase"] in {"error", "waiting"}:
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
            preset_preview_output = (
                immersive_preview_output(
                    now - self._display_preset_preview_started_at,
                    self._display_preset_preview_until - self._display_preset_preview_started_at,
                )
                if preset_preview_active and self._display_preset_preview == "immersive"
                else None
            )
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
                "steam_control_enabled": bool(values.get('steam_control_enabled')),
                "onboarding_completed": values["onboarding_completed"],
                "faceplate_setup_completed": bool(values.get("faceplate_setup_completed")),
                "display_preset": values["display_preset"],
                "display_preset_preview": {
                    "active": preset_preview_active,
                    "preset": self._display_preset_preview if preset_preview_active else "",
                    "remaining_s": max(0.0, self._display_preset_preview_until - now),
                    "owner": self._display_preset_preview_owner if preset_preview_active else '',
                    "on_bar": bool(preset_preview_active and self._display_preset_preview_on_bar),
                    "phase": (
                        "Audio Sync" if preset_preview_output is not None
                        and preset_preview_output.provider.startswith("audio-sync")
                        else "Screen Sync" if preset_preview_output is not None else ""
                    ),
                    "colors": (
                        self._display_preset_preview_colors if preset_preview_active
                        and self._display_preset_preview_colors else
                        [list(pixel) for pixel in preset_preview_output.frame]
                        if preset_preview_output is not None else []
                    ),
                },
                "valve_ownership_policy": values["valve_ownership_policy"],
                "led_output_calibration_mode": values["led_output_calibration_mode"],
                "led_output_calibration": calibration_status,
                "light_bar_day_brightness": values["light_bar_day_brightness"],
                "light_bar_brightness": light_bar_brightness,
                "home_display": values["home_display"],
                "faceplate_extension_mapping": values["faceplate_extension_mapping"],
                "faceplate_extension_saturation": values["faceplate_extension_saturation"],
                "faceplate_extension": self._faceplate_extension_status(),
                "game_display": values["game_display"],
                "current_display": display["selected"],
                "display_power": {"bar_off": self._display_bar_off(values),
                                  "faceplate_off": self._display_panel_off(values)},
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
                "screensaver_light_bar_mode": values['screensaver_light_bar_mode'],
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
                "free_timer_end_action": values['free_timer_end_action'],
                "timer_end_action": self.countdown.end_action.status(),
                "personal_timer": self.countdown.personal_status(),
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
                "faceplate_lab_enabled": values["faceplate_lab_enabled"],
                "faceplate_configuration_error": self._faceplate_configuration_error,
                "lab58_ux_enabled": values["lab58_ux_enabled"],
                "ui_language": values["ui_language"],
                "faceplate_brightness": values["faceplate_brightness"],
                "faceplate_dashboard_show_clock": values.get("faceplate_dashboard_show_clock", False),
                "faceplate_dashboard_clock_choice": values.get("faceplate_dashboard_clock_choice", "default"),
                "faceplate_rotate_180": values["faceplate_rotate_180"],
                "faceplate_artwork_style": values["faceplate_artwork_style"],
                "faceplate_logo_position": values["faceplate_logo_position"],
                "faceplate_artwork_profiles": values["faceplate_artwork_profiles"],
                "faceplate_dashboard_home_appid": values["faceplate_dashboard_home_appid"],
                "faceplate_dashboard_home_source": values["faceplate_dashboard_home_source"],
                "faceplate_dashboard_show_bottom_row": values["faceplate_dashboard_show_bottom_row"],
                "faceplate_dashboard_bottom_mode": values["faceplate_dashboard_bottom_mode"],
                "faceplate_dashboard_battery_style": values["faceplate_dashboard_battery_style"],
                "faceplate_dashboard_show_p2": values["faceplate_dashboard_show_p2"],
                "faceplate_dashboard_clock_format": values["faceplate_dashboard_clock_format"],
                "faceplate_dashboard_show_weather": values["faceplate_dashboard_show_weather"],
                "faceplate_dashboard_clock_position": values["faceplate_dashboard_clock_position"],
                "faceplate_dashboard_game_session": values["faceplate_dashboard_game_session"],
                "faceplate_dashboard_contexts": values['faceplate_dashboard_contexts'],
                "faceplate_player_city_row": values["faceplate_player_city_row"],
                "faceplate_player_city_dashboard_row": values["faceplate_player_city_dashboard_row"],
                "faceplate_player_city_battery_style": values["faceplate_player_city_battery_style"],
                "faceplate_playtime_enabled": values["faceplate_playtime_enabled"],
                "faceplate_artwork_dashboard_refresh": values["faceplate_artwork_dashboard_refresh"],
                "faceplate_power_mode": values["faceplate_power_mode"],
                "faceplate": {
                    **self.faceplate.status(),
                    "home_artwork_prepared": getattr(self, '_faceplate_home_artwork_prepared', False),
                    "automation": self.faceplate_worker.status(),
                    "routing": faceplate_routing,
                    "player_city": self._player_city_status(),
                    "steam_status": self.faceplate_steam_state.snapshot().as_dict(),
                    "power_recovery": {
                        **self._faceplate_power_status,
                        "suspended": self._faceplate_suspended,
                        "retry_pending": self._faceplate_power_target is not None,
                        'route_state': getattr(self, '_faceplate_route_recovery', {}).get('state', 'idle'),
                        'route_attempts': getattr(self, '_faceplate_route_recovery', {}).get('attempts', 0),
                    },
                },
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
