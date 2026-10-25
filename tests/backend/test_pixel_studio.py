import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from signalbar.pixel_studio import MAX_LOG_BYTES, PixelStudioManager


class FakeLogger:
    def info(self, message):
        pass

    def warning(self, message):
        pass


class HealthProbe:
    def __init__(self):
        self.running = False
        self.version = ""

    def __call__(self):
        return {"running": self.running, "version": self.version}


class FakeProcess:
    def poll(self):
        return None


class JsonResponse:
    def __init__(self, value, status=200):
        self.value = value
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return json.dumps(self.value).encode("utf-8")


def write_embedded_components(plugin: Path, version="1.4.1-lab.9"):
    components = plugin / "components"
    service = components / "faceplate-service"
    studio = components / "pixel-studio"
    service.mkdir(parents=True)
    studio.mkdir(parents=True)
    for component, target in (("faceplate-service", service), ("pixel-studio", studio)):
        (target / "component.json").write_text(json.dumps({
            "id": component, "product": "GabeCubeAura", "version": version,
        }), encoding="utf-8")
    (service / "server.py").write_text("print('service')\n", encoding="utf-8")
    (service / "launch-pixel-studio.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (studio / "index.html").write_text("<title>Studio</title>\n", encoding="utf-8")
    (studio / "app.js").write_text("// studio\n", encoding="utf-8")


class PixelStudioManagerTests(unittest.TestCase):
    def test_current_game_is_shared_with_the_loopback_studio(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            manager = PixelStudioManager(
                str(base / "plugin"), str(base / "home/deck"),
                "1.4.1-lab.9", FakeLogger(),
                health_probe=lambda: {"running": False, "version": ""},
            )
            current = manager.set_current_game({"appid": 620, "title": "Portal 2"})
            stored = json.loads(manager.game_state_path.read_text(encoding="utf-8"))
        self.assertEqual(current, {"appid": 620, "title": "Portal 2"})
        self.assertEqual(stored["appid"], 620)

    def test_bootstrap_repairs_components_without_a_desktop_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            plugin, home = base / "plugin", base / "home/deck"
            write_embedded_components(plugin)
            manager = PixelStudioManager(
                str(plugin), str(home), "1.4.1-lab.9", FakeLogger(),
                health_probe=lambda: {"running": False, "version": ""},
            )
            status = manager.ensure_installed()
            self.assertTrue(status["installed"])
            self.assertFalse(status["desktop_launcher"])
            launcher = home / ".local/share/gabecubeaura/components/faceplate-service/launch-pixel-studio.sh"
            self.assertTrue(launcher.stat().st_mode & 0o111)
            desktop = home / ".local/share/applications/gabecubeaura-pixel-studio.desktop"
            self.assertFalse(desktop.exists())
            installed_app = home / ".local/share/gabecubeaura/components/pixel-studio/app.js"
            installed_app.write_text("damaged\n", encoding="utf-8")
            manager.ensure_installed(True)
            self.assertEqual(installed_app.read_text(encoding="utf-8"), "// studio\n")

    def test_existing_install_does_not_repeat_recursive_permission_walk(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            plugin, home = base / "plugin", base / "home/deck"
            write_embedded_components(plugin)
            manager = PixelStudioManager(
                str(plugin), str(home), "1.4.1-lab.9", FakeLogger(),
                health_probe=lambda: {"running": False, "version": ""},
            )
            manager.ensure_installed()
            with patch.object(manager, "_set_permissions") as permissions:
                status = manager.ensure_installed()
            self.assertTrue(status["installed"])
            permissions.assert_not_called()

    def test_standalone_start_is_disabled_and_never_spawns_a_service(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            plugin, home = base / "plugin", base / "home/deck"
            write_embedded_components(plugin)
            launches = []
            manager = PixelStudioManager(
                str(plugin), str(home), "1.4.1-lab.9", FakeLogger(),
                popen=lambda *args, **kwargs: launches.append((args, kwargs)),
                health_probe=lambda: {"running": False, "version": ""},
            )
            status = manager.start()
            self.assertFalse(status["service_running"])
            self.assertFalse(status["started"])
            self.assertFalse(status["standalone_enabled"])
            self.assertIn("retired", status["error"])
            self.assertEqual(launches, [])

    def test_running_service_with_an_old_version_is_not_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            plugin, home = base / "plugin", base / "home/deck"
            write_embedded_components(plugin)
            launches = []
            manager = PixelStudioManager(
                str(plugin), str(home), "1.4.1-lab.9", FakeLogger(),
                popen=lambda *args, **kwargs: launches.append((args, kwargs)),
                health_probe=lambda: {"running": True, "version": "1.4.1-lab.8"},
            )
            status = manager.start()
            self.assertEqual(launches, [])
            self.assertIn("retired", status["error"])
            self.assertEqual(status["service_version"], "")

    def test_disable_removes_launcher_and_stops_only_exact_legacy_service(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            plugin, home, proc = base / "plugin", base / "home/deck", base / "proc"
            manager = PixelStudioManager(
                str(plugin), str(home), "1.4.1-lab.9", FakeLogger(), proc_root=proc,
            )
            manager.desktop_path.parent.mkdir(parents=True)
            manager.desktop_path.write_text("legacy\n", encoding="utf-8")
            for component in ("faceplate-service", "pixel-studio"):
                (manager.component_root / component).mkdir(parents=True)
            exact = proc / "222"
            unrelated = proc / "333"
            exact.mkdir(parents=True)
            unrelated.mkdir(parents=True)
            server = str((manager.component_root / "faceplate-service/server.py").resolve())
            (exact / "cmdline").write_bytes(
                b"/usr/bin/python3\0" + server.encode() + b"\0--studio\0/tmp/studio\0"
            )
            (unrelated / "cmdline").write_bytes(b"/usr/bin/python3\0/tmp/server.py\0")
            with patch("signalbar.pixel_studio.os.kill") as kill:
                status = manager.disable_standalone()
            self.assertFalse(manager.desktop_path.exists())
            self.assertFalse(manager.component_root.joinpath("faceplate-service").exists())
            self.assertFalse(manager.component_root.joinpath("pixel-studio").exists())
            self.assertFalse(status["standalone_enabled"])
            kill.assert_called_once_with(222, 15)

    def test_companion_log_is_rotated_before_a_new_service_start(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            manager = PixelStudioManager(
                str(base / "plugin"), str(base / "home/deck"),
                "1.4.1-lab.9", FakeLogger(),
            )
            manager.state_dir.mkdir(parents=True)
            log = manager.state_dir / "pixel-studio.log"
            log.write_bytes(b"x" * MAX_LOG_BYTES)
            selected = manager._prepare_log_path()
            self.assertEqual(selected, log)
            self.assertFalse(log.exists())
            self.assertEqual(
                (manager.state_dir / "pixel-studio.previous.log").stat().st_size,
                MAX_LOG_BYTES,
            )

    def test_brightness_is_clamped_without_starting_the_retired_service(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            plugin, home = base / "plugin", base / "home/deck"
            write_embedded_components(plugin)
            requests = []

            def opener(request, timeout=0):
                requests.append((request, timeout))
                return JsonResponse({"ok": True, "brightness": 100}, status=202)

            manager = PixelStudioManager(
                str(plugin), str(home), "1.4.1-lab.9", FakeLogger(),
                health_probe=lambda: {"running": True, "version": "1.4.1-lab.9"},
            )
            manager._popen = lambda *args, **kwargs: FakeProcess()
            manager.ensure_installed()
            with patch("signalbar.pixel_studio.urlopen", opener):
                status = manager.set_brightness(400)
            self.assertEqual(status["brightness"], 100)
            self.assertEqual(requests, [])


if __name__ == "__main__":
    unittest.main()
