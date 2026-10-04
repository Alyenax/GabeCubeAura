from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from signalbar.arbiter import Arbiter
from signalbar.arbiter.guard import ManualClock
from signalbar.models import GameState, ProviderOutput, normalize_frame
from signalbar.providers.screen_sync import (
    CAPTURE_PROCESS_MARKER,
    CAPTURE_HEIGHT,
    CAPTURE_WIDTH,
    SESSION_RESTART_SETTLE_SECONDS,
    ScreenCaptureService,
    ScreenSyncProcessor,
    ScreenSyncProvider,
)
from signalbar.providers.events import RED
from signalbar.settings import SettingsStore
from signalbar.backend import Engine


BLACK = normalize_frame([(0, 0, 0)] * 17)


def bgrx_frame(pixel_at):
    raw = bytearray()
    for row in range(CAPTURE_HEIGHT):
        for column in range(CAPTURE_WIDTH):
            red, green, blue = pixel_at(row, column)
            raw.extend((blue, green, red, 0))
    return bytes(raw)


class FakeCapture:
    def __init__(self, clock, frame):
        self.clock = clock
        self.frame = frame
        self.sequence = 1
        self.sampled_at = clock()
        self.active = False

    def set_active(self, active):
        self.active = bool(active)

    def stop(self):
        self.active = False

    def latest(self):
        return self.frame, self.sequence, self.sampled_at

    def status(self):
        return {
            "phase": "capturing" if self.active else "off",
            "error": "",
            "node_id": 42,
            "node_name": "Gamescope",
            "conflicting_consumers": 0,
            "frame_age_s": max(0, self.clock() - self.sampled_at),
            "frames_per_second": 10.0,
        }


VALUES = {
    "screen_sync_style": "panorama",
    "screen_sync_brightness": 255,
    "screen_sync_reactivity": "balanced",
    "screen_sync_colour_intensity": "natural",
    "screen_sync_black_threshold": 8,
    "screen_sync_ignore_black_bars": True,
}


class ScreenSyncProcessorTests(unittest.TestCase):
    def test_panorama_preserves_left_and_right_colours(self):
        raw = bgrx_frame(lambda _row, column: (255, 0, 0) if column < 17 else (0, 0, 255))
        frame = ScreenSyncProcessor().process(raw, brightness=255)
        self.assertEqual(len(frame), 17)
        self.assertGreater(frame[0][0], 240)
        self.assertLess(frame[0][2], 10)
        self.assertGreater(frame[-1][2], 240)
        self.assertLess(frame[-1][0], 10)

    def test_ambient_repeats_one_global_colour(self):
        raw = bgrx_frame(lambda _row, column: (240, 30, 0) if column < 17 else (0, 30, 240))
        frame = ScreenSyncProcessor().process(raw, style="ambient", brightness=255)
        self.assertEqual(len(set(frame)), 1)
        self.assertGreater(frame[0][0], 100)
        self.assertGreater(frame[0][2], 100)

    def test_audio_palette_keeps_the_raw_gamescope_sample(self):
        processor = ScreenSyncProcessor()
        raw = bgrx_frame(lambda row, column: (row * 10, column * 7, 90))
        processor.process(raw, style="ambient", brightness=34)
        self.assertEqual(len(processor.palette_samples), CAPTURE_WIDTH * CAPTURE_HEIGHT)
        self.assertEqual(processor.palette_samples[0], (0, 0, 90))
        self.assertEqual(processor.palette_samples[-1], (170, 231, 90))
        processor.reset()
        self.assertEqual(processor.palette_samples, ())

    def test_black_bars_are_only_ignored_after_three_consistent_frames(self):
        raw = bgrx_frame(
            lambda row, _column: (0, 0, 0) if row < 3 or row >= CAPTURE_HEIGHT - 2 else (0, 200, 40)
        )
        processor = ScreenSyncProcessor()
        processor.process(raw)
        processor.process(raw)
        processor.process(raw)
        self.assertEqual(processor.crop, (3, 2))

    def test_three_black_frames_force_immediate_black(self):
        processor = ScreenSyncProcessor()
        bright = bgrx_frame(lambda _row, _column: (255, 255, 255))
        dark = bgrx_frame(lambda _row, _column: (0, 0, 0))
        processor.process(bright, brightness=255, reactivity="calm")
        processor.process(dark, brightness=255, reactivity="calm")
        processor.process(dark, brightness=255, reactivity="calm")
        frame = processor.process(dark, brightness=255, reactivity="calm")
        self.assertEqual(frame, BLACK)

    def test_bad_frame_size_is_rejected(self):
        with self.assertRaises(ValueError):
            ScreenSyncProcessor().process(b"short")


class ScreenCaptureDiscoveryTests(unittest.TestCase):
    def test_orphan_scan_matches_only_exact_gabecubeaura_gstreamer_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = {
                "101": ["/usr/bin/gst-launch-1.0", "pipewiresrc", CAPTURE_PROCESS_MARKER],
                "102": ["/usr/bin/gst-launch-1.0", "pipewiresrc", "client-name=Other-App"],
                "103": ["/usr/bin/python3", CAPTURE_PROCESS_MARKER],
            }
            for pid, command in commands.items():
                process = root / pid
                process.mkdir()
                (process / "cmdline").write_bytes(b"\0".join(item.encode() for item in command) + b"\0")
            self.assertEqual(sorted(ScreenCaptureService._marked_capture_pids(str(root))), [101])

    def test_orphan_cleanup_terminates_only_marked_capture(self):
        service = ScreenCaptureService()
        with patch.object(service, "_marked_capture_pids", side_effect=[[101, 102], []]), \
                patch("signalbar.providers.screen_sync.os.kill") as kill, \
                patch.object(service, "_wait"):
            self.assertEqual(service._cleanup_orphan_captures(), 2)
        self.assertEqual(
            [call.args for call in kill.call_args_list],
            [(101, 15), (102, 15)],
        )
        self.assertEqual(service.status()["orphan_processes_cleaned"], 2)

    def test_capture_process_starts_in_a_dedicated_session(self):
        commands = []

        class ExitedProcess:
            def __init__(self):
                self.stdout = tempfile.TemporaryFile()
                self.stderr = tempfile.TemporaryFile()

            def poll(self):
                return 1

        process = ExitedProcess()

        def popen(command, **kwargs):
            commands.append((command, kwargs))
            return process

        service = ScreenCaptureService(popen=popen)
        service._active = True
        with patch("signalbar.providers.screen_sync.shutil.which",
                   return_value="/usr/bin/gst-launch-1.0"), \
                patch.object(service, "_cleanup_orphan_captures", return_value=0), \
                patch.object(service, "_discover_gamescope_node",
                             return_value=("/run/user/1000", (91, "gamescope"), [])), \
                patch.object(service, "_command_for_runtime",
                             side_effect=lambda command, _runtime: (command, "deck (uid 1000)")), \
                patch.object(service, "_wait", side_effect=lambda _seconds: service._stop.set()):
            service._supervise()
        process.stdout.close()
        process.stderr.close()
        self.assertTrue(commands[0][1]["start_new_session"])

    def test_failed_capture_is_released_before_retry_wait(self):
        events = []

        class FailedProcess:
            def __init__(self):
                self.stdout = tempfile.TemporaryFile()
                self.stderr = tempfile.TemporaryFile()

            def poll(self):
                return 1

        process = FailedProcess()
        service = ScreenCaptureService(popen=lambda *_args, **_kwargs: process)
        service._active = True

        def terminate(target):
            if target is None:
                return
            self.assertIs(target, process)
            events.append("release")

        def stop_after_wait(_seconds):
            events.append("wait")
            service._stop.set()

        with patch("signalbar.providers.screen_sync.shutil.which",
                   return_value="/usr/bin/gst-launch-1.0"), \
                patch.object(service, "_cleanup_orphan_captures", return_value=0), \
                patch.object(service, "_discover_gamescope_node",
                             return_value=("/run/user/1000", (91, "gamescope"), [])), \
                patch.object(service, "_command_for_runtime",
                             side_effect=lambda command, _runtime: (command, "deck (uid 1000)")), \
                patch.object(service, "_terminate_process", side_effect=terminate), \
                patch.object(service, "_wait", side_effect=stop_after_wait):
            service._supervise()

        process.stdout.close()
        process.stderr.close()
        self.assertEqual(events, ["release", "wait"])
        status = service.status()
        self.assertEqual(status["capture_sessions_released"], 1)
        self.assertTrue(status["last_release_error"])

    def test_established_capture_loss_waits_for_session_to_settle(self):
        class RunningProcess:
            def __init__(self):
                self.stdout = tempfile.TemporaryFile()
                self.stderr = tempfile.TemporaryFile()
                self.stdout.write(bytes(CAPTURE_WIDTH * CAPTURE_HEIGHT * 4))
                self.stdout.seek(0)

            def poll(self):
                return None

        ticks = [0.0]

        def clock():
            ticks[0] += 0.4
            return ticks[0]

        process = RunningProcess()
        service = ScreenCaptureService(clock=clock, popen=lambda *_args, **_kwargs: process)
        service._active = True
        waits = []

        def stop_after_wait(seconds):
            waits.append(seconds)
            service._stop.set()

        with patch("signalbar.providers.screen_sync.shutil.which",
                   return_value="/usr/bin/gst-launch-1.0"), \
                patch.object(service, "_cleanup_orphan_captures", return_value=0), \
                patch.object(service, "_discover_gamescope_node",
                             return_value=("/run/user/1000", (91, "gamescope"), [])), \
                patch.object(service, "_command_for_runtime",
                             side_effect=lambda command, _runtime: (command, "deck (uid 1000)")), \
                patch.object(service, "_terminate_process"), \
                patch.object(service, "_wait", side_effect=stop_after_wait):
            service._supervise()

        process.stdout.close()
        process.stderr.close()
        self.assertTrue(waits)
        self.assertGreaterEqual(waits[-1], SESSION_RESTART_SETTLE_SECONDS)
        self.assertEqual(service.status()["phase"], "waiting")
        self.assertEqual(service._selector_mode, "target-object")
        self.assertEqual(service.status()["capture_sessions_released"], 1)

    def test_compatibility_retry_survives_pipewire_disappearing_during_session_change(self):
        service = ScreenCaptureService()
        service._active = True
        service._selector_mode = "target-object-compat"

        def stop_after_error(_seconds):
            service._stop.set()

        with patch("signalbar.providers.screen_sync.shutil.which",
                   return_value="/usr/bin/gst-launch-1.0"), \
                patch.object(service, "_discover_gamescope_node",
                             side_effect=RuntimeError("PipeWire session was not found")), \
                patch.object(service, "_wait", side_effect=stop_after_error):
            service._supervise()

        self.assertEqual(service.status()["phase"], "error")
        self.assertEqual(service.status()["error"], "PipeWire session was not found")
        self.assertEqual(service._selector_mode, "target-object")

    def test_failed_named_selectors_reach_numeric_node_fallback(self):
        commands = []
        processes = []

        class ExitedProcess:
            def __init__(self):
                self.stdout = tempfile.TemporaryFile()
                self.stderr = tempfile.TemporaryFile()

            def poll(self):
                return 1

        def popen(command, **_kwargs):
            commands.append(command)
            process = ExitedProcess()
            processes.append(process)
            return process

        service = ScreenCaptureService(popen=popen)
        service._active = True
        waits = []

        def stop_after_all_selectors(seconds):
            waits.append(seconds)
            if len(waits) == 3:
                service._stop.set()

        with patch("signalbar.providers.screen_sync.shutil.which",
                   return_value="/usr/bin/gst-launch-1.0"), \
                patch.object(service, "_cleanup_orphan_captures", return_value=0) as cleanup, \
                patch.object(service, "_discover_gamescope_node",
                             return_value=("/run/user/1000", (91, "gamescope"), [])), \
                patch.object(service, "_command_for_runtime",
                             side_effect=lambda command, _runtime: (command, "deck (uid 1000)")), \
                patch.object(service, "_wait", side_effect=stop_after_all_selectors):
            service._supervise()

        for process in processes:
            process.stdout.close()
            process.stderr.close()

        self.assertEqual(len(commands), 3)
        self.assertIn("target-object=gamescope", commands[0])
        self.assertIn("keepalive-time=33", commands[0])
        self.assertIn("target-object=gamescope", commands[1])
        self.assertNotIn("keepalive-time=33", commands[1])
        self.assertIn("path=91", commands[2])
        self.assertEqual(service.status()["capture_selector"], "legacy node 91")
        self.assertEqual(cleanup.call_count, 1)
        self.assertEqual(waits[:2], [0.1, 0.1])
        self.assertGreaterEqual(waits[2], SESSION_RESTART_SETTLE_SECONDS)

    def test_stale_numeric_selector_restarts_full_sequence_without_a_node(self):
        commands = []
        processes = []

        class ExitedProcess:
            def __init__(self):
                self.stdout = tempfile.TemporaryFile()
                self.stderr = tempfile.TemporaryFile()

            def poll(self):
                return 1

        def popen(command, **_kwargs):
            commands.append(command)
            process = ExitedProcess()
            processes.append(process)
            return process

        service = ScreenCaptureService(popen=popen)
        service._active = True
        service._selector_mode = "path"
        waits = 0

        def stop_after_named_sequence(_seconds):
            nonlocal waits
            waits += 1
            if waits == 2:
                service._stop.set()

        with patch("signalbar.providers.screen_sync.shutil.which",
                   return_value="/usr/bin/gst-launch-1.0"), \
                patch.object(service, "_discover_gamescope_node",
                             return_value=("/run/user/1000", None, [])), \
                patch.object(service, "_command_for_runtime",
                             side_effect=lambda command, _runtime: (command, "deck (uid 1000)")), \
                patch.object(service, "_wait", side_effect=stop_after_named_sequence):
            service._supervise()

        for process in processes:
            process.stdout.close()
            process.stderr.close()

        self.assertEqual(len(commands), 2)
        self.assertIn("target-object=gamescope", commands[0])
        self.assertIn("keepalive-time=33", commands[0])
        self.assertIn("target-object=gamescope", commands[1])
        self.assertNotIn("keepalive-time=33", commands[1])
        self.assertEqual(service._selector_mode, "target-object")

    def test_logically_active_capture_restarts_after_old_supervisor_exits(self):
        class FakeThread:
            instances = []

            def __init__(self, **_kwargs):
                self.alive = False
                self.started = False
                self.__class__.instances.append(self)

            def is_alive(self):
                return self.alive

            def start(self):
                self.started = True
                self.alive = True

        service = ScreenCaptureService()
        with patch("signalbar.providers.screen_sync.threading.Thread", FakeThread):
            service.set_active(True)
            self.assertEqual(len(FakeThread.instances), 1)
            self.assertTrue(FakeThread.instances[0].started)

            # Simulate the old capture supervisor completing after a forced
            # game-transition stop. The logical request remains active.
            FakeThread.instances[0].alive = False
            service.set_active(True)

        self.assertEqual(len(FakeThread.instances), 2)
        self.assertTrue(FakeThread.instances[1].started)

    def test_root_backend_runs_pipewire_clients_as_runtime_owner(self):
        with patch("signalbar.providers.screen_sync.os.geteuid", return_value=0), \
                patch("signalbar.providers.screen_sync.pwd.getpwuid",
                      return_value=SimpleNamespace(pw_name="deck")), \
                patch("signalbar.providers.screen_sync.shutil.which",
                      return_value="/usr/bin/runuser"):
            command, identity = ScreenCaptureService._command_for_runtime(
                ["/usr/bin/pw-dump"], "/run/user/1000",
            )
        self.assertEqual(command, [
            "/usr/bin/runuser", "-u", "deck", "--", "/usr/bin/pw-dump",
        ])
        self.assertEqual(identity, "deck (uid 1000)")

    def test_non_root_backend_keeps_direct_pipewire_command(self):
        with patch("signalbar.providers.screen_sync.os.geteuid", return_value=1000), \
                patch("signalbar.providers.screen_sync.pwd.getpwuid",
                      return_value=SimpleNamespace(pw_name="deck")):
            command, identity = ScreenCaptureService._command_for_runtime(
                ["/usr/bin/pw-dump"], "/run/user/1000",
            )
        self.assertEqual(command, ["/usr/bin/pw-dump"])
        self.assertEqual(identity, "deck (uid 1000)")

    def test_gamescope_video_source_wins_over_camera(self):
        dump = [
            {"id": 3, "type": "PipeWire:Interface:Node", "info": {"props": {
                "media.class": "Video/Source", "node.name": "v4l2-camera"}}},
            {"id": 9, "type": "PipeWire:Interface:Node", "info": {"props": {
                "media.class": "Video/Source", "node.name": "gamescope",
                "node.description": "Gamescope Video"}}},
        ]
        self.assertEqual(ScreenCaptureService.find_gamescope_node(dump), (9, "gamescope Gamescope Video"))

    def test_exact_gamescope_node_does_not_require_video_metadata(self):
        dump = [
            {"id": 12, "type": "PipeWire:Interface:Node", "info": {"props": {
                "node.name": "gamescope"}}},
        ]
        self.assertEqual(ScreenCaptureService.find_gamescope_node(dump), (12, "gamescope"))

    def test_discovery_checks_every_pipewire_session(self):
        service = ScreenCaptureService()
        dumps = {
            "/run/user/0": [
                {"id": 3, "type": "PipeWire:Interface:Node", "info": {"props": {
                    "media.class": "Audio/Sink", "node.name": "desktop-audio"}}},
            ],
            "/run/user/1000": [
                {"id": 9, "type": "PipeWire:Interface:Node", "info": {"props": {
                    "node.name": "gamescope"}}},
            ],
        }
        with patch.object(service, "_runtime_dirs", return_value=list(dumps)), \
                patch.object(service, "_pipewire_dump", side_effect=lambda runtime: dumps[runtime]):
            runtime, node, dump = service._discover_gamescope_node()
        self.assertEqual(runtime, "/run/user/1000")
        self.assertEqual(node, (9, "gamescope"))
        self.assertIs(dump, dumps["/run/user/1000"])
        self.assertEqual(service.status()["runtime_dir"], "/run/user/1000")

    def test_accessible_pipewire_session_can_try_gamescope_name_without_enumerated_node(self):
        service = ScreenCaptureService()
        dump = [
            {"id": 3, "type": "PipeWire:Interface:Node", "info": {"props": {
                "media.class": "Audio/Sink", "node.name": "desktop-audio"}}},
        ]
        with patch.object(service, "_runtime_dirs", return_value=["/run/user/1000"]), \
                patch.object(service, "_pipewire_dump", return_value=dump):
            runtime, node, discovered = service._discover_gamescope_node()
        self.assertEqual(runtime, "/run/user/1000")
        self.assertIsNone(node)
        self.assertIs(discovered, dump)
        status = service.status()
        self.assertEqual(status["node_name"], "gamescope (direct name)")
        self.assertIn("trying target-object=gamescope directly", status["discovery_detail"])

    def test_direct_name_fallback_prefers_gaming_user_over_root_pipewire(self):
        service = ScreenCaptureService()
        with patch.object(service, "_runtime_dirs",
                          return_value=["/run/user/0", "/run/user/1000"]), \
                patch.object(service, "_pipewire_dump",
                             side_effect=lambda runtime: [{"runtime": runtime}]), \
                patch("signalbar.providers.screen_sync.pwd.getpwuid",
                      side_effect=lambda uid: SimpleNamespace(
                          pw_name="root" if uid == 0 else "deck",
                      )):
            runtime, node, _dump = service._discover_gamescope_node()
        self.assertEqual(runtime, "/run/user/1000")
        self.assertIsNone(node)

    def test_capture_command_prefers_current_gamescope_name_with_legacy_fallback(self):
        current = ScreenCaptureService._capture_command("gst-launch-1.0", 91)
        self.assertIn("target-object=gamescope", current)
        self.assertIn("client-name=GabeCubeAura-Screen-Sync", current)
        self.assertIn("keepalive-time=33", current)
        self.assertNotIn("path=91", current)
        compatibility = ScreenCaptureService._capture_command(
            "gst-launch-1.0", None, "target-object-compat",
        )
        self.assertIn("target-object=gamescope", compatibility)
        self.assertNotIn("keepalive-time=33", compatibility)
        legacy = ScreenCaptureService._capture_command("gst-launch-1.0", 91, "path")
        self.assertIn("path=91", legacy)
        self.assertNotIn("target-object=gamescope", legacy)
        self.assertNotIn("keepalive-time=33", legacy)

    def test_consumer_count_only_includes_links_from_selected_node(self):
        dump = [
            {"type": "PipeWire:Interface:Link", "info": {"state": "active", "props": {
                "link.output.node": 9}}},
            {"type": "PipeWire:Interface:Link", "info": {"state": "error", "props": {
                "link.output.node": 9}}},
            {"type": "PipeWire:Interface:Link", "info": {"state": "active", "props": {
                "link.output.node": 3}}},
        ]
        self.assertEqual(ScreenCaptureService.count_consumers(dump, 9), 1)


class ScreenSyncProviderTests(unittest.TestCase):
    def test_customization_fallback_is_suppressed_during_pending_launch_transition(self):
        should_fallback = Engine._screen_sync_fallback_should_run
        self.assertTrue(should_fallback(True, True, None, False))
        self.assertFalse(should_fallback(True, True, None, True))
        self.assertFalse(should_fallback(True, True, BLACK, False))
        self.assertFalse(should_fallback(False, True, None, False))

    def test_engine_keeps_read_only_capture_warm_during_led_priority(self):
        values = {"signalbar_enabled": True, "stripmine_priority_screen_sync": "signalbar"}
        should_run = Engine._screen_sync_should_run
        self.assertTrue(should_run(values, True, False, True, False))
        self.assertFalse(should_run(values, False, False, True, False))
        self.assertTrue(should_run(values, True, True, True, False))
        self.assertTrue(should_run(values, True, False, False, False))
        self.assertTrue(should_run(
            values, True, False, False, False, steam_priority=True,
        ))
        self.assertFalse(should_run(values, True, False, True, False, recording=True))
        self.assertTrue(should_run(values, True, False, False, True))
        values["stripmine_priority_screen_sync"] = "stripmine"
        self.assertFalse(should_run(values, True, False, True, True))

    def test_audio_screen_sync_palette_requests_capture_without_a_running_game(self):
        values = {
            "audio_sync_style": "slow-prism",
            "audio_sync_palette": "screen-sync",
        }
        self.assertTrue(Engine._audio_screen_capture_should_run(values, True))
        values["audio_sync_palette"] = "sapphire"
        self.assertFalse(Engine._audio_screen_capture_should_run(values, True))
        values["audio_sync_palette"] = "screen-sync"
        self.assertFalse(Engine._audio_screen_capture_should_run(values, False))

    def test_screen_sync_settings_validate_and_route_per_game(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(str(Path(directory) / "settings.json"))
            values = store.update({
                "game_display": "screen_sync",
                "screen_sync_style": "bad",
                "screen_sync_brightness": 2,
                "screen_sync_reactivity": "fast",
                "screen_sync_colour_intensity": "vivid",
                "screen_sync_black_threshold": 80,
                "screen_sync_screensaver_enabled": 1,
            })
            self.assertEqual(values["screen_sync_style"], "panorama")
            self.assertEqual(values["screen_sync_brightness"], 34)
            self.assertEqual(values["screen_sync_reactivity"], "fast")
            self.assertEqual(values["screen_sync_colour_intensity"], "vivid")
            self.assertEqual(values["screen_sync_black_threshold"], 32)
            self.assertTrue(values["screen_sync_screensaver_enabled"])
            self.assertEqual(store.display_for(42)["mode"], "screen_sync")
            store.update_display(42, "artwork")
            self.assertEqual(store.display_for(42)["mode"], "artwork")

    def test_provider_processes_only_fresh_frames_and_exposes_palette(self):
        clock = ManualClock(10)
        capture = FakeCapture(clock, bgrx_frame(lambda _row, _column: (10, 180, 240)))
        provider = ScreenSyncProvider(capture=capture, clock=clock)
        provider.set_active(True)
        output = provider.output(VALUES)
        self.assertEqual(output.provider, "screen-sync")
        self.assertEqual(len(output.frame), 17)
        self.assertEqual(len(provider.status()["colors"]), 17)
        clock.advance(1.1)
        self.assertIsNone(provider.output(VALUES).frame)
        provider.set_active(False)
        self.assertFalse(capture.active)

    def test_arbiter_treats_screen_sync_as_a_permanent_game_display(self):
        output = ProviderOutput("screen-sync", normalize_frame([(10, 20, 30)] * 17), "live")
        none = ProviderOutput("none", None, "none")
        result = Arbiter().choose(
            mode="screen_sync", guard_allows=True, game=GameState(42, "Game"),
            performance=none, artwork=none, idle=none, screen_sync_base=output,
        )
        self.assertEqual(result.provider, "screen-sync")

    def test_screensaver_screen_sync_replaces_every_permanent_home_display(self):
        frame = lambda provider: ProviderOutput(
            provider, normalize_frame([(10, 20, 30)] * 17), provider,
        )
        none = ProviderOutput("none", None, "none")
        base = {
            "mode": "screen_sync",
            "guard_allows": True,
            "game": GameState(0, ""),
            "performance": none,
            "artwork": none,
            "idle": none,
            "screen_sync_base": frame("screen-sync"),
        }
        permanent_displays = (
            {"customization_base": frame("customization:steady")},
            {"performance": frame("performance")},
            {"weather_base": frame("weather:home")},
            {"controller_base": frame("controller:battery")},
            {"audio_sync_base": frame("audio-sync:spectrum")},
        )
        for display in permanent_displays:
            with self.subTest(display=next(iter(display))):
                result = Arbiter().choose(**{**base, **display})
                self.assertEqual(result.provider, "screen-sync")

    def test_screensaver_screen_sync_keeps_temporary_layers_above_it(self):
        frame = lambda provider: ProviderOutput(
            provider, normalize_frame([(10, 20, 30)] * 17), provider,
        )
        none = ProviderOutput("none", None, "none")
        base = {
            "mode": "screen_sync",
            "guard_allows": True,
            "game": GameState(0, ""),
            "performance": none,
            "artwork": none,
            "idle": none,
            "screen_sync_base": frame("screen-sync"),
        }
        self.assertEqual(
            Arbiter().choose(**base, event=frame("event:notification")).provider,
            "event:notification",
        )
        self.assertEqual(
            Arbiter().choose(**base, launch_artwork=frame("launch-artwork")).provider,
            "launch-artwork",
        )
        self.assertEqual(
            Arbiter().choose(**base, weather_base=frame("weather:preview")).provider,
            "weather:preview",
        )

    def test_customization_fallback_keeps_recording_marker(self):
        none = ProviderOutput("none", None, "none")
        fallback = ProviderOutput("customization:steady", normalize_frame([(4, 8, 12)] * 17), "fallback")
        result = Arbiter().choose(
            mode="screen_sync", guard_allows=True, game=GameState(42, "Game"),
            performance=none, artwork=none, idle=none, screen_sync_base=none,
            screen_sync_fallback=fallback, recording_marker=True,
            recording_marker_isolation=True,
        )
        self.assertTrue(result.provider.startswith("customization:steady+recording"))
        self.assertEqual(result.frame[8], RED)
        self.assertEqual(result.frame[7], (0, 0, 0))
        self.assertEqual(result.frame[9], (0, 0, 0))

    def test_steam_system_priority_blocks_events_and_fallback(self):
        frame = ProviderOutput("event:notification", normalize_frame([(20, 30, 40)] * 17), "event")
        result = Arbiter().choose(
            mode="screen_sync", guard_allows=False, game=GameState(42, "Game"),
            performance=frame, artwork=frame, idle=frame, event=frame,
            screen_sync_base=frame, screen_sync_fallback=frame, steam_priority=True,
        )
        self.assertEqual(result.provider, "valve")
        self.assertIsNone(result.frame)


if __name__ == "__main__":
    unittest.main()
