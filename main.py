"""Decky backend entry point for GabeCubeAura."""

import asyncio
import os
from pathlib import Path
import shutil
import sys

import decky

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(PLUGIN_DIR, "py_modules"))

from signalbar.backend import Engine  # noqa: E402
from signalbar.faceplate import FaceplateService, PowerEvents  # noqa: E402
from signalbar.faceplate import options as faceplate_options  # noqa: E402
from signalbar import faceplate_claim  # noqa: E402
from signalbar.settings import SettingsStore  # noqa: E402
from signalbar.settings.export import (  # noqa: E402
    configuration_export_path, read_configuration_import, write_configuration_export,
)
from signalbar.steam import get_library_artwork  # noqa: E402
from signalbar.providers.weather import search_cities  # noqa: E402
from signalbar import __version__  # noqa: E402
from signalbar.updates import UpdateManager  # noqa: E402


class Plugin:
    # Set in _main; None until then (and in tests that build a bare Plugin).
    faceplate = None
    faceplate_power = None
    faceplate_settings_dir = None

    @staticmethod
    def _migrate_legacy_settings(settings_directory: str):
        """Copy legacy settings once when GabeCubeAura is installed as a new plugin."""
        current = Path(settings_directory)
        current.mkdir(parents=True, exist_ok=True)
        if (current / "config.json").exists():
            return ""
        # Decky gives each product name its own settings directory. Import the
        # former public SignalBar installation when GabeCubeAura starts empty.
        for legacy_name in ("SignalBar", "signalbar"):
            legacy = current.parent / legacy_name
            source = legacy / "config.json"
            if legacy == current or not source.is_file():
                continue
            for filename in ("config.json", "artwork-cache.json", "launch-artwork-cache.json"):
                candidate = legacy / filename
                if candidate.is_file() and not (current / filename).exists():
                    shutil.copy2(candidate, current / filename)
            return legacy_name
        return ""

    async def _main(self):
        migrated_from = self._migrate_legacy_settings(decky.DECKY_PLUGIN_SETTINGS_DIR)
        settings_path = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "config.json")
        cache_path = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "artwork-cache.json")
        self.engine = Engine(SettingsStore(settings_path), cache_path, decky.logger)
        self.configuration_export_path = configuration_export_path(
            decky.DECKY_PLUGIN_SETTINGS_DIR,
            os.environ.get("DECKY_USER_HOME"),
        )
        self.engine.start()
        self.update_manager = UpdateManager(
            __version__, self.engine.settings,
            decky.DECKY_PLUGIN_RUNTIME_DIR,
            decky.DECKY_PLUGIN_DIR,
            decky.logger,
        )
        self.update_manager.start()
        # The faceplate is optional hardware: a failure here must never stop
        # the light bar or the updater.
        try:
            self.faceplate = FaceplateService(
                faceplate_options.unprefixed(self.engine.settings.all()), decky.logger,
                counter_path=os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "faceplate-writes.json"),
            )
            self.faceplate_settings_dir = decky.DECKY_PLUGIN_SETTINGS_DIR
            self.faceplate.start()
            self._sync_faceplate()
        except Exception as error:  # noqa: BLE001
            decky.logger.warning(f"[GabeCubeAura] faceplate support unavailable: {error}")
            self.faceplate = None
        if migrated_from:
            decky.logger.info(f"[GabeCubeAura] imported legacy {migrated_from} settings")
        decky.logger.info("[GabeCubeAura] loaded")

    def _sync_faceplate(self):
        """Hand the faceplate its current settings after anything may have changed them."""
        if self.faceplate is None:
            return
        values = faceplate_options.unprefixed(self.engine.settings.all())
        self.faceplate.configure(values)
        # The sleep/shutdown hook holds a logind delay lock, so it only runs
        # while the faceplate is in use, never for light-bar-only setups.
        if values["mode"] != "off" and self.faceplate_power is None:
            self.faceplate_power = PowerEvents(self.faceplate.power_event, decky.logger)
            self.faceplate_power.start()
        elif values["mode"] == "off" and self.faceplate_power is not None:
            self.faceplate_power.stop()
            self.faceplate_power = None
        if self.faceplate_settings_dir:
            if values["mode"] != "off":
                faceplate_claim.claim(self.faceplate_settings_dir)
            else:
                faceplate_claim.release(self.faceplate_settings_dir)

    def _stop_faceplate(self):
        if self.faceplate is None:
            return
        if self.faceplate_power is not None:
            self.faceplate_power.stop()
            self.faceplate_power = None
        if self.faceplate_settings_dir:
            faceplate_claim.release(self.faceplate_settings_dir)
        self.faceplate.stop()

    async def _unload(self):
        self.update_manager.stop()
        self._stop_faceplate()
        self.engine.stop()
        decky.logger.info("[GabeCubeAura] unloaded; LED ownership released")

    async def _uninstall(self):
        self.update_manager.stop()
        self._stop_faceplate()
        self.engine.stop()

    async def get_status(self):
        return self.engine.status()

    async def export_configuration(self):
        status = self.engine.status()
        return write_configuration_export(
            self.engine.settings,
            self.configuration_export_path,
            status["version"],
            status["game"],
        )

    async def import_configuration(self, path: str):
        global_values, display_profiles, artwork_profiles, launch_artwork_profiles = read_configuration_import(path)
        self.engine.import_configuration(
            global_values, display_profiles, artwork_profiles, launch_artwork_profiles,
        )
        self._sync_faceplate()
        return self.engine.status()

    async def reset_configuration(self):
        self.engine.reset_configuration()
        self._sync_faceplate()
        return self.engine.status()

    async def set_mode(self, mode: str):
        self.engine.update_settings({"mode": mode})
        return self.engine.status()

    async def set_game_display(self, appid: int, mode: str):
        self.engine.update_display(appid, mode)
        return self.engine.status()

    async def set_setting(self, key: str, value):
        self.engine.update_settings({key: value})
        if key.startswith(faceplate_options.PREFIX) or key == "reverse_led_order":
            self._sync_faceplate()
        return self.engine.status()

    async def set_artwork_setting(self, appid: int, key: str, value):
        changes = {}
        if key == "mode":
            changes["mode"] = value
        elif key == "manual_y":
            changes["manual_y"] = value
        elif key == "source":
            changes["source"] = value
        elif key == "vibrance":
            changes["vibrance"] = value
        self.engine.update_artwork_settings(appid, changes)
        return self.engine.status()

    async def set_launch_artwork_setting(self, appid: int, key: str, value):
        changes = {}
        if key == "palette_mode":
            changes["palette_mode"] = value
        elif key == "custom_palettes":
            changes["custom_palettes"] = value
        self.engine.update_launch_artwork_settings(appid, changes)
        return self.engine.status()

    async def game_changed(self, appid: int = 0, title: str = "", launch: bool = False,
                           source: str = ""):
        self.engine.set_game(appid, title, launch, source)
        if self.faceplate is not None:
            try:
                current = max(0, int(appid))
            except (TypeError, ValueError):
                current = 0
            self.faceplate.game_event(current, bool(current))
        return self.engine.status()

    def _require_faceplate(self):
        if self.faceplate is None:
            raise RuntimeError("Faceplate support is not running")
        return self.faceplate

    async def get_faceplate_status(self):
        return self._require_faceplate().status()

    async def set_faceplate_setting(self, key: str, value):
        self._require_faceplate()
        cleaned = faceplate_options.clean(key, value)
        self.engine.update_settings({faceplate_options.PREFIX + key: cleaned})
        self._sync_faceplate()
        return self.faceplate.status()

    async def set_faceplate_game_settings(self, appid: int, changes: dict = None):
        """One game's own art style and logo position; None returns it to the global choice."""
        self._require_faceplate()
        if int(appid) <= 0:
            raise ValueError("A game profile needs a game")
        key = str(int(appid))
        values = faceplate_options.unprefixed(self.engine.settings.all())
        profiles = dict(values["game_profiles"])
        if changes is None:
            profiles.pop(key, None)
        else:
            # A new profile starts as a copy of the global choice, so turning
            # it on does not change the picture until something is edited.
            base = profiles.get(key) or {name: values[name] for name in faceplate_options.GAME_KEYS}
            profiles[key] = faceplate_options.game_profile(dict(base, **changes))
        self.engine.update_settings({faceplate_options.PREFIX + "game_profiles": profiles})
        self._sync_faceplate()
        return self.faceplate.status()

    async def get_artwork(self, appid: int = 0, source: str = "hero", purpose: str = "artwork"):
        result = get_library_artwork(appid, source)
        if result.get("found"):
            prepare = (
                self.engine.prepare_launch_artwork
                if purpose == "launch" else self.engine.prepare_artwork
            )
            result["cached"] = prepare(
                result["appid"], result["fingerprint"], result["filename"], result["source"]
            )
        return result

    async def submit_artwork(self, appid: int, fingerprint: str, colors, sample_y: float,
                             dominant_palettes, filename: str = "", source: str = "hero",
                             purpose: str = "artwork"):
        submit = (
            self.engine.submit_launch_artwork
            if purpose == "launch" else self.engine.submit_artwork
        )
        submit(appid, fingerprint, colors, sample_y, dominant_palettes, filename, source)
        return self.engine.status()

    async def preview_launch_artwork(self):
        return self.engine.preview_launch_artwork()

    async def preview_customization(self):
        return self.engine.preview_customization()

    async def preview_light_calibration(self):
        self.engine.preview_light_calibration()
        return self.engine.status()

    async def preview_light_brightness(self, mode: str = "day"):
        self.engine.preview_light_brightness(mode)
        return self.engine.status()

    async def set_light_bar_brightness(self, key: str, value, mode: str = "day"):
        if key not in {"light_bar_day_brightness", "night_mode_brightness"}:
            raise ValueError("Unsupported light bar brightness setting")
        self.engine.update_settings({key: value})
        self.engine.preview_light_brightness(mode)
        return self.engine.status()

    async def preview_display_preset(self, preset: str):
        self.engine.preview_display_preset(preset, 10.0)
        return self.engine.status()

    async def set_steam_activity(self, active: bool, reason: str = "Steam event"):
        return self.engine.set_steam_activity(active, reason)

    async def set_screen_sync_context(self, context: str, active: bool,
                                      state: str = "available", detail: str = ""):
        return self.engine.set_screen_sync_context(context, active, state, detail)

    async def preview_screen_sync(self):
        self.engine.preview_screen_sync(15.0)
        return self.engine.status()

    async def preview_audio_sync(self):
        self.engine.preview_audio_sync(15.0)
        return self.engine.status()

    async def report_runtime_diagnostic(self, event: str, appid: int = 0,
                                        source: str = "", duration_ms: float = -1):
        self.engine.report_runtime_diagnostic(event, appid, source, duration_ms)
        return True

    async def report_parental_minutes(self, minutes: float):
        self.engine.report_parental_minutes(minutes)
        return self.engine.status()

    async def start_free_timer(self, minutes: int):
        self.engine.start_free_timer(minutes)
        return self.engine.status()

    async def stop_free_timer(self):
        self.engine.stop_free_timer()
        return self.engine.status()

    async def preview_countdown(self):
        self.engine.preview_countdown()
        return self.engine.status()

    async def trigger_event(self, kind: str, preview: bool = False, variant: str = ""):
        return self.engine.trigger_event(kind, preview, variant)

    async def update_controllers(self, controllers, source: str = "Steam callback"):
        self.engine.update_controllers(controllers, source)
        return True

    async def reset_controllers(self):
        self.engine.reset_controllers()
        return True

    async def report_controller_telemetry(self, state):
        self.engine.report_controller_telemetry(state)
        return True

    async def preview_controller(self, kind: str, variant: str = "", count: int = 1, target: int = 0):
        return self.engine.preview_controller(kind, variant, count, target)

    async def search_weather_cities(self, query: str):
        try:
            cities = await asyncio.get_running_loop().run_in_executor(None, search_cities, query)
            return {"results": cities, "error": ""}
        except Exception as error:
            decky.logger.warning(f"[GabeCubeAura] city search failed: {type(error).__name__}: {error}")
            return {"results": [], "error": f"{type(error).__name__}: {error}"[:180]}

    async def preview_weather(self, condition: str, variant: int):
        return self.engine.preview_weather(condition, variant)

    async def stop_weather_preview(self):
        return self.engine.stop_weather_preview()

    async def get_update_status(self):
        return self.update_manager.status()

    async def check_for_updates(self):
        return await asyncio.get_running_loop().run_in_executor(
            None, self.update_manager.check, True,
        )

    async def prepare_update(self):
        return await asyncio.get_running_loop().run_in_executor(None, self.update_manager.prepare)

    async def install_prepared_update(self, confirmation_token: str):
        return self.update_manager.install(confirmation_token)

    async def set_update_preferences(self, auto_check: bool, notifications: bool,
                                     check_interval_minutes: int = 1440,
                                     channel: str = "stable"):
        return await asyncio.get_running_loop().run_in_executor(
            None,
            self.update_manager.set_preferences,
            auto_check,
            notifications,
            check_interval_minutes,
            channel,
        )

    async def start_private_update_authorization(self):
        return await asyncio.get_running_loop().run_in_executor(
            None, self.update_manager.start_private_authorization,
        )

    async def poll_private_update_authorization(self):
        return await asyncio.get_running_loop().run_in_executor(
            None, self.update_manager.poll_private_authorization,
        )

    async def disconnect_private_update_authorization(self):
        return await asyncio.get_running_loop().run_in_executor(
            None, self.update_manager.disconnect_private_authorization,
        )

    async def acknowledge_update_notification(self, version: str):
        return self.update_manager.acknowledge_notification(version)

    async def dismiss_update_error(self):
        return self.update_manager.dismiss_error()

    async def run_update_lab_scenario(self, scenario: str):
        return await asyncio.get_running_loop().run_in_executor(
            None, self.update_manager.run_lab, scenario,
        )

    async def export_update_test_report(self):
        user_home = os.environ.get("DECKY_USER_HOME", "")
        if user_home:
            destination = os.path.join(user_home, "Documents", "GabeCubeAura-update-test-report.json")
        else:
            destination = os.path.join(
                decky.DECKY_PLUGIN_RUNTIME_DIR, "GabeCubeAura-update-test-report.json",
            )
        return self.update_manager.export_lab_report(destination)
