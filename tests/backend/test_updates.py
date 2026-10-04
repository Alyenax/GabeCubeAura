import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import warnings
from zipfile import ZipFile, ZIP_DEFLATED, ZipInfo

from signalbar.settings import SettingsStore
from signalbar.update_helper import run_transaction
from signalbar.updates import (
    BETA_VERSION,
    LAB_VERSION,
    GitHubDeviceAuth,
    GitHubReleaseClient,
    PRIVATE_RELEASES_API_URL,
    RELEASES_API_URL,
    UpdateError,
    UpdateManager,
    _version_order,
    _version_tuple,
    validate_and_stage_archive,
)


def write_plugin(directory: Path, version: str, marker="healthy"):
    directory.mkdir(parents=True)
    (directory / "dist").mkdir()
    (directory / "main.py").write_text(f'MARKER = "{marker}"\n', encoding="utf-8")
    (directory / "plugin.json").write_text(
        json.dumps({"name": "GabeCubeAura", "author": "Alyenax"}), encoding="utf-8",
    )
    (directory / "package.json").write_text(
        json.dumps({"name": "gabecubeaura", "version": version}), encoding="utf-8",
    )
    (directory / "dist/index.js").write_text("export {};\n", encoding="utf-8")
    (directory / "LICENSE").write_text("fixture license\n", encoding="utf-8")
    backend = directory / "py_modules/signalbar"
    backend.mkdir(parents=True)
    (backend / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")


def write_archive(path: Path, version="1.1.0"):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "GabeCubeAura"
        write_plugin(root, version)
        with ZipFile(path, "w", ZIP_DEFLATED) as archive:
            for item in sorted(root.rglob("*")):
                if item.is_file():
                    archive.write(item, Path("GabeCubeAura") / item.relative_to(root))


class FakeClient:
    def __init__(self, archive: Path, version="1.1.0"):
        self.archive = archive
        self.digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.calls = []
        self.release = {
            "not_modified": False,
            "version": version,
            "tag": f"v{version}",
            "name": f"GabeCubeAura {version}",
            "notes": "Safe update",
            "html_url": f"https://github.com/Alyenax/GabeCubeAura/releases/tag/v{version}",
            "archive_name": f"GabeCubeAura-v{version}.zip",
            "archive_url": f"https://github.com/Alyenax/GabeCubeAura/releases/download/v{version}/GabeCubeAura-v{version}.zip",
            "archive_size": archive.stat().st_size,
            "archive_digest": self.digest,
            "checksums_url": f"https://github.com/Alyenax/GabeCubeAura/releases/download/v{version}/SHA256SUMS",
            "etag": '"fixture"',
        }

    def latest(self, installed_version, *, etag=""):
        self.calls.append((installed_version, etag))
        return dict(self.release)

    def read_checksum(self, release, installed_version):
        return self.digest

    def download_archive(self, release, destination, installed_version):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.archive.read_bytes())
        return self.digest


class ConditionalFakeClient(FakeClient):
    def latest(self, installed_version, *, etag=""):
        self.calls.append((installed_version, etag))
        if etag:
            return {"not_modified": True, "etag": etag}
        return dict(self.release)

class FakeLogger:
    def warning(self, message):
        pass


class FakePrivateAuth:
    def __init__(self, token="ghu_" + "p" * 24):
        self.token = token
        self.access_calls = 0
        self.disconnected = False

    def status(self):
        return {
            "private_auth_configured": True,
            "private_auth_state": "disconnected" if self.disconnected else "connected",
            "private_user_code": "",
            "private_verification_uri": "",
            "private_auth_expires_at": 0,
            "private_repository": "Alyenax/GabeCubeAura-Lab",
        }

    def access_token(self):
        self.access_calls += 1
        return self.token

    def disconnect(self):
        self.disconnected = True
        return self.status()


class FakeResponse:
    def __init__(self, payload: bytes, headers=None):
        self.payload = payload
        self.headers = headers or {}
        self.offset = 0

    def read(self, size=-1):
        if size < 0:
            size = len(self.payload) - self.offset
        chunk = self.payload[self.offset:self.offset + size]
        self.offset += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeService:
    def __init__(self, fail_start=False):
        self.running = True
        self.starts = 0
        self.stops = 0
        self.fail_start = fail_start

    def stop(self):
        self.stops += 1
        self.running = False

    def start(self):
        self.starts += 1
        if self.fail_start:
            raise OSError("start failed")
        self.running = True

    def active(self):
        return self.running

    def wait_inactive(self, timeout=20):
        return not self.running


def fake_exchange(first: Path, second: Path):
    temporary = first.parent / "GabeCubeAura.exchange-test"
    first.rename(temporary)
    second.rename(first)
    temporary.rename(second)


class UpdateTests(unittest.TestCase):
    def test_fresh_public_install_uses_stable_daily_checks_without_private_auth(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            settings = SettingsStore(str(base / "settings/config.json"))
            manager = UpdateManager(
                "1.3.2", settings, str(base / "runtime"),
                str(base / "plugins/GabeCubeAura"), FakeLogger(),
            )
            status = manager.status()
            self.assertEqual(status["channel"], "stable")
            self.assertEqual(status["check_interval_minutes"], 1440)
            self.assertEqual(status["private_auth_state"], "disconnected")
            self.assertFalse((base / "runtime/updates/private-auth.json").exists())

    def test_versions_require_stable_semver_but_accept_local_test_install(self):
        self.assertEqual(_version_tuple("v1.1.0"), (1, 1, 0))
        self.assertEqual(_version_tuple("1.0.99-test.1", allow_test=True), (1, 0, 99, -1, 1))
        self.assertEqual(_version_tuple("1.2.0-beta1", allow_test=True), (1, 2, 0, -2, 1))
        self.assertEqual(_version_tuple("1.2.0-beta.1", allow_test=True), (1, 2, 0, -2, 1))
        self.assertEqual(_version_tuple("1.3.2-lab.1", allow_test=True), (1, 3, 2, -1, 1))
        self.assertTrue(BETA_VERSION.fullmatch("1.2.0-beta3"))
        self.assertTrue(BETA_VERSION.fullmatch("1.2.0-beta.3"))
        self.assertTrue(LAB_VERSION.fullmatch("1.3.2-lab.1"))
        self.assertGreater(_version_order("1.2.0"),
                           _version_order("1.2.0-beta1", allow_test=True))
        self.assertLess(_version_order("1.1.0"),
                        _version_order("1.2.0-beta1", allow_test=True))
        for invalid in ("1.1", "1.1.0-beta", "01.1.0", "latest"):
            with self.assertRaises(UpdateError, msg=invalid):
                _version_tuple(invalid)

    def test_private_device_flow_stores_only_bounded_tokens_outside_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            clock = [1000]
            responses = [
                {
                    "device_code": "device-code-123", "user_code": "ABCD-EFGH",
                    "verification_uri": "https://github.com/login/device",
                    "expires_in": 900, "interval": 5,
                },
                {"error": "authorization_pending"},
                {
                    "access_token": "ghu_" + "a" * 24,
                    "expires_in": 28800,
                    "refresh_token": "ghr_" + "b" * 24,
                    "refresh_token_expires_in": 15897600,
                    "token_type": "bearer",
                },
            ]
            requests = []

            def opener(request, timeout=10):
                requests.append(request)
                return FakeResponse(json.dumps(responses.pop(0)).encode())

            path = Path(directory) / "runtime/updates/private-auth.json"
            auth = GitHubDeviceAuth(
                path, client_id="Iv1.fixtureclient123", repository_id=42,
                opener=opener, clock=lambda: clock[0],
            )
            started = auth.start()
            self.assertEqual(started["private_auth_state"], "pending")
            self.assertEqual(started["private_user_code"], "ABCD-EFGH")
            self.assertNotIn("device-code-123", json.dumps(started))
            self.assertEqual(auth.poll()["private_auth_state"], "pending")
            clock[0] += 5
            connected = auth.poll()
            self.assertEqual(connected["private_auth_state"], "connected")
            self.assertEqual(auth.access_token(), "ghu_" + "a" * 24)
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("user_code", persisted)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertIn("repository_id=42", requests[1].data.decode())
            self.assertNotIn("client_secret", requests[1].data.decode())
            auth.disconnect()
            self.assertFalse(path.exists())

    def test_private_release_client_accepts_only_lab_assets_through_api(self):
        digest = "c" * 64
        version = "1.3.2-lab.1"
        archive = f"GabeCubeAura-v{version}.zip"
        base = "https://api.github.com/repos/Alyenax/GabeCubeAura-Lab/releases/assets"
        release = {
            "tag_name": f"v{version}", "name": "Private lab", "body": "notes",
            "html_url": f"https://github.com/Alyenax/GabeCubeAura-Lab/releases/tag/v{version}",
            "draft": False, "prerelease": True,
            "assets": [
                {"name": archive, "url": f"{base}/101", "size": 100,
                 "digest": f"sha256:{digest}"},
                {"name": "SHA256SUMS", "url": f"{base}/102", "size": 100},
            ],
        }
        requests = []

        def opener(request, timeout=10):
            requests.append(request)
            if request.full_url.endswith("/102"):
                return FakeResponse(f"{digest}  {archive}\n".encode())
            return FakeResponse(json.dumps([release]).encode(), {"ETag": '"private"'})

        token = "ghu_" + "a" * 24
        client = GitHubReleaseClient(
            opener=opener, api_url=PRIVATE_RELEASES_API_URL,
            allow_prerelease=True, prerelease_kind="lab", include_stable=False,
            owner="Alyenax", repository="GabeCubeAura-Lab", token=token,
            private_assets=True,
        )
        result = client.latest("1.3.1")
        self.assertEqual(result["version"], version)
        self.assertEqual(result["archive_url"], f"{base}/101")
        self.assertEqual(client.read_checksum(result, "1.3.1"), digest)
        self.assertEqual(requests[0].full_url, PRIVATE_RELEASES_API_URL)
        self.assertEqual(requests[0].get_header("Authorization"), f"Bearer {token}")
        self.assertEqual(requests[1].get_header("Accept"), "application/octet-stream")

    def test_private_channel_uses_authenticated_lab_client_and_disconnects_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive = base / "lab.zip"
            write_archive(archive, "1.3.2-lab.1")
            settings = SettingsStore(str(base / "settings/config.json"))
            private_auth = FakePrivateAuth()
            lab_client = FakeClient(archive, "1.3.2-lab.1")
            manager = UpdateManager(
                "1.3.1", settings, str(base / "runtime"),
                str(base / "plugins/GabeCubeAura"), FakeLogger(),
                private_auth=private_auth,
            )

            with patch("signalbar.updates.GitHubReleaseClient", return_value=lab_client) as factory:
                status = manager.set_preferences(True, True, 60, "private")

            self.assertEqual(status["channel"], "private")
            self.assertEqual(status["phase"], "available")
            self.assertEqual(status["available_version"], "1.3.2-lab.1")
            self.assertEqual(private_auth.access_calls, 1)
            self.assertEqual(factory.call_args.kwargs["token"], private_auth.token)
            self.assertTrue(factory.call_args.kwargs["private_assets"])
            self.assertEqual(factory.call_args.kwargs["prerelease_kind"], "lab")
            self.assertFalse(factory.call_args.kwargs["include_stable"])

            disconnected = manager.disconnect_private_authorization()
            self.assertTrue(private_auth.disconnected)
            self.assertEqual(disconnected["phase"], "authorization_required")
            self.assertEqual(disconnected["available_version"], "")

    def test_github_client_accepts_only_expected_assets_and_prerelease_policy(self):
        digest = "a" * 64
        release = {
            "tag_name": "v1.1.0",
            "name": "GabeCubeAura 1.1.0",
            "body": "notes",
            "html_url": "https://github.com/Alyenax/GabeCubeAura/releases/tag/v1.1.0",
            "draft": False,
            "prerelease": False,
            "assets": [
                {
                    "name": "GabeCubeAura-v1.1.0.zip",
                    "browser_download_url": "https://github.com/Alyenax/GabeCubeAura/releases/download/v1.1.0/GabeCubeAura-v1.1.0.zip",
                    "size": 100,
                    "digest": f"sha256:{digest}",
                },
                {
                    "name": "SHA256SUMS",
                    "browser_download_url": "https://github.com/Alyenax/GabeCubeAura/releases/download/v1.1.0/SHA256SUMS",
                    "size": 100,
                },
            ],
        }
        def opener(request, timeout=10):
            if request.full_url.endswith("SHA256SUMS"):
                return FakeResponse(f"{digest}  GabeCubeAura-v1.1.0.zip\n".encode())
            return FakeResponse(json.dumps(release).encode(), {"ETag": '"release"'})
        client = GitHubReleaseClient(opener=opener)
        result = client.latest("1.0.0")
        self.assertEqual(result["version"], "1.1.0")
        self.assertEqual(client.read_checksum(result, "1.0.0"), digest)
        release["prerelease"] = True
        with self.assertRaises(UpdateError):
            client.latest("1.0.0")
        release["prerelease"] = False
        test_client = GitHubReleaseClient(opener=opener, allow_prerelease=True)
        self.assertEqual(test_client.latest("1.0.99-test.1")["version"], "1.1.0")

    def test_beta_channel_selects_the_newest_beta_or_stable_release(self):
        digest = "b" * 64

        def release(version, prerelease):
            tag = f"v{version}"
            archive = f"GabeCubeAura-v{version}.zip"
            base = f"https://github.com/Alyenax/GabeCubeAura/releases"
            return {
                "tag_name": tag, "name": tag, "body": "notes", "draft": False,
                "prerelease": prerelease, "html_url": f"{base}/tag/{tag}",
                "assets": [
                    {"name": archive, "browser_download_url": f"{base}/download/{tag}/{archive}",
                     "size": 100, "digest": f"sha256:{digest}"},
                    {"name": "SHA256SUMS", "browser_download_url": f"{base}/download/{tag}/SHA256SUMS",
                     "size": 100},
                ],
            }

        payload = [release("1.2.0-beta2", True), release("1.1.0", False)]

        def opener(request, timeout=10):
            self.assertEqual(request.full_url, RELEASES_API_URL)
            return FakeResponse(json.dumps(payload).encode(), {"ETag": '"beta-list"'})

        client = GitHubReleaseClient(
            opener=opener, api_url=RELEASES_API_URL, allow_prerelease=True,
        )
        self.assertEqual(client.latest("1.1.0")["version"], "1.2.0-beta2")
        payload.insert(0, release("1.2.0", False))
        self.assertEqual(client.latest("1.1.0")["version"], "1.2.0")

    def test_valid_archive_is_staged_and_manifest_version_is_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive = base / "valid.zip"
            write_archive(archive)
            root = validate_and_stage_archive(archive, base / "stage", "1.1.0")
            self.assertEqual(root.name, "GabeCubeAura")
            self.assertTrue((root / "dist/index.js").is_file())
            with self.assertRaises(UpdateError):
                validate_and_stage_archive(archive, base / "wrong", "1.2.0")
            beta = base / "beta.zip"
            write_archive(beta, "1.2.0-beta2")
            self.assertTrue(validate_and_stage_archive(
                beta, base / "beta-stage", "1.2.0-beta2",
            ).is_dir())

    def test_archive_rejects_traversal_symlink_and_duplicate_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            unsafe = base / "unsafe.zip"
            with ZipFile(unsafe, "w") as archive:
                archive.writestr("GabeCubeAura/../outside", "bad")
            with self.assertRaises(UpdateError):
                validate_and_stage_archive(unsafe, base / "stage-a", "1.1.0")

            symlink = base / "symlink.zip"
            with ZipFile(symlink, "w") as archive:
                info = ZipInfo("GabeCubeAura/link")
                info.external_attr = 0o120777 << 16
                archive.writestr(info, "target")
            with self.assertRaises(UpdateError):
                validate_and_stage_archive(symlink, base / "stage-b", "1.1.0")

            duplicate = base / "duplicate.zip"
            with ZipFile(duplicate, "w") as archive:
                archive.writestr("GabeCubeAura/main.py", "one")
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    archive.writestr("GabeCubeAura/main.py", "two")
            with self.assertRaises(UpdateError):
                validate_and_stage_archive(duplicate, base / "stage-c", "1.1.0")

    def test_stale_available_release_is_cleared_after_successful_update(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            state = base / "runtime/updates/update-state.json"
            state.parent.mkdir(parents=True)
            state.write_text(json.dumps({
                "phase": "available",
                "installed_version": "1.0.0",
                "available_version": "1.1.0",
                "release_notes": "old notes",
                "release_url": "https://github.com/Alyenax/GabeCubeAura/releases/tag/v1.1.0",
                "confirmation_token": "a" * 32,
                "prepared_digest": "b" * 64,
            }), encoding="utf-8")
            manager = UpdateManager(
                "1.1.0", SettingsStore(str(base / "settings.json")),
                str(base / "runtime"), str(base / "plugins/GabeCubeAura"), FakeLogger(),
            )
            status = manager.status()
            self.assertEqual(status["phase"], "up_to_date")
            self.assertEqual(status["available_version"], "")
            self.assertEqual(status["confirmation_token"], "")

    def test_manager_discovers_prepares_and_persists_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive = base / "release.zip"
            write_archive(archive)
            settings = SettingsStore(str(base / "settings/config.json"))
            manager = UpdateManager(
                "1.0.99-test.1", settings, str(base / "runtime"),
                str(base / "plugins/GabeCubeAura"), FakeLogger(), client=FakeClient(archive),
            )
            self.assertEqual(manager.check()["phase"], "available")
            prepared = manager.prepare()
            self.assertEqual(prepared["phase"], "ready")
            self.assertRegex(prepared["confirmation_token"], r"^[0-9a-f]{32}$")
            self.assertTrue((base / "runtime/updates/staged" / prepared["confirmation_token"] / "GabeCubeAura").is_dir())
            manager.set_preferences(False, False, 180, "beta")
            restored = SettingsStore(str(base / "settings/config.json")).all()
            self.assertFalse(restored["updates_auto_check"])
            self.assertFalse(restored["updates_notifications"])
            self.assertEqual(restored["updates_check_interval_minutes"], 180)
            self.assertEqual(restored["updates_channel"], "beta")

    def test_selected_check_interval_drives_the_next_automatic_check(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive = base / "release.zip"
            write_archive(archive)
            settings = SettingsStore(str(base / "settings/config.json"))
            manager = UpdateManager(
                "1.0.0", settings, str(base / "runtime"),
                str(base / "plugins/GabeCubeAura"), FakeLogger(),
                client=FakeClient(archive), clock=lambda: 1000,
            )
            self.assertEqual(
                manager.set_preferences(True, True, 15, "stable")["next_check_at"], 1000,
            )
            checked = manager.check()
            self.assertEqual(checked["next_check_at"], 1900)
            self.assertEqual(checked["check_interval_minutes"], 15)

    def test_helper_launch_removes_decky_runtime_libraries(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive = base / "GabeCubeAura-v1.1.1.zip"
            write_archive(archive, "1.1.1")
            active = base / "plugins/GabeCubeAura"
            write_plugin(active, "1.1.0")
            manager = UpdateManager(
                "1.1.0", SettingsStore(str(base / "settings/config.json")),
                str(base / "runtime"), str(active), FakeLogger(),
                client=FakeClient(archive, "1.1.1"),
            )
            manager.check()
            prepared = manager.prepare()

            poisoned = {
                "PATH": "/usr/bin:/bin",
                "LD_LIBRARY_PATH": "/tmp/_MEI-decky",
                "LD_PRELOAD": "/tmp/decky-preload.so",
                "PYTHONHOME": "/tmp/decky-python",
                "PYTHONPATH": "/tmp/decky-modules",
                "LANG": "C.UTF-8",
            }
            with patch.dict("signalbar.updates.os.environ", poisoned, clear=True), \
                    patch(
                        "signalbar.updates.shutil.which",
                        side_effect=["/usr/bin/python3", "/usr/bin/systemd-run"],
                    ), \
                    patch("signalbar.updates.subprocess.run") as launched:
                accepted = manager.install(prepared["confirmation_token"])

            self.assertTrue(accepted["accepted"])
            environment = launched.call_args.kwargs["env"]
            self.assertEqual(environment["LD_LIBRARY_PATH"], "")
            self.assertNotIn("LD_PRELOAD", environment)
            self.assertNotIn("PYTHONHOME", environment)
            self.assertNotIn("PYTHONPATH", environment)
            self.assertEqual(environment["LANG"], "C.UTF-8")

    def test_switching_from_stable_to_beta_checks_immediately_and_prepares_beta(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive = base / "beta.zip"
            write_archive(archive, "1.2.0-beta.3")
            settings = SettingsStore(str(base / "settings/config.json"))
            client = FakeClient(archive, "1.2.0-beta.3")
            manager = UpdateManager(
                "1.1.3", settings, str(base / "runtime"),
                str(base / "plugins/GabeCubeAura"), FakeLogger(), client=client,
            )

            status = manager.set_preferences(True, True, 15, "beta")

            self.assertEqual(status["channel"], "beta")
            self.assertEqual(status["phase"], "available")
            self.assertEqual(status["available_version"], "1.2.0-beta.3")
            self.assertFalse(status["return_to_stable"])
            self.assertEqual(len(client.calls), 1)
            prepared = manager.prepare()
            self.assertEqual(prepared["phase"], "ready")

    def test_switching_from_beta_to_stable_offers_verified_return_even_when_older(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive = base / "stable.zip"
            write_archive(archive, "1.1.3")
            settings = SettingsStore(str(base / "settings/config.json"))
            settings.update({"updates_channel": "beta"})
            manager = UpdateManager(
                "1.2.0-beta.3", settings, str(base / "runtime"),
                str(base / "plugins/GabeCubeAura"), FakeLogger(),
                client=FakeClient(archive, "1.1.3"),
            )

            status = manager.set_preferences(True, True, 60, "stable")

            self.assertEqual(status["phase"], "available")
            self.assertEqual(status["available_version"], "1.1.3")
            self.assertTrue(status["return_to_stable"])

    def test_startup_check_runs_once_even_when_periodic_deadline_is_in_the_future(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive = base / "GabeCubeAura-v1.1.2.zip"
            write_archive(archive, "1.1.2")
            settings = SettingsStore(str(base / "settings/config.json"))
            client = FakeClient(archive, "1.1.2")
            manager = UpdateManager(
                "1.1.1", settings, str(base / "runtime"),
                str(base / "plugins/GabeCubeAura"), FakeLogger(), client=client,
                clock=lambda: 100,
            )
            manager._set(next_check_at=999999)

            self.assertEqual(manager._check_on_startup()["phase"], "available")
            self.assertEqual(len(client.calls), 1)
            settings.update({"updates_auto_check": False})
            manager._check_on_startup()
            self.assertEqual(len(client.calls), 1)

    def test_manual_check_bypasses_a_stale_etag(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive = base / "GabeCubeAura-v1.1.2.zip"
            write_archive(archive, "1.1.2")
            client = ConditionalFakeClient(archive, "1.1.2")
            manager = UpdateManager(
                "1.1.1", SettingsStore(str(base / "settings/config.json")),
                str(base / "runtime"), str(base / "plugins/GabeCubeAura"),
                FakeLogger(), client=client,
            )
            manager._set(
                phase="up_to_date", checked_channel="stable",
                etag='"stale-release"', available_version="",
            )

            automatic = manager.check()
            manual = manager.check(force_refresh=True)

            self.assertEqual(client.calls[0], ("1.1.1", '"stale-release"'))
            self.assertEqual(client.calls[1], ("1.1.1", ""))
            self.assertEqual(automatic["phase"], "up_to_date")
            self.assertEqual(manual["phase"], "available")
            self.assertEqual(manual["available_version"], "1.1.2")

    def test_health_acknowledgement_only_matches_pending_version_and_token(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            runtime = base / "runtime"
            state = runtime / "updates/update-state.json"
            token = "a" * 32
            state.parent.mkdir(parents=True)
            state.write_text(json.dumps({
                "pending_token": token, "pending_version": "1.1.0", "phase": "restart_pending",
            }), encoding="utf-8")
            UpdateManager("1.1.0", SettingsStore(str(base / "settings.json")),
                          str(runtime), str(base / "GabeCubeAura"), FakeLogger())
            health = json.loads((runtime / f"updates/health/{token}.json").read_text(encoding="utf-8"))
            self.assertEqual(health["version"], "1.1.0")

    def test_update_lab_runs_all_fixed_scenarios_without_real_plugin_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive = base / "release.zip"
            write_archive(archive)
            manager = UpdateManager(
                "1.0.99-test.1", SettingsStore(str(base / "settings.json")),
                str(base / "runtime"), str(base / "real/GabeCubeAura"),
                FakeLogger(), client=FakeClient(archive),
            )
            for scenario in ("valid-package", "checksum-mismatch", "rollback"):
                result = manager.run_lab(scenario)
                self.assertTrue(result["passed"], result)
            report = json.loads(
                (base / "runtime/updates/update-lab-report.json").read_text(encoding="utf-8")
            )
            self.assertEqual({item["scenario"] for item in report["results"]}, {
                "valid-package", "checksum-mismatch", "rollback",
            })
            self.assertFalse((base / "real/GabeCubeAura").exists())

    def _transaction(self, base: Path):
        token = "b" * 32
        active = base / "plugins/GabeCubeAura"
        staged = base / f"runtime/updates/staged/{token}/GabeCubeAura"
        write_plugin(active, "1.0.0", "old")
        write_plugin(staged, "1.1.0", "new")
        state = base / "runtime/updates/update-state.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text("{}", encoding="utf-8")
        return {
            "schema": 1, "token": token, "from_version": "1.0.0", "to_version": "1.1.0",
            "digest": "c" * 64, "active_dir": str(active), "staged_dir": str(staged),
            "runtime_root": str(base / "runtime/updates"), "state_path": str(state),
            "health_path": str(base / f"runtime/updates/health/{token}.json"),
            "service": "plugin_loader.service", "health_timeout": 45,
        }

    def test_transaction_swaps_only_after_stop_and_accepts_health(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            raw = self._transaction(base)
            settings = base / "settings/config.json"
            artwork = base / "settings/artwork-cache.json"
            settings.parent.mkdir(parents=True)
            settings.write_bytes(b'{"choice":"kept"}\n')
            artwork.write_bytes(b'{"palette":"kept"}\n')
            before = (hashlib.sha256(settings.read_bytes()).hexdigest(),
                      hashlib.sha256(artwork.read_bytes()).hexdigest())
            service = FakeService()
            result = run_transaction(raw, service=service, health_waiter=lambda *args: True,
                                     exchanger=fake_exchange)
            self.assertEqual(result, {"result": "updated", "version": "1.1.0"})
            self.assertEqual(service.stops, 1)
            self.assertEqual(service.starts, 1)
            self.assertIn('MARKER = "new"', (Path(raw["active_dir"]) / "main.py").read_text())
            rollback = base / f"runtime/updates/rollback/{raw['token']}/GabeCubeAura/main.py"
            self.assertIn('MARKER = "old"', rollback.read_text())
            after = (hashlib.sha256(settings.read_bytes()).hexdigest(),
                     hashlib.sha256(artwork.read_bytes()).hexdigest())
            self.assertEqual(after, before)
            UpdateManager(
                "1.1.0", SettingsStore(str(base / "settings/plugin.json")),
                str(base / "runtime"), str(Path(raw["active_dir"])), FakeLogger(),
            )
            self.assertFalse(rollback.parent.exists())

    def test_transaction_resumes_after_atomic_exchange_was_interrupted(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            raw = self._transaction(base)
            active, staged = Path(raw["active_dir"]), Path(raw["staged_dir"])
            fake_exchange(active, staged)
            service = FakeService()
            result = run_transaction(raw, service=service, health_waiter=lambda *args: True,
                                     exchanger=fake_exchange)
            self.assertEqual(result["result"], "updated")
            self.assertIn('MARKER = "new"', (active / "main.py").read_text())
            rollback = base / f"runtime/updates/rollback/{raw['token']}/GabeCubeAura/main.py"
            self.assertIn('MARKER = "old"', rollback.read_text())

    def test_failed_health_check_restores_previous_plugin_without_loop(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            raw = self._transaction(base)
            service = FakeService()
            result = run_transaction(raw, service=service, health_waiter=lambda *args: False,
                                     exchanger=fake_exchange)
            self.assertEqual(result["result"], "rolled_back")
            self.assertEqual(service.starts, 2)
            self.assertEqual(service.stops, 2)
            self.assertIn('MARKER = "old"', (Path(raw["active_dir"]) / "main.py").read_text())
            state = json.loads(Path(raw["state_path"]).read_text(encoding="utf-8"))
            self.assertEqual(state["phase"], "rolled_back")
            self.assertEqual(state["pending_token"], "")


if __name__ == "__main__":
    unittest.main()
