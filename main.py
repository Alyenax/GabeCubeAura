"""Decky backend entry point for GabeCubeAura."""

import asyncio
import base64
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time
import secrets

import decky

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(PLUGIN_DIR, "py_modules"))

from signalbar.backend import Engine  # noqa: E402
from signalbar.shutdown import ShutdownBudget
from signalbar.settings import SettingsStore  # noqa: E402
from signalbar.settings.export import (  # noqa: E402
    configuration_export_path, read_configuration_import, write_configuration_export,
    build_configuration_export, write_configuration_payload,
)
from signalbar.steam import get_library_artwork  # noqa: E402
from signalbar.steam.quick_preview import get_quick_artwork, quick_preview_diagnostic  # noqa: E402
from signalbar.providers.weather import search_cities  # noqa: E402
from signalbar.pixel_studio import PixelStudioManager  # noqa: E402
from signalbar.diagnostics import DiagnosticJournal  # noqa: E402
from signalbar.screen_sync_trace import ScreenSyncTrace  # noqa: E402
from signalbar.faceplate.power_events import PowerEvents  # noqa: E402
from signalbar import faceplate_claim  # noqa: E402
from signalbar.faceplate.artwork_jobs import ArtworkPreparationJobs  # noqa: E402
from signalbar.faceplate.library import installed_games  # noqa: E402
from signalbar.faceplate.steamgriddb import SteamGridDBError  # noqa: E402
from signalbar.faceplate import (  # noqa: E402
    FaceplatePreferencesStore, FaceplateRevisionConflict,
)
from signalbar import __version__  # noqa: E402
from signalbar.distribution import supports_private_tools  # noqa: E402
from signalbar.updates import UpdateManager  # noqa: E402
from signalbar.jsaux_broker import Broker, BrokerServer  # noqa: E402
from signalbar.faceplate.broker_adapter import FaceplateBrokerAdapter  # noqa: E402
from signalbar.jsaux_broker.server import CANONICAL_RUNTIME, provision_runtime
from signalbar.onboarding import OnboardingDraft, OnboardingTransaction, clean_draft, draft_error_code

PERSISTED_RUNTIME_EVENTS = {
    "frontend_mounted", "frontend_unmounted", "game_synced", "game_retained",
    "parental_received", "steam_led_override",
    "quick_panel_ui",
}


PERSISTENT_JSAUX_CONTENT = Path('/var/lib/gabecubeaura-jsaux')

class Plugin:
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
        user_home = os.environ.get("DECKY_USER_HOME", "/home/deck")
        self.diagnostics = DiagnosticJournal(
            Path(user_home) / ".local/state/gabecubeaura",
            __version__, decky.logger,
        )
        self.diagnostics.begin_session()
        migrated_from = self._migrate_legacy_settings(decky.DECKY_PLUGIN_SETTINGS_DIR)
        settings_path = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "config.json")
        cache_path = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "artwork-cache.json")
        settings = SettingsStore(settings_path, first_install_defaults=True)
        faceplate_preferences = FaceplatePreferencesStore()
        self.onboarding_draft = OnboardingDraft(Path(decky.DECKY_PLUGIN_SETTINGS_DIR) / 'setup-draft.json')
        self.onboarding_transaction = OnboardingTransaction(Path(decky.DECKY_PLUGIN_SETTINGS_DIR) / 'setup-transaction.json')
        self._onboarding_commit_lock = threading.RLock()
        self._onboarding_recovery_error = ''
        try:
            recovered = self.onboarding_transaction.recover(settings, faceplate_preferences)
        except (OSError, ValueError, TypeError, RecursionError) as error:
            # Keep all evidence. Runtime capture/display stays blocked until
            # recovery is possible; never start with a half-applied setup.
            self._onboarding_recovery_error = type(error).__name__
            recovered = None
        if recovered == 'committed':
            try:
                self.onboarding_draft.discard()
            except (OSError, ValueError):
                decky.logger.warning('[GabeCubeAura] Committed setup draft cleanup deferred')
        self.engine = Engine(
            settings, cache_path, decky.logger,
            faceplate_preferences=faceplate_preferences,
            screen_sync_trace=ScreenSyncTrace(self.diagnostics.state_dir),
            faceplate_runtime_path=Path(
                user_home
            ) / ".local/state/gabecubeaura/faceplate-runtime.json",
        )
        self.engine._onboarding_recovery_blocked = bool(self._onboarding_recovery_error)
        self.engine.assistant.start_server()
        self.configuration_export_path = configuration_export_path(
            decky.DECKY_PLUGIN_SETTINGS_DIR,
            os.environ.get("DECKY_USER_HOME"),
        )
        # Broker callbacks attach before the existing worker/engine starts.
        self.jsaux_broker = self.jsaux_broker_server = None
        self._jsaux_broker_error = ''
        self._jsaux_broker_stage = 'not-started'
        self._jsaux_broker_errno = None
        self._jsaux_broker_retry_at = 0.
        self._jsaux_broker_start_lock = threading.Lock()
        runtime_root = CANONICAL_RUNTIME
        self.engine.jsaux_broker_adapter = FaceplateBrokerAdapter(
            self.engine, ownership_root=runtime_root / 'ownership',
        )
        await asyncio.get_running_loop().run_in_executor(None, self._start_jsaux_broker)
        self._jsaux_recovery_task = asyncio.create_task(self._recover_jsaux_startup())
        self.faceplate_settings_dir = decky.DECKY_PLUGIN_SETTINGS_DIR
        self._sync_faceplate_claim()
        try:
            self.engine.start()
        except Exception:
            faceplate_claim.release(self.faceplate_settings_dir)
            raise
        self.faceplate_power_events = PowerEvents(
            self._handle_faceplate_power_event, decky.logger,
        )
        self.update_manager = UpdateManager(
            __version__, self.engine.settings,
            decky.DECKY_PLUGIN_RUNTIME_DIR,
            decky.DECKY_PLUGIN_DIR,
            decky.logger,
        )
        self.pixel_studio = PixelStudioManager(
            decky.DECKY_PLUGIN_DIR,
            user_home,
            __version__,
            decky.logger,
        )
        # Pixel Studio is Decky-native now. Remove the retired Desktop entry
        # and stop only an exact matching legacy loopback service.
        self.pixel_studio.disable_standalone()
        self.faceplate_artwork_jobs = ArtworkPreparationJobs(
            self.engine.faceplate.steamgriddb,
            self.engine.faceplate_game_snapshot,
            decky.logger,
        )
        self.cinema = self.cinema_installer = self.cinema_preview = self.cinema_tools = None
        self.studio = self.studio_installer = self.studio_preview = None
        # Studio moved to Decky-Animated-Screensaver. Do not open/migrate/scan its
        # former library, spawn media workers, load codecs or inspect Steam export
        # files during plugin startup. Old RPC names only provide a retired-state
        # response to a frontend surviving an update; no service is constructed.
        self._cinema_error = ('Animated Screensaver Studio moved to Decky-Animated-Screensaver. '
                              'Existing files and Steam installations were preserved.')
        self._cinema_tools_path = ''
        self._cinema_scanned = False
        self._cinema_install_error = ''
        self._cinema_installation = None
        self._cinema_bridge_token = ''
        self.pixel_studio.set_current_game(self.engine.faceplate_game_snapshot())
        self._configure_faceplate_power_events()
        self.update_manager.start()
        self._integration_loop = asyncio.get_running_loop()
        self.engine.assistant.actions.send = self._timer_steam_action
        self._diagnostic_upload_task = None
        self._diagnostic_upload_lock=asyncio.Lock()
        self.automatic_incidents = None
        if migrated_from:
            decky.logger.info(f"[GabeCubeAura] imported legacy {migrated_from} settings")
        decky.logger.info("[GabeCubeAura] loaded")

    async def _unload(self):
        await self._shutdown_plugin()

    async def _shutdown_plugin(self):
        self._gabe_unloading = True
        automatic=getattr(self,'automatic_incidents',None)
        if automatic:await automatic.close()
        timer = getattr(self, "_gabe_report_timer", None)
        if timer: timer.cancel()
        task = getattr(self, '_diagnostic_upload_task', None)
        if task: task.cancel()
        recovery = getattr(self, '_jsaux_recovery_task', None)
        if recovery: recovery.cancel()
        # Decky v3.2.10 kills a plugin still alive five seconds after SIGTERM.
        # Share 3s of join waits instead of adding every component's timeout;
        # retain headroom for cancellation, device release and final state I/O.
        def cleanup():
            budget = ShutdownBudget(3.0)
            self.engine._stop.set()
            self.engine.countdown.end_action.cancel('plugin-stopped')
            operations = (
                ('artwork', self.faceplate_artwork_jobs.cancel, False),
                ('studio', self._stop_cinema, True),
                ('power-events', self.faceplate_power_events.stop, True),
                ('updates', self.update_manager.stop, True),
                ('engine', self.engine.stop, True),
                ('claim', self._sync_faceplate_claim, False),
            )
            failed = False
            for name, callback, bounded in operations:
                started = time.monotonic()
                try:
                    budget.call(callback) if bounded else callback()
                except Exception as error:
                    failed = True
                    decky.logger.warning(f'[GabeCubeAura] shutdown {name}: {type(error).__name__}')
                finally:
                    decky.logger.info(f'[GabeCubeAura] shutdown {name}: {time.monotonic()-started:.3f}s')
            if not failed:
                self.diagnostics.finish_session()
                decky.logger.info("[GabeCubeAura] unloaded; LED ownership released")
        await asyncio.get_running_loop().run_in_executor(None, cleanup)

    async def _uninstall(self):
        await self._shutdown_plugin()
        self.pixel_studio.uninstall()

    async def get_status(self):
        # Status gathers several providers and optional filesystem snapshots.
        # Keep that synchronous work off Decky's asyncio thread so one slow
        # device probe cannot freeze every settings tab.
        return await asyncio.get_running_loop().run_in_executor(
            None, self.engine.status,
        )

    async def get_led_preview(self, channels):
        return await asyncio.get_running_loop().run_in_executor(
            None, self.engine.led_preview, channels,
        )

    def _onboarding_event(self, operation, code):
        # No draft text, city, path or exception message in the private journal.
        try:
            journal = getattr(self, 'diagnostics', None)
            if journal: journal.record('onboarding_draft', operation=operation, code=code)
        except Exception:
            pass  # Diagnostic failure cannot prevent recovery.

    async def get_onboarding(self):
        def snapshot():
            presence = self.engine.faceplate.device_status()
            draft = self.onboarding_draft.resume()
            draft_error = ''
            code = self.onboarding_draft.storage_error or self.onboarding_draft.recovery_code
            if code != getattr(self, '_onboarding_draft_last_code', ''):
                self._onboarding_draft_last_code = code
                self._onboarding_event('read', code or 'ready')
            return {'draft': draft, 'draft_error': draft_error, 'draft_error_code': '',
                    'draft_storage': 'memory' if self.onboarding_draft.storage_error else 'disk',
                    'bar_detected': bool(self.engine._available),
                    'faceplate_detected': bool(presence.get('available')),
                    'faceplate_busy': bool(presence.get('busy')),
                    'recovery_error': getattr(self, '_onboarding_recovery_error', '')}
        return await asyncio.get_running_loop().run_in_executor(None, snapshot)

    async def save_onboarding_draft(self, changes: dict):
        return await asyncio.get_running_loop().run_in_executor(None, self.onboarding_draft.remember, changes)

    async def reset_onboarding_draft(self):
        self._onboarding_event('archive', 'started')
        try:
            await asyncio.get_running_loop().run_in_executor(None, self.onboarding_draft.restart)
        except (OSError, ValueError) as error:
            code = draft_error_code(error)
            self._onboarding_event('archive', code)
            state = await self.get_onboarding()
            return dict(state, draft_reset_error=code)
        state = await self.get_onboarding()
        self._onboarding_event('archive', state.get('draft_error_code') or 'ready')
        return state

    async def complete_onboarding(self, choices: dict):
        transaction_prepared = False
        def complete():
            if not self._onboarding_commit_lock.acquire(blocking=False):
                raise ValueError('Setup is already being applied')
            try:
                return self._call_with_faceplate_claim_sync(apply_complete)
            finally:
                self._onboarding_commit_lock.release()
        def persist_complete():
            nonlocal transaction_prepared
            if getattr(self, '_onboarding_recovery_error', ''):
                raise ValueError('Complete local setup recovery before applying new choices')
            self.onboarding_draft.resume()  # Progress storage cannot veto validated choices.
            selected = clean_draft(choices)
            changes = {'onboarding_completed': True}
            if self.engine._available:
                for source, target in (('preset', 'display_preset'), ('brightness', 'light_bar_day_brightness'),
                                       ('night_percentage', 'night_mode_brightness')):
                    if source in selected: changes[target] = selected[source]
                if 'night' in selected:
                    changes['night_mode_enabled'] = bool(selected['night'] and selected.get('city'))
            if selected.get('city'):
                changes['weather_location'] = selected['city']
            # Voice belongs to DVA. Legacy draft consent is accepted for recovery
            # compatibility but must never rewrite importable GCA voice preferences.
            presence = device_status
            requested = selected.get('faceplate_requested')
            previous_routes = self.engine.faceplate_preferences.read()
            if requested is True and not presence.get('available'):
                # Keep the setup intent, but never activate a now-absent device.
                requested = None
            if requested is True:
                changes['faceplate_lab_enabled'] = True
                # Setup always starts Home on Dashboard Weather, even for legacy drafts.
                changes['faceplate_dashboard_home_source'] = 'weather'
            elif requested is False:
                changes['faceplate_lab_enabled'] = False
            if type(requested) is bool and presence.get('available'):
                changes['faceplate_setup_completed'] = True
            old_routes = {'home': previous_routes.home_scene, 'game': previous_routes.game_scene}
            new_routes = dict(old_routes)
            if requested is True:
                new_routes = {'home': 'dashboard',
                    'game': old_routes['game'] if selected.get('game') == 'keep' else selected.get('game', old_routes['game'])}
            before_fields, after_fields = self.engine.settings.plan_update(changes)
            self.onboarding_transaction.prepare(before_fields, after_fields, old_routes, new_routes)
            transaction_prepared = True
            if requested is True:
                self.engine.faceplate_preferences.update(
                    home_scene=new_routes['home'], game_scene=new_routes['game'],
                    expected_revision=previous_routes.revision)
            self.engine.settings.update(changes)
            return before_fields, changes, requested is True

        def apply_complete():
            # Device/provider reads and application never hold the settings lock.
            nonlocal device_status
            device_status = self.engine.faceplate.device_status()
            self.engine._onboarding_applying = True
            before_fields = {}
            try:
                with self.engine.settings._lock:
                    before_fields, changes, activate_faceplate = persist_complete()
                self.engine.refresh_settings(changes)
                self.onboarding_transaction.committed()
            except Exception:
                if transaction_prepared:
                    try:
                        recovered = self.onboarding_transaction.recover(
                            self.engine.settings, self.engine.faceplate_preferences)
                        if recovered:self.engine.refresh_settings(before_fields)
                    except Exception as recovery_error:
                        self._onboarding_recovery_error = type(recovery_error).__name__
                        self.engine._onboarding_recovery_blocked = True
                raise
            finally:
                self.engine._onboarding_applying = False
            try:
                self.onboarding_draft.discard()
                self.onboarding_transaction.clear()
            except (OSError, ValueError):
                # The committed journal finishes cleanup at next startup.
                decky.logger.warning('[GabeCubeAura] Setup cleanup deferred')
            # Applying setup is explicit consent, equivalent to Decky On.
            # Never treat this request as USB confirmation of the saved route.
            if activate_faceplate:
                self._onboarding_event('faceplate-activation', 'requested')
                accepted = self.engine.activate_faceplate_setup()
                self._onboarding_event('faceplate-activation', 'started' if accepted else 'pending-or-blocked')
            self.engine._faceplate_next_reconcile = 0.
            self._configure_faceplate_power_events()
            return self.engine.status()
        device_status = {}
        return await asyncio.get_running_loop().run_in_executor(None, complete)

    async def export_configuration(self):
        def export():
            return write_configuration_payload(self._configuration_snapshot(),self.configuration_export_path)
        return await asyncio.get_running_loop().run_in_executor(None,export)

    def _configuration_snapshot(self):
        from signalbar.settings.baseline import collect_sources
        status=self.engine.status()
        return build_configuration_export(self.engine.settings,status['version'],status['game'],
            sources=collect_sources(self.engine,self.diagnostics))

    async def save_configuration_to_github(self):
        raise RuntimeError('Private delivery is unavailable. Export a local file instead.')

    async def export_creation(self, appid: int, mode: str, expected_sha: str):
        def export():
            from signalbar.faceplate.creation_transfer import creation_archive
            from signalbar.safe_export import write_private_bytes
            import hashlib
            data = creation_archive(self.engine.faceplate.steamgriddb, appid, mode, expected_sha)
            digest = hashlib.sha256(data).hexdigest()
            path = Path(self.configuration_export_path).with_name(
                f'GabeCubeAura-creation-{int(appid)}-{mode}-{digest[:12]}.zip')
            write_private_bytes(path, data)
            return dict(path=str(path), size_bytes=len(data), digest=digest, url='')
        return await asyncio.get_running_loop().run_in_executor(None, export)

    async def save_creation_to_github(self, appid: int, mode: str, expected_sha: str):
        raise RuntimeError('Private delivery is unavailable. Export a local file instead.')

    async def import_configuration(self, path: str):
        global_values, display_profiles, artwork_profiles, launch_artwork_profiles = read_configuration_import(path)
        await asyncio.get_running_loop().run_in_executor(
            None, self._call_with_faceplate_claim_sync, self.engine.import_configuration,
            global_values, display_profiles, artwork_profiles, launch_artwork_profiles,
        )
        await asyncio.get_running_loop().run_in_executor(None, self._configure_faceplate_power_events)
        return self.engine.status()

    async def reset_configuration(self):
        await asyncio.get_running_loop().run_in_executor(
            None, self._call_with_faceplate_claim_sync, self.engine.reset_configuration,
        )
        if getattr(self, 'onboarding_draft', None) is not None:
            self.onboarding_draft.discard()
        await asyncio.get_running_loop().run_in_executor(None, self._configure_faceplate_power_events)
        return self.engine.status()

    async def reset_settings_only(self):
        await asyncio.get_running_loop().run_in_executor(
            None, self._call_with_faceplate_claim_sync, self.engine.reset_settings_only,
        )
        if getattr(self, 'onboarding_draft', None) is not None:
            await asyncio.get_running_loop().run_in_executor(None, self.onboarding_draft.discard)
        await asyncio.get_running_loop().run_in_executor(None, self._configure_faceplate_power_events)
        return self.engine.status()

    async def factory_reset_configuration(self, confirmation: str):
        from signalbar.configuration_reset import factory_reset
        await asyncio.get_running_loop().run_in_executor(
            None, self._call_with_faceplate_claim_sync, factory_reset, self, confirmation,
        )
        await asyncio.get_running_loop().run_in_executor(None, self._configure_faceplate_power_events)
        return self.engine.status()

    async def set_mode(self, mode: str):
        self.engine.update_settings({"mode": mode})
        return self.engine.status()

    async def set_game_display(self, appid: int, mode: str):
        self.engine.update_display(appid, mode)
        return self.engine.status()

    async def set_steam_control(self, enabled: bool):
        await asyncio.get_running_loop().run_in_executor(None, self.engine.set_steam_control, enabled)
        return await asyncio.get_running_loop().run_in_executor(None, self.engine.status)

    async def set_setting(self, key: str, value):
        changes = {key: value}
        if key == "faceplate_lab_enabled" and type(value) is bool:
            changes["faceplate_setup_completed"] = True
        loop = asyncio.get_running_loop()
        if key == "faceplate_lab_enabled":
            await loop.run_in_executor(
                None, self._call_with_faceplate_claim_sync, self.engine.update_settings, changes,
            )
        else:
            await loop.run_in_executor(None, self.engine.update_settings, changes)
        if key == "faceplate_brightness":
            self.diagnostics.record(
                "faceplate_brightness_changed",
                brightness=self.engine.settings.all().get("faceplate_brightness", 100),
                source="decky_setting",
            )
        if key in {"faceplate_power_mode", "faceplate_lab_enabled", "gabe_assistant", "free_timer_end_action"}:
            await asyncio.get_running_loop().run_in_executor(
                None, self._configure_faceplate_power_events,
            )
        return await asyncio.get_running_loop().run_in_executor(None, self.engine.status)

    def _call_with_faceplate_claim_sync(self, callback, *args):
        """Follow committed settings even after failure or RPC cancellation.

        Run inside the same executor job as the mutation, not in the awaiting
        coroutine: cancelling a caller does not stop an already-running job.
        """
        try:
            return callback(*args)
        finally:
            self._sync_faceplate_claim()

    def _sync_faceplate_claim(self):
        # Early RPCs may finish while _main is still awaiting broker startup.
        # The normal startup sync publishes once its settings directory is ready.
        if not getattr(self, 'faceplate_settings_dir', None):
            return
        # Serialize late RPC completions with shutdown. Display power/standby
        # is deliberately NOT a release: another plugin must not wake it up.
        lock = self.__dict__.setdefault('_faceplate_claim_lock', threading.RLock())
        with lock:
            enabled = (not getattr(self, '_gabe_unloading', False)
                       and self.engine.settings.all().get("faceplate_lab_enabled"))
            if enabled:
                if not faceplate_claim.claim(self.faceplate_settings_dir):
                    decky.logger.warning("[GabeCubeAura] faceplate ownership claim unavailable")
            else:
                faceplate_claim.release(self.faceplate_settings_dir)

    def _configure_faceplate_power_events(self):
        monitor = getattr(self, 'faceplate_power_events', None)
        if monitor is None:
            return
        values = self.engine.settings.all()
        automatic = (values.get("faceplate_lab_enabled")
                     and values.get("faceplate_power_mode") == "auto")
        # Timer actions need power transitions even without a display.
        timer_power = (values.get('free_timer_end_action', 'none') != 'none'
                       or self.engine.countdown.end_action.status()['phase'] in ('armed', 'ready', 'executing'))
        if automatic or timer_power:
            monitor.start()
        else:
            monitor.stop()

    def _handle_faceplate_power_event(self, kind: str, starting: bool):
        values = self.engine.settings.all()
        automatic = bool(values.get('faceplate_lab_enabled')
                         and values.get('faceplate_power_mode') == 'auto')
        self.engine._assistant_system_suspended = bool(starting)
        if starting:
            self.engine.countdown.end_action.cancel('system-suspended')
            # Withdraw temporary presentation leases before logind sleeps.
            if not automatic:
                self.engine.assistant.cancel('system-suspended')
        self.engine._assistant_wake_allowed = self.engine._assistant_wake_policy(values)
        if not automatic:
            return  # A manual/off panel must not receive a power command.
        if starting:
            self.engine.suspend_faceplate(kind)
        else:
            self.engine.resume_faceplate()

    async def set_faceplate_power(self, enabled: bool):
        await asyncio.get_running_loop().run_in_executor(
            None, self.engine.set_faceplate_power, bool(enabled), "Decky control",
        )
        return self.engine.status()

    async def resume_faceplate(self):
        """Redundant Steam resume path if the logind monitor was interrupted."""
        await asyncio.get_running_loop().run_in_executor(
            None, self.engine.resume_faceplate,
        )
        return self.engine.status()

    async def set_faceplate_routing(self, home_scene: str, game_scene: str,
                                    expected_revision: int, performance_risk_accepted: bool = False):
        self.diagnostics.record(
            "faceplate_route_requested", home_scene=home_scene,
            game_scene=game_scene, expected_revision=int(expected_revision),
        )
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, self.engine.update_faceplate_routing,
                home_scene, game_scene, int(expected_revision), performance_risk_accepted,
            )
        except (ValueError, FaceplateRevisionConflict) as error:
            self.diagnostics.record(
                "faceplate_route_failed", error=str(error),
                home_scene=home_scene, game_scene=game_scene,
            )
            raise ValueError(str(error)) from error
        status = self.engine.status()
        faceplate = status.get("faceplate", {})
        routing = faceplate.get("routing", {}) if isinstance(faceplate, dict) else {}
        preparation = routing.get("preparation", {}) if isinstance(routing, dict) else {}
        self.diagnostics.record(
            "faceplate_route_finished",
            desired_scene=routing.get("desired_scene", ""),
            effective_scene=routing.get("effective_scene", ""),
            preparation_state=preparation.get("state", ""),
            preparation_error=preparation.get("error", ""),
        )
        return status

    async def set_faceplate_visual_theme(self, visual_theme: str,
                                         expected_revision: int):
        self.diagnostics.record(
            "faceplate_visual_theme_requested", visual_theme=visual_theme,
            expected_revision=int(expected_revision),
        )
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, self.engine.update_faceplate_visual_theme,
                visual_theme, int(expected_revision),
            )
        except (ValueError, FaceplateRevisionConflict) as error:
            self.diagnostics.record(
                "faceplate_visual_theme_failed", visual_theme=visual_theme,
                error=str(error),
            )
            raise ValueError(str(error)) from error
        status = self.engine.status()
        self.diagnostics.record(
            "faceplate_visual_theme_finished", visual_theme=visual_theme,
        )
        return status

    async def set_faceplate_scene_theme(self, scene_kind: str, scene_theme: str,
                                        expected_revision: int):
        self.diagnostics.record(
            "faceplate_scene_theme_requested", scene_kind=scene_kind,
            scene_theme=scene_theme, expected_revision=int(expected_revision),
        )
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, self.engine.update_faceplate_scene_theme,
                scene_kind, scene_theme, int(expected_revision),
            )
        except (ValueError, FaceplateRevisionConflict) as error:
            self.diagnostics.record(
                "faceplate_scene_theme_failed", scene_kind=scene_kind,
                scene_theme=scene_theme, error=str(error),
            )
            raise ValueError(str(error)) from error
        status = self.engine.status()
        self.diagnostics.record(
            "faceplate_scene_theme_finished", scene_kind=scene_kind,
            scene_theme=scene_theme,
        )
        return status

    async def set_steamgriddb_api_key(self, api_key: str):
        self.diagnostics.record("steamgriddb_key_validation_started", replacement=True)
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.engine.faceplate.steamgriddb.set_api_key(
                    api_key, validate=True,
                ),
            )
        except SteamGridDBError as error:
            self.diagnostics.record("steamgriddb_key_validation_failed", error=str(error))
            raise ValueError(str(error)) from error
        steamgriddb = self.engine.status().get("faceplate", {}).get("steamgriddb", {})
        self.diagnostics.record(
            "steamgriddb_key_validation_finished",
            state=steamgriddb.get("validation_state", ""),
            code=steamgriddb.get("validation_code", ""),
            detail=steamgriddb.get("validation_detail", ""),
        )
        if getattr(self,'studio',None): self.studio.refresh_key_state()
        return self.engine.status()

    async def validate_steamgriddb_api_key(self):
        self.diagnostics.record("steamgriddb_key_validation_started", replacement=False)
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, self.engine.faceplate.steamgriddb.validate_api_key,
            )
        except Exception as error:
            self.diagnostics.record("steamgriddb_key_validation_failed", error=str(error))
            raise
        steamgriddb = self.engine.status().get("faceplate", {}).get("steamgriddb", {})
        self.diagnostics.record(
            "steamgriddb_key_validation_finished",
            state=steamgriddb.get("validation_state", ""),
            code=steamgriddb.get("validation_code", ""),
            detail=steamgriddb.get("validation_detail", ""),
        )
        return self.engine.status()

    async def clear_steamgriddb_api_key(self):
        self.engine.faceplate.steamgriddb.clear_api_key()
        if getattr(self,'studio',None): self.studio.refresh_key_state()
        return self.engine.status()

    @staticmethod
    def _clean_faceplate_artwork_job(value):
        clean = dict(value or {})
        prepared = clean.get("prepared")
        if isinstance(prepared, dict):
            clean["prepared"] = {
                key: prepared.get(key) for key in (
                    "appid", "asset_id", "mode", "ready", "animation_style",
                    "thumb", "animated", "author", "asset_kind", "source_width",
                    "source_height", "crop_axis", "crop_y", "saturation",
                    "crop_x", "brightness", "logo_scale", "frames", "peak_load", "size", "sha256",
                    "loop_cleanup", "loop_original_frames",
                    "loop_trimmed_frames", "loop_trimmed_ms",
                    "dashboard_pack_frames", "dashboard_pack_revision",
                    "dashboard_treatment", "dashboard_show_clock",
                    "dashboard_compression",
                    "dashboard_clock_size", "dashboard_show_status_rail",
                    "dashboard_show_session", "dashboard_show_battery",
                )
            }
        return clean

    async def get_faceplate_installed_games(self):
        games = await asyncio.get_running_loop().run_in_executor(
            None, installed_games,
        )
        return {"games": games, "count": len(games)}

    def _stop_cinema(self, timeout=None):
        """Compatibility shutdown hook; Studio no longer starts in this plugin."""
        # The hook name remains only for bounded unload compatibility.
        self._stop_jsaux_broker(timeout=timeout)

    def _stop_jsaux_broker(self, timeout=None):
        budget = ShutdownBudget(timeout)
        for component in (getattr(self, 'jsaux_broker_server', None),
                          getattr(self, 'jsaux_broker', None)):
            if component is not None:
                budget.call(component.stop)

    def _start_jsaux_broker(self):
        """One secure startup attempt; report a stage, never a secret path."""
        if getattr(self, 'jsaux_broker_server', None) is not None:
            return True
        if time.monotonic() < getattr(self, '_jsaux_broker_retry_at', 0.):
            return False
        lock = getattr(self, '_jsaux_broker_start_lock', None)
        if lock is None or not lock.acquire(blocking=False):
            return False
        stage = 'runtime-provisioning'
        try:
            provision_runtime(CANONICAL_RUNTIME)
            stage = 'content-storage'
            # Installed exports must survive an OS reboot without a DAS service.
            # Backend-owned private storage, separate from user-owned Decky settings.
            self.jsaux_broker = Broker(PERSISTENT_JSAUX_CONTENT,
                                       adapter=self.engine.jsaux_broker_adapter)
            stage = 'socket-start'
            self.jsaux_broker_server = BrokerServer(self.jsaux_broker, runtime_dir=CANONICAL_RUNTIME)
            self.jsaux_broker_server.start()
            self._jsaux_broker_error, self._jsaux_broker_stage, self._jsaux_broker_errno = '', 'ready', None
            self._jsaux_broker_runtime_diagnostic = {}
            return True
        except (OSError, RuntimeError, ValueError) as error:
            self._jsaux_broker_error = type(error).__name__
            self._jsaux_broker_stage = stage
            self._jsaux_broker_errno = getattr(error, 'errno', None)
            self._jsaux_broker_runtime_diagnostic = getattr(error, 'diagnostic', {})
            self._jsaux_broker_retry_at = time.monotonic() + 10.
            self._stop_jsaux_broker(timeout=0)
            self.jsaux_broker_server = self.jsaux_broker = None
            decky.logger.warning('[GabeCubeAura] JSAUX broker ' + stage + ': ' + type(error).__name__)
            return False
        finally:
            lock.release()

    async def _recover_jsaux_startup(self):
        # Finite recovery inside the plugin, not a daemon or idle polling loop.
        for delay in (10, 20, 40):
            if self.jsaux_broker is not None: return
            await asyncio.sleep(delay)
            if getattr(self, '_gabe_unloading', False): return
            await asyncio.get_running_loop().run_in_executor(None, self._start_jsaux_broker)

    async def animated_screensaver_studio(self, action: str, payload: dict = None):
        # A frontend surviving plugin upgrade must not restart old preparation.
        return {'retired': True, 'name': 'Decky-Animated-Screensaver',
                'error': self._cinema_error, 'preserved_existing_files': True}

    async def set_cinema_context(self, payload: dict):
        # Retired installed-player relay cannot acquire the matrix after update.
        return False

    async def get_jsaux_broker_status(self):
        """Sanitized local diagnostic; never return endpoint capability."""
        if getattr(self, 'jsaux_broker', None) is None:
            await asyncio.get_running_loop().run_in_executor(None, self._start_jsaux_broker)
        return self._broker_diagnostic_snapshot()


    def _timer_steam_action(self, payload):
        asyncio.run_coroutine_threadsafe(decky.emit('timer-action', payload), self._integration_loop)

    async def timer_claim_action(self, token: str):
        return self.engine.assistant.actions.claim(token)

    async def timer_acknowledge_action(self, token: str, accepted: bool):
        self.engine.assistant.actions.acknowledge(token, accepted)

    async def get_ambience_profiles(self):
        return self.engine.ambience.status()

    async def save_ambience_profile(self, name: str, values: dict, identifier: str = ''):
        return await asyncio.get_running_loop().run_in_executor(
            None, self.engine.ambience.save, name, values, identifier)

    async def activate_ambience_profile(self, identifier: str):
        return await asyncio.get_running_loop().run_in_executor(None, self.engine.ambience.activate, identifier)

    async def delete_ambience_profile(self, identifier: str):
        return await asyncio.get_running_loop().run_in_executor(None, self.engine.ambience.delete, identifier)













    async def search_faceplate_artwork(self, appid: int, preference: str):
        self.diagnostics.record(
            "faceplate_artwork_search_started", appid=int(appid), preference=preference,
        )
        try:
            results = await asyncio.get_running_loop().run_in_executor(
                None, self.engine.faceplate.steamgriddb.search,
                int(appid), str(preference),
            )
        except SteamGridDBError as error:
            self.diagnostics.record(
                "faceplate_artwork_search_failed", appid=int(appid), error=str(error),
            )
            raise ValueError(str(error)) from error
        # The original URL remains backend-only. Decky renders at most eight
        # bounded thumbnails and never receives source media or image bytes.
        safe = [{
            key: item.get(key) for key in (
                "id", "kind", "score", "style", "thumb", "animated", "author",
                "width", "height",
            )
        } for item in results[:8]]
        self.diagnostics.record(
            "faceplate_artwork_search_finished", appid=int(appid), count=len(safe),
        )
        return {"results": safe, "count": len(safe)}

    async def get_faceplate_artwork_job(self, appid: int = 0):
        appid = max(0, int(appid or 0))
        library = self.engine.faceplate.steamgriddb
        selected = library.selected_manifest(appid) if appid else {}
        prepared = {
            mode: library.prepared_manifest(appid, mode) if appid else {}
            for mode in ("static", "animated", "pan")
        }
        return {
            "job": self._clean_faceplate_artwork_job(self.faceplate_artwork_jobs.status()),
            "selected": {key: selected.get(key) for key in (
                "appid", "asset_id", "mode", "thumb", "animated", "author",
                "asset_kind", "source_width", "source_height", "frames", "size",
                "dashboard_pack_frames", "dashboard_treatment",
                "dashboard_compression",
                "dashboard_show_clock", "dashboard_clock_size",
                "dashboard_show_status_rail", "dashboard_show_session",
                "dashboard_show_battery",
                "loop_cleanup", "loop_original_frames", "loop_trimmed_frames",
                "loop_trimmed_ms", "logo_scale",
            )} if selected else {},
            "prepared": {
                mode: {key: value.get(key) for key in (
                    "appid", "asset_id", "mode", "thumb", "animated", "author",
                    "asset_kind", "source_width", "source_height", "frames",
                    "dashboard_pack_frames", "dashboard_treatment",
                    "dashboard_compression",
                    "dashboard_show_clock", "dashboard_clock_size",
                    "dashboard_show_status_rail", "dashboard_show_session",
                    "dashboard_show_battery",
                    "loop_cleanup", "loop_original_frames", "loop_trimmed_frames",
                    "loop_trimmed_ms", "art_style", "logo_position", "logo_scale",
                )} for mode, value in prepared.items() if value
            },
        }

    async def get_faceplate_dashboard_background_status(self):
        appid = int(self.engine.settings.all().get("faceplate_dashboard_home_appid", 0) or 0)
        manifest = await asyncio.get_running_loop().run_in_executor(
            None, self.engine.faceplate.steamgriddb.home_dashboard_manifest, appid,
        ) if appid > 0 else {}
        return {"appid": appid, "ready": bool(manifest)}

    async def get_faceplate_artwork_library(self):
        library, games = await asyncio.gather(
            asyncio.get_running_loop().run_in_executor(
                None, self.engine.faceplate.steamgriddb.library_entries,
            ),
            asyncio.get_running_loop().run_in_executor(None, installed_games),
        )
        names = {int(item.get("appid", 0)): str(item.get("name", "")) for item in games}
        for item in library:
            item["name"] = names.get(int(item.get("appid", 0) or 0), "")
        return {"entries": library, "count": len(library)}

    async def delete_faceplate_artwork(self, appid: int, mode: str):
        if self.engine.faceplate_game_snapshot()["appid"] > 0:
            raise ValueError("Quit the running game before deleting artwork")
        job = self.faceplate_artwork_jobs.status()
        if job.get("state") in {"queued", "running", "cancelling"}:
            raise ValueError("Wait for artwork preparation to finish")
        def delete_and_list():
            library = self.engine.faceplate.steamgriddb
            deleted = library.delete_prepared(int(appid), str(mode))
            # Deletion must not rescan the complete Steam library merely to
            # rediscover display names the frontend already owns.
            return deleted, library.library_entries()

        try:
            deleted, entries = await asyncio.get_running_loop().run_in_executor(
                None, delete_and_list,
            )
        except SteamGridDBError as error:
            raise ValueError(str(error)) from error
        values = self.engine.settings.all()
        if (int(values.get("faceplate_dashboard_home_appid", 0) or 0) == int(appid)
                and not self.engine.faceplate.steamgriddb.selected_dashboard_manifest(int(appid))):
            self.engine.settings.update({
                "faceplate_dashboard_home_appid": 0,
                "faceplate_dashboard_home_source": "weather",
            })
        self.engine.refresh_faceplate("artwork-library-delete")
        self.diagnostics.record(
            "faceplate_artwork_deleted", appid=int(appid), mode=str(mode),
            deleted=bool(deleted),
        )
        return {"entries": entries, "count": len(entries)}

    async def get_faceplate_artwork_preview(self, appid: int):
        """Pixel Studio preview: the selected 64x54 GIF after orientation."""
        data, source = await asyncio.get_running_loop().run_in_executor(
            None, self.engine.faceplate.preview_artwork, int(appid),
        )
        if data is None:
            return {"data_uri": "", "source": source,
                    "error": "No prepared or local artwork found for this game"}
        return {"data_uri": "data:image/gif;base64," +
                base64.b64encode(data).decode("ascii"), "source": source, "error": ""}

    async def get_prepared_faceplate_artwork_preview(self, appid: int, mode: str):
        def preview():
            prepared = self.engine.faceplate.steamgriddb.prepared(int(appid), str(mode), draft=True)
            if prepared is None:
                raise ValueError("Prepare the artwork before previewing it")
            return self.engine.faceplate._orient_gif(prepared[0])
        data = await asyncio.get_running_loop().run_in_executor(None, preview)
        return {"data_uri": "data:image/gif;base64," + base64.b64encode(data).decode("ascii")}

    async def get_faceplate_artwork_dashboard_preview(self, appid: int, mode: str = "", draft: bool = False, home: bool = False):
        try:
            preview = await asyncio.get_running_loop().run_in_executor(
                None, self.engine.faceplate_artwork_dashboard_preview, int(appid), str(mode), bool(draft), bool(home),
            )
        except (ValueError, SteamGridDBError) as error:
            raise ValueError(str(error)) from error
        data = preview.pop("gif")
        preview["data_uri"] = "data:image/gif;base64," + base64.b64encode(data).decode("ascii")
        return preview

    async def prepare_faceplate_artwork(self, appid: int, asset_id: int,
                                        asset_kind: str, mode: str, crop_y: int,
                                        saturation: int, brightness: int,
                                        crop_x: int = 50,
                                        dashboard_treatment: str = "cinema",
                                        dashboard_show_clock: bool = False,
                                        dashboard_clock_size: str = "large",
                                        dashboard_show_session: bool = True,
                                        dashboard_show_battery: bool = True,
                                        dashboard_compression: str = "compatible",
                                        loop_cleanup: str = "no", draft: bool = False,
                                        logo_scale: int = 100):
        from signalbar.faceplate.artwork_layout import validate_logo_scale
        validate_logo_scale(logo_scale)
        stored = self.engine.settings.all()
        profile = stored.get("faceplate_artwork_profiles", {}).get(str(int(appid)), {})
        request = {
            "art_style": profile.get(
                "style", stored.get("faceplate_artwork_style", "logo_dim")),
            "logo_position": profile.get(
                "position", stored.get("faceplate_logo_position", "bottom")),
            "logo_scale": logo_scale,
            "appid": int(appid), "asset_id": int(asset_id),
            "asset_kind": str(asset_kind), "mode": str(mode),
            "crop_y": int(crop_y), "saturation": int(saturation),
            "brightness": int(brightness),
            "crop_x": int(crop_x),
            "dashboard_treatment": str(dashboard_treatment),
            "dashboard_compression": str(dashboard_compression),
            "dashboard_show_clock": bool(dashboard_show_clock),
            "dashboard_clock_size": str(dashboard_clock_size),
            "dashboard_show_session": bool(dashboard_show_session),
            "dashboard_show_battery": bool(dashboard_show_battery),
            "loop_cleanup": str(loop_cleanup),
            "draft": bool(draft),
        }
        try:
            job = await asyncio.get_running_loop().run_in_executor(
                None, self.faceplate_artwork_jobs.start, request,
            )
        except SteamGridDBError as error:
            raise ValueError(str(error)) from error
        self.diagnostics.record(
            "faceplate_artwork_preparation_started", appid=int(appid), mode=mode,
        )
        return self._clean_faceplate_artwork_job(job)

    async def cancel_faceplate_artwork(self):
        job = await asyncio.get_running_loop().run_in_executor(
            None, self.faceplate_artwork_jobs.cancel,
        )
        return self._clean_faceplate_artwork_job(job)

    async def get_faceplate_delivery_status(self):
        """Read the current worker receipt, never probe USB or reload media."""
        return self.engine.faceplate_delivery_status()

    async def _run_faceplate_artwork_apply(self, key, operation, progress):
        """Join overlapping identical Apply calls and serialize library promotion.

        Cancellation of one RPC must not cancel a copy another caller awaits.
        Route changes share the existing reentrant configuration lock.
        """
        pending = getattr(self, '_faceplate_artwork_applies', None)
        if pending is None:
            pending = self._faceplate_artwork_applies = {}
        future = pending.get(key)
        if future is None:
            def run():
                try:
                    with self.engine._faceplate_configuration_lock:
                        return operation()
                except Exception as error:
                    self.diagnostics.record('faceplate_artwork_apply_failed',
                        appid=key[1], mode=key[2], destination=key[0],
                        stage=progress['stage'], error_type=type(error).__name__)
                    raise
            future = asyncio.get_running_loop().run_in_executor(None, run)
            pending[key] = future
            def finished(done):
                if pending.get(key) is done:
                    pending.pop(key, None)
                if not done.cancelled():
                    done.exception()  # Also observe an abandoned caller's failure.
            future.add_done_callback(finished)
        return await asyncio.shield(future)

    async def activate_faceplate_artwork(self, appid: int, mode: str, draft: bool = False, expected_sha: str = "", presentation: str = "artwork"):
        if presentation not in {"artwork", "artwork-dashboard"}:
            raise ValueError("Unknown artwork presentation")
        if self.faceplate_artwork_jobs.status().get("state") in {"queued", "running", "cancelling"}:
            raise ValueError("Wait for artwork preparation to finish")

        progress = {'stage': 'validate'}
        def activate():
            library = self.engine.faceplate.steamgriddb
            if presentation == "artwork-dashboard" and not library.prepared_dashboard_manifest(
                    int(appid), str(mode), **({"draft": True} if draft else {})):
                raise SteamGridDBError(
                    "This saved artwork predates Dashboard support. Prepare it once again."
                )
            if draft:
                self._verify_faceplate_draft(int(appid), str(mode), expected_sha)
                stored = self.engine.settings.all()
                # Freeze a Lab57 shared Home background before replacing its
                # game slot, so the new game-only destination is independent.
                if (stored.get("faceplate_dashboard_home_source") == "artwork"
                        and stored.get("faceplate_dashboard_home_appid") == int(appid)
                        and not (library.artwork_root / str(int(appid)) / "home.json").exists()):
                    existing = library.selected_dashboard_manifest(int(appid))
                    if existing:
                        progress['stage'] = 'save-home'
                        library.assign_home(int(appid), existing["mode"])
            progress['stage'] = 'save-game'
            selected = self.engine.faceplate.steamgriddb.activate_prepared(
                int(appid), str(mode), **({"draft": True} if draft else {}),
            )
            # Prepared files are already decoded/encoded. Applying them is
            # permitted during a game, but never starts a conversion here.
            # Commit the content first, then select its scene and queue once.
            progress['stage'] = 'select-display'
            preferences = self.engine.faceplate_preferences.read()
            self.engine.update_faceplate_routing(
                preferences.home_scene, presentation, preferences.revision,
            )
            return selected

        try:
            selected = await self._run_faceplate_artwork_apply(
                ('game', int(appid), str(mode), bool(draft), str(expected_sha), presentation),
                activate, progress)
        except (SteamGridDBError, FaceplateRevisionConflict) as error:
            raise ValueError(str(error)) from error
        self.diagnostics.record(
            "faceplate_artwork_activated", appid=int(appid), mode=mode,
            presentation=presentation,
        )
        return {key: selected.get(key) for key in (
            "appid", "asset_id", "mode", "thumb", "animated", "author",
            "asset_kind", "source_width", "source_height", "frames", "size",
            "dashboard_pack_frames", "dashboard_treatment",
            "dashboard_compression",
            "dashboard_show_clock", "dashboard_clock_size",
            "dashboard_show_status_rail", "dashboard_show_session",
            "dashboard_show_battery",
            "loop_cleanup", "loop_original_frames", "loop_trimmed_frames",
            "loop_trimmed_ms",
        )}

    def _verify_faceplate_draft(self, appid, mode, expected_sha):
        if self.faceplate_artwork_jobs.status().get("state") in {"queued", "running", "cancelling"}:
            raise ValueError("Wait for artwork preparation to finish")
        prepared = self.engine.faceplate.steamgriddb.prepared(appid, mode, draft=True)
        if not expected_sha or prepared is None or prepared[1].get("sha256") != expected_sha:
            raise ValueError("The prepared artwork changed. Review its new preview before applying.")

    async def assign_faceplate_dashboard_artwork(self, appid: int, mode: str, draft: bool = False, home_only: bool = False, expected_sha: str = "", include_status: bool = True):
        """Atomically activate a prepared pack and make it Dashboard Home."""
        appid = int(appid)
        mode = str(mode)
        job = self.faceplate_artwork_jobs.status()
        if job.get("state") in {"queued", "running", "cancelling"}:
            raise ValueError("Wait for artwork preparation to finish")

        progress = {'stage': 'validate'}
        def assign():
            library = self.engine.faceplate.steamgriddb
            if draft:
                self._verify_faceplate_draft(appid, mode, expected_sha)
            if not library.prepared_dashboard_manifest(appid, mode, **({"draft": True} if draft else {})):
                raise SteamGridDBError(
                    "This saved artwork predates Dashboard support. Prepare it once again."
                )
            # Home owns a separate immutable prepared slot: a later game-only
            # replacement must not silently replace the chosen Home theme.
            progress['stage'] = 'save-home'
            selected = library.assign_home(appid, mode, draft=draft)
            if not home_only:
                progress['stage'] = 'save-game'
                library.activate_prepared(appid, mode, **({"draft": True} if draft else {}))
            preferences = self.engine.faceplate_preferences.read()
            assignment = {
                "faceplate_dashboard_home_appid": appid,
                "faceplate_dashboard_home_source": "artwork",
            }
            # Persist without reconfiguring the LED providers or rendering the
            # previous route. The final route update queues the complete
            # assignment exactly once through the sole Faceplate worker.
            progress['stage'] = 'save-settings'
            self.engine.settings.update(assignment)
            progress['stage'] = 'select-display'
            self.engine.update_faceplate_routing(
                "artwork-dashboard", preferences.game_scene if home_only else "artwork-dashboard",
                preferences.revision,
            )
            return selected

        try:
            selected = await self._run_faceplate_artwork_apply(
                ('home' if home_only else 'both', appid, mode, bool(draft), str(expected_sha)),
                assign, progress)
        except (SteamGridDBError, ValueError, FaceplateRevisionConflict) as error:
            raise ValueError(str(error)) from error
        self.diagnostics.record(
            "faceplate_dashboard_artwork_assigned", appid=appid, mode=mode,
            dashboard_pack_frames=int(selected.get("dashboard_pack_frames", 0) or 0),
        )
        if not include_status:
            # Applying is complete. A later status read is a separate UI concern.
            return {key: selected.get(key) for key in ('appid', 'mode', 'sha256', 'frames', 'dashboard_pack_frames')}
        return self.engine.status()

    async def set_steamgriddb_preference(self, preference: str):
        try:
            self.engine.faceplate.steamgriddb.set_preference(preference)
        except SteamGridDBError as error:
            raise ValueError(str(error)) from error
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

    async def report_dashboard_stats(self, appid: int, stats: dict):
        return self.engine.report_dashboard_stats(appid, stats)

    async def claim_player_city_poll(self):
        return self.engine.claim_player_city_poll()

    async def complete_player_city_poll(self, request_id: str, appid: int, payload=None, error_code: str = ''):
        return self.engine.complete_player_city_poll(request_id, appid, payload, error_code)

    async def game_changed(self, appid: int = 0, title: str = "", launch: bool = False,
                           source: str = ""):
        self.diagnostics.record(
            "game_change_requested", appid=int(appid or 0), launch=bool(launch), source=source,
        )
        try:
            self.engine.set_game(appid, title, launch, source)
            self.pixel_studio.set_current_game({"appid": appid, "title": title})
        except Exception as error:
            self.diagnostics.record(
                "game_change_failed", appid=int(appid or 0), error=str(error),
            )
            raise
        self.diagnostics.record(
            "game_change_finished", appid=int(appid or 0), launch=bool(launch), source=source,
        )
        return self.engine.status()

    async def get_quick_artwork(self, appid: int = 0, source: str = "hero"):
        def preview():
            game = self.engine.faceplate_game_snapshot()
            if game.get('appid') != appid:
                return {'found': False, 'appid': appid}
            result = get_quick_artwork(appid, source)
            if not result.get('found'):
                self.diagnostics.record('quick_artwork_unavailable', appid=appid, source=source,
                                        **quick_preview_diagnostic())
            return result
        return await asyncio.get_running_loop().run_in_executor(None, preview)

    async def get_artwork(self, appid: int = 0, source: str = "hero", purpose: str = "artwork",
                          include_data: bool = True):
        result = await asyncio.get_running_loop().run_in_executor(
            None, get_library_artwork, appid, source, include_data,
        )
        if result.get("found"):
            prepare = (
                self.engine.prepare_launch_artwork
                if purpose == "launch" else self.engine.prepare_artwork
            )
            result["cached"] = await asyncio.get_running_loop().run_in_executor(
                None, prepare, result["appid"], result["fingerprint"],
                result["filename"], result["source"],
            )
        if not include_data:
            # The background game watcher never transports or decodes artwork.
            # Missing palettes are prepared explicitly from the Artwork page;
            # launch must remain a metadata-only, non-blocking path.
            result.pop("data_uri", None)
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

    async def preview_display_preset(self, preset: str, owner: str = ''):
        if not isinstance(owner, str) or len(owner) > 80:
            raise ValueError('Invalid preview owner')
        def preview():
            if not self.engine.preview_display_preset(preset, 10.0, owner=owner):
                raise ValueError('Invalid setup experience')
            return self.engine.status()
        return await asyncio.get_running_loop().run_in_executor(None, preview)

    async def stop_display_preset_preview(self, owner: str):
        return await asyncio.get_running_loop().run_in_executor(
            None, self.engine.stop_display_preset_preview, owner)

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
        if event in PERSISTED_RUNTIME_EVENTS:
            self.diagnostics.record(
                "runtime_diagnostic",
                name=event,
                appid=int(appid or 0),
                source=source,
                duration_ms=max(-1, round(float(duration_ms), 1)),
            )
        return True





    async def report_parental_minutes(self, minutes: float):
        self.engine.report_parental_minutes(minutes)
        return self.engine.status()

    async def start_free_timer(self, minutes: int, end_action: str = 'none'):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.engine.start_free_timer, minutes, end_action)
        await loop.run_in_executor(None, self._configure_faceplate_power_events)
        return await loop.run_in_executor(None, self.engine.status)

    async def stop_free_timer(self):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.engine.stop_free_timer)
        await loop.run_in_executor(None, self._configure_faceplate_power_events)
        return await loop.run_in_executor(None, self.engine.status)

    async def extend_free_timer(self, minutes: int = 15):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.engine.extend_free_timer, minutes)
        return await loop.run_in_executor(None, self.engine.status)

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

    async def preview_weather(self, condition: str, variant: int, visual_theme: str = ""):
        return await asyncio.get_running_loop().run_in_executor(
            None, self.engine.preview_weather,
            condition, int(variant), visual_theme,
        )

    async def get_faceplate_weather_preview(self, condition: str, variant: int,
                                            visual_theme: str = ""):
        """Render the hardware Weather GIF off Decky's RPC/event loop."""
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                None, self.engine.faceplate_weather_preview,
                condition, int(variant), visual_theme,
            )
            payload = result.pop("gif")
            return {
                **result,
                "data_uri": "data:image/gif;base64," + base64.b64encode(payload).decode("ascii"),
                "error": "",
            }
        except Exception as error:
            decky.logger.warning(
                f"[GabeCubeAura] Faceplate Weather preview failed: "
                f"{type(error).__name__}: {error}"
            )
            return {"data_uri": "", "error": str(error)[:180]}

    async def get_faceplate_dashboard_preview(self, condition: str, variant: int,
                                              visual_theme: str = ""):
        """Render the selected Home Dashboard off Decky's RPC/event loop."""
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                None, self.engine.faceplate_dashboard_preview,
                condition, int(variant), visual_theme,
            )
            payload = result.pop("gif")
            return {
                **result,
                "data_uri": "data:image/gif;base64," + base64.b64encode(payload).decode("ascii"),
                "error": "",
            }
        except Exception as error:
            decky.logger.warning(
                f"[GabeCubeAura] Faceplate Dashboard preview failed: "
                f"{type(error).__name__}: {error}"
            )
            return {"data_uri": "", "error": str(error)[:180]}

    async def stop_weather_preview(self):
        return self.engine.stop_weather_preview()

    async def get_pixel_studio_status(self):
        return await asyncio.get_running_loop().run_in_executor(
            None, self.pixel_studio.status,
        )

    async def repair_pixel_studio(self):
        return await asyncio.get_running_loop().run_in_executor(
            None, self.pixel_studio.disable_standalone,
        )

    async def start_pixel_studio(self):
        self.diagnostics.record("pixel_studio_start_requested")
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                None, self.pixel_studio.start,
            )
        except Exception as error:
            self.diagnostics.record("pixel_studio_start_exception", error=str(error))
            raise
        self.diagnostics.record(
            "pixel_studio_start_result",
            running=bool(result.get("service_running")),
            started=bool(result.get("started")),
            error=result.get("error", ""),
        )
        return result

    async def set_pixel_studio_brightness(self, value: int):
        brightness = max(5, min(100, int(value)))
        await asyncio.get_running_loop().run_in_executor(
            None, self.engine.update_settings, {"faceplate_brightness": brightness},
        )
        # Compatibility endpoint for an older cached frontend. Brightness is a
        # GabeCubeAura preference and must never start/probe the companion while
        # a Decky slider is moving.
        self.pixel_studio.last_brightness = brightness
        self.diagnostics.record("faceplate_brightness_changed", brightness=brightness)
        return self.pixel_studio.status(probe=False)

    async def get_diagnostic_status(self):
        return self.diagnostics.status()

    async def set_diagnostic_upload(self, enabled: bool):
        result = self.diagnostics.set_automatic_upload(bool(enabled))
        self.engine.assistant.diagnostic["automatic"] = result["automatic_upload"]
        if not enabled:
            automatic=getattr(self,'automatic_incidents',None)
            if automatic:automatic.disable()
            timer = getattr(self, "_gabe_report_timer", None)
            if timer: timer.cancel()
        return result

    async def enable_capture_diagnostic(self):
        self.engine.screen_sync_trace.enable_detail(300)
        # Existing capture lifecycle will use the detail level on its next start.
        return {'seconds': 300}

    async def export_diagnostic_report(self):
        report = await asyncio.get_running_loop().run_in_executor(
            None, lambda: self.diagnostics.build_report(cinema=self._cinema_diagnostic_snapshot()),
        )
        report["report"]["updates"] = self._update_diagnostic_snapshot()
        report["report"]["display_control"] = self.diagnostics._sanitize(self.engine.display_control_snapshot())
        trace = getattr(self.engine, "screen_sync_trace", None)
        if isinstance(trace, ScreenSyncTrace):
            report["report"]["screen_sync_trace"] = trace.snapshot()
        destination = Path(self.configuration_export_path).parent / "GabeCubeAura-diagnostic.json"
        from signalbar.safe_export import write_private_bytes
        data = (json.dumps(report['report'], indent=2, ensure_ascii=False) + '\n').encode()
        await asyncio.get_running_loop().run_in_executor(None, write_private_bytes, destination, data)
        return {"path": str(destination)}

    def _update_diagnostic_snapshot(self):
        state = self.update_manager.status()
        return self.diagnostics._sanitize({key: state.get(key) for key in (
            "phase", "installed_version", "available_version", "error_category",
            "error", "last_result", "recovery_error",
        )})

    def _broker_diagnostic_snapshot(self):
        broker = getattr(self, 'jsaux_broker', None)
        snapshot = {'available': broker is not None, 'protocol': 'jsaux-broker',
                    'contract_revision': 4,
                    'error': getattr(self, '_jsaux_broker_error', ''),
                    'startup_stage': getattr(self, '_jsaux_broker_stage', 'unknown'),
                    'startup_errno': getattr(self, '_jsaux_broker_errno', None),
                    'effective_uid': os.geteuid(),
                    'content_storage': 'private-persistent-cache',
                    'runtime_check': dict(getattr(self, '_jsaux_broker_runtime_diagnostic', {})),
                    'studio_retired': True, 'legacy_files_preserved': True}
        if broker is not None and callable(getattr(broker, 'diagnostic_snapshot', None)):
            snapshot['delegation'] = broker.diagnostic_snapshot()
            snapshot['installed_player'] = broker.player_runtime.snapshot()
        adapter = getattr(getattr(self, 'engine', None), 'jsaux_broker_adapter', None)
        if adapter is not None:
            # Adapter metadata contains no authentication capability or paths.
            try:
                snapshot['state'] = adapter.snapshot()
                if callable(getattr(adapter,'diagnostic_snapshot',None)):
                    snapshot['usb'] = adapter.diagnostic_snapshot()
            except (OSError, RuntimeError, ValueError):
                snapshot['error'] = 'state-unavailable'
        return snapshot

    def _cinema_diagnostic_snapshot(self):
        # Retain the old report key for support-tool readers, not a Studio engine.
        return self._broker_diagnostic_snapshot()

    async def send_cinema_diagnostic(self):
        return await self._upload_diagnostic_report('JSAUX broker compatibility')

    async def _upload_diagnostic_report(self, reason: str, system_evidence=None):
        raise RuntimeError('Private delivery is unavailable. Export a local file instead.')

    async def send_diagnostic_report(self):
        return await self._upload_diagnostic_report("manual report")

    async def get_update_status(self):
        return self.update_manager.status()

    async def check_for_updates(self):
        return await asyncio.get_running_loop().run_in_executor(
            None, self.update_manager.check, True,
        )

    async def prepare_update(self):
        return await asyncio.get_running_loop().run_in_executor(None, self.update_manager.prepare)

    async def cancel_update_preparation(self):
        return self.update_manager.cancel_preparation()

    async def prepare_previous_version(self):
        return await asyncio.get_running_loop().run_in_executor(
            None, self.update_manager.prepare_previous_version,
        )

    async def prepare_lab114_rollback(self):
        return await asyncio.get_running_loop().run_in_executor(
            None, self.update_manager.prepare_lab114_rollback,
        )

    async def install_prepared_update(self, confirmation_token: str):
        return await asyncio.get_running_loop().run_in_executor(
            None, self.update_manager.install, confirmation_token,
        )

    async def set_update_preferences(self, auto_check: bool, notifications: bool,
                                     check_interval_minutes: int = 1440,
                                     channel: str = "stable", auto_install=None):
        return await asyncio.get_running_loop().run_in_executor(
            None,
            self.update_manager.set_preferences,
            auto_check,
            notifications,
            check_interval_minutes,
            channel,
            auto_install,
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
