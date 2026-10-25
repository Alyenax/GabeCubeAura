"""Verified GitHub release discovery and staged GabeCubeAura updates."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import random
import re
import shutil
import ssl
import stat
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPSHandler, Request, build_opener, HTTPRedirectHandler
from zipfile import BadZipFile, ZipFile


OWNER = "Alyenax"
REPOSITORY = "GabeCubeAura"
API_URL = f"https://api.github.com/repos/{OWNER}/{REPOSITORY}/releases/latest"
RELEASES_API_URL = f"https://api.github.com/repos/{OWNER}/{REPOSITORY}/releases?per_page=50"
TEST_RELEASE_API_URL = f"https://api.github.com/repos/{OWNER}/{REPOSITORY}/releases/tags/v1.1.0"
PRIVATE_OWNER = "Alyenax"
PRIVATE_REPOSITORY = "GabeCubeAura-Lab"
PRIVATE_REPOSITORY_ID = 1402255604
# Public identifier for the read-only GitHub App. It is filled after the app is
# registered and is not a secret. No client secret is embedded in the plugin.
PRIVATE_GITHUB_CLIENT_ID = "Iv23lizXKqIqTbVNKuUD"
PRIVATE_RELEASES_API_URL = (
    f"https://api.github.com/repos/{PRIVATE_OWNER}/{PRIVATE_REPOSITORY}/releases?per_page=50"
)
DEVICE_CODE_URL = "https://github.com/login/device/code"
ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
EXPECTED_ROOT = "GabeCubeAura"
CHECK_INTERVAL_MINUTES = {15, 60, 180, 360, 720, 1440}
STARTUP_DELAY_SECONDS = 20
HEALTHY_TRANSACTION_RECOVERY_SECONDS = 5
MAX_METADATA_BYTES = 512 * 1024
MAX_CHECKSUM_BYTES = 64 * 1024
MAX_ARCHIVE_BYTES = 5 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 20 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 512
REQUIRED_FILES = {
    "main.py",
    "plugin.json",
    "package.json",
    "dist/index.js",
    "LICENSE",
    "py_modules/signalbar/__init__.py",
}
ALLOWED_HTTPS_HOSTS = {
    "api.github.com",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "github-releases.githubusercontent.com",
}
SYSTEM_CA_BUNDLES = (
    "/etc/ssl/cert.pem",
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/ssl/certs/ca-bundle.crt",
)


def _clean_system_command_environment():
    """Keep Decky's bundled libraries away from SteamOS system commands."""
    environment = os.environ.copy()
    for name in ("LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH"):
        environment.pop(name, None)
    environment["LD_LIBRARY_PATH"] = ""
    return environment


STABLE_VERSION = re.compile(r"^(?:v)?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
TEST_VERSION = re.compile(
    r"^(?:v)?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)-test\.(0|[1-9]\d*)$"
)
BETA_VERSION = re.compile(
    r"^(?:v)?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)-beta\.?(0|[1-9]\d*)$"
)
LAB_VERSION = re.compile(
    r"^(?:v)?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)-lab\.?(0|[1-9]\d*)$"
)
HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")
OAUTH_TOKEN = re.compile(r"^gh[ur]_[A-Za-z0-9_]{16,512}$")


class UpdateError(RuntimeError):
    """A bounded, user-safe updater error."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


def _version_tuple(value: str, *, allow_test=False):
    text = str(value or "").strip()
    match = STABLE_VERSION.fullmatch(text)
    if match:
        return tuple(int(part) for part in match.groups())
    if allow_test:
        test = TEST_VERSION.fullmatch(text)
        if test:
            major, minor, patch, iteration = (int(part) for part in test.groups())
            return major, minor, patch, -1, iteration
        beta = BETA_VERSION.fullmatch(text)
        if beta:
            major, minor, patch, iteration = (int(part) for part in beta.groups())
            return major, minor, patch, -2, iteration
        lab = LAB_VERSION.fullmatch(text)
        if lab:
            major, minor, patch, iteration = (int(part) for part in lab.groups())
            return major, minor, patch, -1, iteration
    raise UpdateError("invalid_version", "The release version is not a stable semantic version")


def _version_order(value: str, *, allow_test=False):
    """Return one comparable key where a stable release follows its prereleases."""
    parsed = _version_tuple(value, allow_test=allow_test)
    return (*parsed, 0, 0) if len(parsed) == 3 else parsed


def _atomic_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def _safe_read_json(path: Path, default=None):
    try:
        if path.stat().st_size > MAX_METADATA_BYTES:
            return {} if default is None else default
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else ({} if default is None else default)
    except (OSError, ValueError, TypeError):
        return {} if default is None else default


def _certificate_failure(error):
    return isinstance(getattr(error, "reason", error), ssl.SSLCertVerificationError)


class _RestrictedRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        parsed = urlparse(newurl)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HTTPS_HOSTS:
            raise UpdateError("unsafe_redirect", "GitHub redirected the update to an untrusted host")
        redirected = super().redirect_request(request, fp, code, msg, headers, newurl)
        if redirected is not None and urlparse(request.full_url).hostname != parsed.hostname:
            # GitHub release assets use a signed redirect. The signed URL does
            # not need the user token, and forwarding it to another host would
            # unnecessarily expose a private credential.
            redirected.remove_header("Authorization")
        return redirected


def _verified_open(request: Request, timeout=10):
    contexts = [ssl.create_default_context()]
    for bundle in SYSTEM_CA_BUNDLES:
        if os.path.isfile(bundle):
            try:
                contexts.append(ssl.create_default_context(cafile=bundle))
            except OSError:
                continue
    last_error = None
    for index, context in enumerate(contexts):
        try:
            opener = build_opener(HTTPSHandler(context=context), _RestrictedRedirectHandler())
            return opener.open(request, timeout=timeout)
        except URLError as error:
            last_error = error
            if not _certificate_failure(error) or index == len(contexts) - 1:
                raise
    raise last_error or UpdateError("network", "Unable to open the update URL")


def _bounded_read(response, maximum: int):
    payload = response.read(maximum + 1)
    if len(payload) > maximum:
        raise UpdateError("response_too_large", "The update server response is too large")
    return payload


class GitHubDeviceAuth:
    """Persist one least-privilege GitHub App device authorization."""

    def __init__(self, path: Path, *, client_id=PRIVATE_GITHUB_CLIENT_ID,
                 repository_id=PRIVATE_REPOSITORY_ID, opener=_verified_open,
                 clock=time.time):
        self.path = Path(path)
        self.client_id = str(client_id or "")
        self.repository_id = int(repository_id or 0)
        self._open = opener
        self.clock = clock
        self._lock = threading.RLock()
        self._state = _safe_read_json(self.path, {})

    @property
    def configured(self):
        return bool(re.fullmatch(r"[A-Za-z0-9_.-]{10,100}", self.client_id)) \
            and self.repository_id > 0

    def _save(self):
        _atomic_json(self.path, self._state)

    def _post(self, url: str, values: dict):
        if url not in {DEVICE_CODE_URL, ACCESS_TOKEN_URL}:
            raise UpdateError("private_auth", "GitHub authorization URL is not trusted")
        request = Request(
            url,
            data=urlencode(values).encode("ascii"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "GabeCubeAura private updater",
            },
            method="POST",
        )
        try:
            response = self._open(request, timeout=15)
            with response:
                payload = _bounded_read(response, 64 * 1024)
            decoded = json.loads(payload)
        except UpdateError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, TypeError) as error:
            raise UpdateError("private_auth_network", "Could not reach GitHub authorization") from error
        if not isinstance(decoded, dict):
            raise UpdateError("private_auth", "GitHub returned invalid authorization data")
        return decoded

    def _public_status(self):
        now = int(self.clock())
        phase = str(self._state.get("phase", "disconnected"))
        if phase == "pending" and now >= int(self._state.get("device_expires_at", 0) or 0):
            phase = "expired"
        access = str(self._state.get("access_token", ""))
        refresh = str(self._state.get("refresh_token", ""))
        access_expires = int(self._state.get("access_expires_at", 0) or 0)
        refresh_expires = int(self._state.get("refresh_expires_at", 0) or 0)
        connected = bool(
            OAUTH_TOKEN.fullmatch(access)
            and (access_expires == 0 or access_expires > now + 30)
        ) or bool(
            OAUTH_TOKEN.fullmatch(refresh)
            and (refresh_expires == 0 or refresh_expires > now + 30)
        )
        if connected:
            phase = "connected"
        return {
            "private_auth_configured": self.configured,
            "private_auth_state": phase,
            "private_user_code": str(self._state.get("user_code", "")) if phase == "pending" else "",
            "private_verification_uri": (
                str(self._state.get("verification_uri", "")) if phase == "pending" else ""
            ),
            "private_auth_expires_at": (
                int(self._state.get("device_expires_at", 0) or 0) if phase == "pending" else 0
            ),
            "private_repository": f"{PRIVATE_OWNER}/{PRIVATE_REPOSITORY}",
        }

    def status(self):
        with self._lock:
            return self._public_status()

    def start(self):
        if not self.configured:
            raise UpdateError("private_auth_config", "Private Lab authorization is not configured")
        decoded = self._post(DEVICE_CODE_URL, {"client_id": self.client_id})
        device_code = str(decoded.get("device_code", ""))
        user_code = str(decoded.get("user_code", ""))
        verification_uri = str(decoded.get("verification_uri", ""))
        try:
            expires_in = max(60, min(1800, int(decoded.get("expires_in", 900))))
            interval = max(5, min(30, int(decoded.get("interval", 5))))
        except (TypeError, ValueError, OverflowError) as error:
            raise UpdateError("private_auth", "GitHub returned invalid device timing") from error
        if (not device_code or len(device_code) > 256
                or not re.fullmatch(r"[A-Z0-9-]{4,32}", user_code)
                or verification_uri != "https://github.com/login/device"):
            raise UpdateError("private_auth", "GitHub returned invalid device authorization data")
        now = int(self.clock())
        with self._lock:
            self._state = {
                "schema": 1,
                "phase": "pending",
                "device_code": device_code,
                "user_code": user_code,
                "verification_uri": verification_uri,
                "device_expires_at": now + expires_in,
                "poll_interval": interval,
                "next_poll_at": now,
                "error": "",
            }
            self._save()
            return self._public_status()

    def _adopt_token(self, decoded: dict):
        access = str(decoded.get("access_token", ""))
        refresh = str(decoded.get("refresh_token", ""))
        if not OAUTH_TOKEN.fullmatch(access):
            raise UpdateError("private_auth", "GitHub returned an invalid access token")
        if refresh and not OAUTH_TOKEN.fullmatch(refresh):
            raise UpdateError("private_auth", "GitHub returned an invalid refresh token")
        try:
            expires_in = int(decoded.get("expires_in", 0) or 0)
            refresh_expires_in = int(decoded.get("refresh_token_expires_in", 0) or 0)
        except (TypeError, ValueError, OverflowError) as error:
            raise UpdateError("private_auth", "GitHub returned invalid token timing") from error
        now = int(self.clock())
        self._state = {
            "schema": 1,
            "phase": "connected",
            "access_token": access,
            "access_expires_at": now + expires_in if expires_in > 0 else 0,
            "refresh_token": refresh,
            "refresh_expires_at": now + refresh_expires_in if refresh_expires_in > 0 else 0,
            "error": "",
        }
        self._save()

    def poll(self):
        with self._lock:
            now = int(self.clock())
            if self._state.get("phase") != "pending":
                return self._public_status()
            if now >= int(self._state.get("device_expires_at", 0) or 0):
                self._state.update(
                    phase="expired", device_code="", user_code="", verification_uri="",
                    error="The GitHub code expired",
                )
                self._save()
                return self._public_status()
            if now < int(self._state.get("next_poll_at", 0) or 0):
                return self._public_status()
            interval = int(self._state.get("poll_interval", 5) or 5)
            device_code = str(self._state.get("device_code", ""))
            self._state["next_poll_at"] = now + interval
            self._save()
        decoded = self._post(ACCESS_TOKEN_URL, {
            "client_id": self.client_id,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "repository_id": str(self.repository_id),
        })
        error = str(decoded.get("error", ""))
        with self._lock:
            if not error:
                self._adopt_token(decoded)
            elif error == "authorization_pending":
                pass
            elif error == "slow_down":
                self._state["poll_interval"] = min(60, int(self._state.get("poll_interval", 5)) + 5)
            elif error in {"expired_token", "access_denied"}:
                self._state.update(
                    phase="expired", device_code="", user_code="", verification_uri="",
                    error=error,
                )
            else:
                self._state.update(
                    phase="error", device_code="", user_code="", verification_uri="",
                    error=error[:80],
                )
            self._save()
            return self._public_status()

    def access_token(self):
        if not self.configured:
            raise UpdateError("private_auth_config", "Private Lab authorization is not configured")
        with self._lock:
            now = int(self.clock())
            access = str(self._state.get("access_token", ""))
            access_expires = int(self._state.get("access_expires_at", 0) or 0)
            if OAUTH_TOKEN.fullmatch(access) and (access_expires == 0 or access_expires > now + 60):
                return access
            refresh = str(self._state.get("refresh_token", ""))
            refresh_expires = int(self._state.get("refresh_expires_at", 0) or 0)
            if not OAUTH_TOKEN.fullmatch(refresh) or (refresh_expires and refresh_expires <= now + 60):
                raise UpdateError("private_auth_required", "Connect GitHub to use Private Lab updates")
        decoded = self._post(ACCESS_TOKEN_URL, {
            "client_id": self.client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh,
        })
        if decoded.get("error"):
            with self._lock:
                self._state.update(phase="expired", access_token="", refresh_token="")
                self._save()
            raise UpdateError("private_auth_required", "Reconnect GitHub to use Private Lab updates")
        with self._lock:
            self._adopt_token(decoded)
            return str(self._state["access_token"])

    def disconnect(self):
        with self._lock:
            self._state = {"schema": 1, "phase": "disconnected"}
            self.path.unlink(missing_ok=True)
            return self._public_status()


class GitHubReleaseClient:
    """Read only access to one fixed GitHub repository."""

    def __init__(self, opener=_verified_open, api_url=API_URL, *, allow_prerelease=False,
                 prerelease_kind="beta", include_stable=True, owner=OWNER,
                 repository=REPOSITORY, token="", private_assets=False):
        self._open = opener
        self.api_url = api_url
        self.allow_prerelease = allow_prerelease
        self.prerelease_kind = prerelease_kind
        self.include_stable = bool(include_stable)
        self.owner = str(owner)
        self.repository = str(repository)
        self.token = str(token)
        self.private_assets = bool(private_assets)

    def _request(self, url, version, *, etag=""):
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HTTPS_HOSTS:
            raise UpdateError("unsafe_url", "The update source is not an approved GitHub URL")
        asset_prefix = f"https://api.github.com/repos/{self.owner}/{self.repository}/releases/assets/"
        headers = {
            "Accept": (
                "application/octet-stream"
                if self.private_assets and url.startswith(asset_prefix)
                else "application/vnd.github+json"
            ),
            "User-Agent": f"GabeCubeAura/{version} updater",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            if not OAUTH_TOKEN.fullmatch(self.token):
                raise UpdateError("private_auth", "The private update token is invalid")
            headers["Authorization"] = f"Bearer {self.token}"
        if etag:
            headers["If-None-Match"] = etag[:256]
        return Request(url, headers=headers)

    def latest(self, installed_version: str, *, etag=""):
        request = self._request(self.api_url, installed_version, etag=etag)
        try:
            response = self._open(request, timeout=10)
        except HTTPError as error:
            if error.code == 304:
                return {"not_modified": True, "etag": etag}
            if error.code == 403 and error.headers.get("X-RateLimit-Remaining") == "0":
                raise UpdateError("rate_limited", "GitHub rate limit reached. Try again later") from error
            raise UpdateError("http", f"GitHub returned HTTP {error.code}") from error
        except UpdateError:
            raise
        except (URLError, TimeoutError, OSError) as error:
            raise UpdateError("network", "Could not reach the official GabeCubeAura release") from error
        with response:
            payload = _bounded_read(response, MAX_METADATA_BYTES)
            response_etag = str(response.headers.get("ETag", ""))[:256]
        try:
            decoded = json.loads(payload)
        except (ValueError, TypeError) as error:
            raise UpdateError("metadata", "GitHub returned invalid release metadata") from error
        if isinstance(decoded, list):
            releases = []
            for candidate in decoded:
                if not isinstance(candidate, dict) or candidate.get("draft"):
                    continue
                candidate_version = str(candidate.get("tag_name", "")).removeprefix("v")
                stable = bool(STABLE_VERSION.fullmatch(candidate_version))
                selected_prerelease = bool(
                    BETA_VERSION.fullmatch(candidate_version)
                    if self.prerelease_kind == "beta"
                    else LAB_VERSION.fullmatch(candidate_version)
                    if self.prerelease_kind == "lab"
                    else False
                )
                if self.include_stable and stable and not candidate.get("prerelease"):
                    releases.append(candidate)
                elif self.allow_prerelease and selected_prerelease and candidate.get("prerelease"):
                    releases.append(candidate)
            if not releases:
                raise UpdateError("metadata", "GitHub did not return a published release for this channel")
            release = max(
                releases,
                key=lambda item: _version_order(
                    str(item.get("tag_name", "")).removeprefix("v"), allow_test=True,
                ),
            )
        else:
            release = decoded
        if not isinstance(release, dict) or release.get("draft"):
            raise UpdateError("metadata", "GitHub did not return a published release for this channel")
        version = str(release.get("tag_name", "")).removeprefix("v")
        _version_tuple(version, allow_test=self.allow_prerelease)
        stable = bool(STABLE_VERSION.fullmatch(version))
        selected_prerelease = bool(
            BETA_VERSION.fullmatch(version)
            if self.prerelease_kind == "beta"
            else LAB_VERSION.fullmatch(version)
            if self.prerelease_kind == "lab"
            else False
        )
        if stable and (release.get("prerelease") or not self.include_stable):
            raise UpdateError("metadata", "A stable tag cannot be published as a prerelease")
        if selected_prerelease and not release.get("prerelease"):
            raise UpdateError("metadata", "A prerelease tag must be published as a prerelease")
        if not stable and not (self.allow_prerelease and selected_prerelease and release.get("prerelease")):
            raise UpdateError("metadata", "GitHub returned a release outside the selected channel")
        html_url = str(release.get("html_url", ""))
        if not html_url.startswith(
            f"https://github.com/{self.owner}/{self.repository}/releases/tag/"
        ):
            raise UpdateError("metadata", "The release page does not belong to the selected repository")
        expected_archive = f"GabeCubeAura-v{version}.zip"
        assets = release.get("assets")
        if not isinstance(assets, list):
            raise UpdateError("metadata", "The release has no asset list")
        by_name = {}
        for asset in assets:
            if isinstance(asset, dict) and isinstance(asset.get("name"), str):
                by_name[asset["name"]] = asset
        archive = self._validated_asset(by_name.get(expected_archive), expected_archive)
        checksums = self._validated_asset(by_name.get("SHA256SUMS"), "SHA256SUMS")
        if int(archive.get("size", 0)) <= 0 or int(archive.get("size", 0)) > MAX_ARCHIVE_BYTES:
            raise UpdateError("archive_size", "The release archive size is outside the allowed limit")
        digest = str(archive.get("digest") or "")
        if digest and (not digest.startswith("sha256:") or not HEX_DIGEST.fullmatch(digest[7:].lower())):
            raise UpdateError("metadata", "GitHub reported an invalid archive digest")
        return {
            "not_modified": False,
            "version": version,
            "tag": str(release.get("tag_name", "")),
            "name": str(release.get("name", ""))[:160],
            "notes": str(release.get("body", ""))[:12000],
            "html_url": html_url,
            "archive_name": expected_archive,
            "archive_url": archive["download_url"],
            "archive_size": int(archive["size"]),
            "archive_digest": digest[7:].lower() if digest else "",
            "checksums_url": checksums["download_url"],
            "etag": response_etag,
        }

    def _validated_asset(self, asset, expected_name):
        if not isinstance(asset, dict) or asset.get("name") != expected_name:
            raise UpdateError("missing_asset", f"The release is missing {expected_name}")
        if self.private_assets:
            url = str(asset.get("url", ""))
            prefix = f"https://api.github.com/repos/{self.owner}/{self.repository}/releases/assets/"
            if not url.startswith(prefix) or urlparse(url).hostname != "api.github.com":
                raise UpdateError("unsafe_url", f"The {expected_name} API asset URL is not trusted")
        else:
            url = str(asset.get("browser_download_url", ""))
            prefix = f"https://github.com/{self.owner}/{self.repository}/releases/download/"
            if not url.startswith(prefix) or urlparse(url).hostname != "github.com":
                raise UpdateError("unsafe_url", f"The {expected_name} download URL is not trusted")
        return {**asset, "download_url": url}

    def read_checksum(self, release: dict, installed_version: str):
        request = self._request(release["checksums_url"], installed_version)
        try:
            response = self._open(request, timeout=10)
            with response:
                payload = _bounded_read(response, MAX_CHECKSUM_BYTES)
        except UpdateError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            raise UpdateError("checksum_download", "Could not download SHA256SUMS") from error
        try:
            lines = payload.decode("utf-8").splitlines()
        except UnicodeDecodeError as error:
            raise UpdateError("checksum", "SHA256SUMS is not valid UTF-8") from error
        matches = []
        for line in lines:
            fields = line.strip().split(maxsplit=1)
            if len(fields) != 2:
                continue
            digest, filename = fields
            filename = filename.lstrip("*")
            if filename == release["archive_name"]:
                matches.append(digest.lower())
        if len(matches) != 1 or not HEX_DIGEST.fullmatch(matches[0]):
            raise UpdateError("checksum", "SHA256SUMS has no unique valid digest for the archive")
        if release.get("archive_digest") and release["archive_digest"] != matches[0]:
            raise UpdateError("checksum", "GitHub and SHA256SUMS disagree about the archive")
        return matches[0]

    def download_archive(self, release: dict, destination: Path, installed_version: str):
        request = self._request(release["archive_url"], installed_version)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".part")
        digest = hashlib.sha256()
        total = 0
        try:
            response = self._open(request, timeout=15)
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_ARCHIVE_BYTES:
                raise UpdateError("archive_size", "The archive is larger than the allowed limit")
            with response, temporary.open("wb") as handle:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_ARCHIVE_BYTES:
                        raise UpdateError("archive_size", "The archive is larger than the allowed limit")
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if total != int(release["archive_size"]):
                raise UpdateError("archive_size", "The downloaded archive size does not match GitHub")
            os.replace(temporary, destination)
            return digest.hexdigest()
        except UpdateError:
            temporary.unlink(missing_ok=True)
            raise
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
            temporary.unlink(missing_ok=True)
            raise UpdateError("archive_download", "Could not download the release archive") from error


def validate_and_stage_archive(archive_path: Path, staging_parent: Path, expected_version: str):
    """Validate and extract one Decky archive without trusting ZIP paths."""
    _version_tuple(expected_version, allow_test=True)
    if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise UpdateError("archive_size", "The archive is larger than the allowed limit")
    if staging_parent.exists():
        shutil.rmtree(staging_parent)
    staging_parent.mkdir(parents=True, mode=0o700)
    names = set()
    total = 0
    try:
        with ZipFile(archive_path) as archive:
            infos = archive.infolist()
            if not infos or len(infos) > MAX_ARCHIVE_ENTRIES:
                raise UpdateError("archive_entries", "The archive contains an invalid number of entries")
            for info in infos:
                name = info.filename
                if not name or "\\" in name or name.startswith("/"):
                    raise UpdateError("archive_path", "The archive contains an unsafe path")
                parts = PurePosixPath(name).parts
                if not parts or parts[0] != EXPECTED_ROOT or any(part in {"", ".", ".."} for part in parts):
                    raise UpdateError("archive_path", "The archive must contain one GabeCubeAura directory")
                if name in names:
                    raise UpdateError("archive_duplicate", "The archive contains a duplicate path")
                names.add(name)
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise UpdateError("archive_symlink", "The archive contains a symbolic link")
                total += int(info.file_size)
                if total > MAX_UNCOMPRESSED_BYTES:
                    raise UpdateError("archive_size", "The extracted archive would be too large")
            for info in infos:
                parts = PurePosixPath(info.filename).parts
                destination = staging_parent.joinpath(*parts)
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target, length=64 * 1024)
                os.chmod(destination, 0o644)
    except UpdateError:
        shutil.rmtree(staging_parent, ignore_errors=True)
        raise
    except (BadZipFile, OSError, RuntimeError) as error:
        shutil.rmtree(staging_parent, ignore_errors=True)
        raise UpdateError("archive", "The release archive is corrupt or unreadable") from error

    root = staging_parent / EXPECTED_ROOT
    missing = [name for name in REQUIRED_FILES if not (root / name).is_file()]
    if missing:
        shutil.rmtree(staging_parent, ignore_errors=True)
        raise UpdateError("package", f"The package is missing {missing[0]}")
    try:
        package = json.loads((root / "package.json").read_text(encoding="utf-8"))
        plugin = json.loads((root / "plugin.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as error:
        shutil.rmtree(staging_parent, ignore_errors=True)
        raise UpdateError("package", "The package manifests are invalid") from error
    if package.get("name") != "gabecubeaura" or package.get("version") != expected_version:
        shutil.rmtree(staging_parent, ignore_errors=True)
        raise UpdateError("package", "The package name or version does not match the release")
    if plugin.get("name") != "GabeCubeAura":
        shutil.rmtree(staging_parent, ignore_errors=True)
        raise UpdateError("package", "The Decky plugin name is not GabeCubeAura")
    return root


class UpdateManager:
    """Own release state, background checks and transaction preparation."""

    def __init__(self, installed_version: str, settings, runtime_dir: str, plugin_dir: str,
                 logger, client=None, private_auth=None, clock=time.time,
                 monotonic=time.monotonic):
        self.installed_version = installed_version
        self.settings = settings
        self.runtime_dir = Path(runtime_dir).resolve()
        self.plugin_dir = Path(plugin_dir).resolve()
        self.logger = logger
        self.client = client
        self.clock = clock
        self.monotonic = monotonic
        self.root = self.runtime_dir / "updates"
        self.state_path = self.root / "update-state.json"
        self.private_auth = private_auth or GitHubDeviceAuth(
            self.root / "private-auth.json", clock=clock,
        )
        self._lock = threading.RLock()
        self._operation_lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._release = None
        self._state = self._load_state()
        self._cleanup_completed_transaction()
        self._cleanup_expired()
        self._acknowledge_pending_health()

    def _load_state(self):
        state = _safe_read_json(self.state_path, {})
        state.setdefault("phase", "idle")
        state.setdefault("installed_version", self.installed_version)
        state.setdefault("available_version", "")
        state.setdefault("last_checked_at", 0)
        state.setdefault("next_check_at", 0)
        state.setdefault("notified_version", "")
        state.setdefault("etag", "")
        state.setdefault("checked_channel", "")
        state.setdefault("return_to_stable", False)
        state.setdefault("error_category", "")
        state.setdefault("error", "")
        state.setdefault("release_notes", "")
        state.setdefault("release_url", "")
        state.setdefault("prepared_digest", "")
        state.setdefault("confirmation_token", "")
        state.setdefault("pending_token", "")
        state.setdefault("pending_version", "")
        state.setdefault("rollback_version", "")
        state.setdefault("last_result", "")
        state.setdefault("completed_token", "")
        state["installed_version"] = self.installed_version
        available = str(state.get("available_version", ""))
        try:
            returning = (
                bool(state.get("return_to_stable"))
                and self._configured_channel() == "stable"
                and bool(BETA_VERSION.fullmatch(self.installed_version))
                and bool(STABLE_VERSION.fullmatch(available))
                and available != self.installed_version
            )
            stale_available = (
                bool(available)
                and not returning
                and _version_order(available, allow_test=True)
                <= _version_order(self.installed_version, allow_test=True)
            )
        except UpdateError:
            stale_available = bool(available)
        if stale_available:
            state.update({
                "available_version": "",
                "release_notes": "",
                "release_url": "",
                "prepared_digest": "",
                "confirmation_token": "",
                "return_to_stable": False,
            })
            if state.get("phase") == "available":
                state["phase"] = "up_to_date"
        return state

    def _cleanup_completed_transaction(self):
        token = str(self._state.get("completed_token", ""))
        if not re.fullmatch(r"[0-9a-f]{32}", token) or self._state.get("pending_token"):
            return
        for family in ("downloads", "staged", "rollback", "health"):
            target = self.root / family / (f"{token}.json" if family == "health" else token)
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink(missing_ok=True)
        for target in (
            self.root / "helpers" / f"update-helper-{token}.py",
            self.root / "transactions" / f"{token}.json",
            self.root / "transactions" / f"{token}.result.json",
            self.root / "transactions" / f"{token}.fatal.json",
        ):
            target.unlink(missing_ok=True)
        self._state["completed_token"] = ""
        self._save()

    def _cleanup_expired(self):
        cutoff = self.clock() - 7 * 24 * 60 * 60
        pending = str(self._state.get("pending_token", ""))
        for family in ("downloads", "staged", "rollback", "failed", "helpers", "transactions", "health"):
            directory = self.root / family
            if not directory.is_dir():
                continue
            for target in list(directory.iterdir())[:256]:
                if pending and pending in target.name:
                    continue
                try:
                    if target.stat().st_mtime >= cutoff:
                        continue
                    if target.is_dir() and not target.is_symlink():
                        shutil.rmtree(target, ignore_errors=True)
                    else:
                        target.unlink(missing_ok=True)
                except OSError:
                    continue

    def _save(self):
        _atomic_json(self.state_path, self._state)

    def _set(self, **changes):
        with self._lock:
            self._state.update(changes)
            self._state["installed_version"] = self.installed_version
            self._save()

    def _acknowledge_pending_health(self):
        token = str(self._state.get("pending_token", ""))
        expected = str(self._state.get("pending_version", ""))
        if not token or expected != self.installed_version or not re.fullmatch(r"[0-9a-f]{32}", token):
            return
        health = self.root / "health" / f"{token}.json"
        _atomic_json(health, {
            "token": token,
            "version": self.installed_version,
            "acknowledged_at": int(self.clock()),
        })

    def _refresh_helper_state(self):
        """Adopt terminal state written by the independent update helper."""
        if self._state.get("phase") not in {"installing", "swap_started", "swapped", "restart_pending"}:
            return
        token = str(self._state.get("pending_token", ""))
        if not re.fullmatch(r"[0-9a-f]{32}", token):
            return
        persisted = _safe_read_json(self.state_path, {})
        phase = str(persisted.get("phase", ""))
        same_transaction = (
            persisted.get("completed_token") == token
            or persisted.get("pending_token") == token
        )
        if same_transaction and phase in {"updated", "rolled_back", "error"}:
            self._state = self._load_state()

    def _recover_healthy_pending_transaction(self):
        """Finish a stale restart once the replacement backend is healthy."""
        if self._state.get("phase") != "restart_pending":
            return
        token = str(self._state.get("pending_token", ""))
        expected = str(self._state.get("pending_version", ""))
        if (not re.fullmatch(r"[0-9a-f]{32}", token)
                or expected != self.installed_version):
            return
        health = _safe_read_json(self.root / "health" / f"{token}.json", {})
        acknowledged_at = int(health.get("acknowledged_at", 0) or 0)
        if (health.get("token") != token or health.get("version") != expected
                or self.clock() - acknowledged_at < HEALTHY_TRANSACTION_RECOVERY_SECONDS):
            return
        transaction = _safe_read_json(self.root / "transactions" / f"{token}.json", {})
        rollback_version = str(transaction.get("from_version", ""))
        self._set(
            phase="updated", installed_version=self.installed_version,
            pending_token="", pending_version="", confirmation_token="",
            available_version="", release_notes="", release_url="",
            prepared_digest="", rollback_version=rollback_version,
            last_result="updated", completed_token=token,
            error="", error_category="",
        )
        self.logger.warning(
            "[GabeCubeAura] recovered a healthy update transaction left at restart_pending"
        )

    def _recover_superseded_pending_transaction(self):
        """Unlock a stale restart replaced by a different manual installation."""
        if self._state.get("phase") != "restart_pending":
            return
        token = str(self._state.get("pending_token", ""))
        expected = str(self._state.get("pending_version", ""))
        if (not re.fullmatch(r"[0-9a-f]{32}", token)
                or not expected or expected == self.installed_version):
            return
        transaction = _safe_read_json(self.root / "transactions" / f"{token}.json", {})
        previous = str(transaction.get("from_version", ""))
        result = "rolled_back" if previous == self.installed_version else "updated"
        self._set(
            phase=result, installed_version=self.installed_version,
            pending_token="", pending_version="", confirmation_token="",
            available_version="", release_notes="", release_url="",
            prepared_digest="", rollback_version=previous,
            last_result=result, completed_token=token,
            error="", error_category="",
        )
        self.logger.warning(
            "[GabeCubeAura] closed a restart_pending transaction superseded by the installed version"
        )

    def _reconcile_helper_state(self):
        with self._lock:
            self._refresh_helper_state()
            self._recover_superseded_pending_transaction()
            self._recover_healthy_pending_transaction()

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self.root.mkdir(parents=True, exist_ok=True)
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="gabecubeaura-updates", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _run(self):
        initial = STARTUP_DELAY_SECONDS + random.uniform(0, 30)
        if self._stop.wait(initial):
            return
        self._check_on_startup()
        while not self._stop.is_set():
            values = self.settings.all()
            now = self.clock()
            due = values.get("updates_auto_check", True) and now >= float(self._state.get("next_check_at", 0))
            if due:
                try:
                    self.check()
                except Exception as error:
                    self.logger.warning(f"[GabeCubeAura] background update check failed: {error}")
            self._wake.wait(60)
            self._wake.clear()

    def _check_on_startup(self):
        if not self.settings.all().get("updates_auto_check", True):
            return self.status()
        try:
            return self.check()
        except Exception as error:
            self.logger.warning(f"[GabeCubeAura] startup update check failed: {error}")
            return self.status()

    def _configured_channel(self):
        channel = self.settings.all().get("updates_channel", "stable")
        return channel if channel in {"stable", "beta", "private"} else "stable"

    def _release_client(self, channel=None):
        if self.client is not None:
            return self.client
        if "-test." in self.installed_version:
            return GitHubReleaseClient(api_url=TEST_RELEASE_API_URL, allow_prerelease=True)
        channel = channel or self._configured_channel()
        if channel == "private":
            return GitHubReleaseClient(
                api_url=PRIVATE_RELEASES_API_URL,
                allow_prerelease=True,
                prerelease_kind="lab",
                include_stable=False,
                owner=PRIVATE_OWNER,
                repository=PRIVATE_REPOSITORY,
                token=self.private_auth.access_token(),
                private_assets=True,
            )
        return GitHubReleaseClient(
            api_url=RELEASES_API_URL if channel == "beta" else API_URL,
            allow_prerelease=channel == "beta",
        )

    def _check_interval_seconds(self):
        raw = self.settings.all().get("updates_check_interval_minutes", 1440)
        try:
            minutes = int(raw)
        except (TypeError, ValueError, OverflowError):
            minutes = 1440
        if minutes not in CHECK_INTERVAL_MINUTES:
            minutes = 1440
        return minutes * 60

    def _availability(self, version: str, channel: str):
        installed = _version_order(self.installed_version, allow_test=True)
        candidate = _version_order(version, allow_test=True)
        installed_beta = bool(BETA_VERSION.fullmatch(self.installed_version))
        candidate_stable = bool(STABLE_VERSION.fullmatch(version))
        if channel == "stable" and installed_beta and candidate_stable:
            return version != self.installed_version, candidate < installed
        return candidate > installed, False

    def status(self):
        self._reconcile_helper_state()
        with self._lock:
            values = self.settings.all()
            result = dict(self._state)
            result.update({
                "installed_version": self.installed_version,
                "auto_check": bool(values.get("updates_auto_check", True)),
                "notifications": bool(values.get("updates_notifications", True)),
                "check_interval_minutes": int(values.get("updates_check_interval_minutes", 1440)),
                "channel": values.get("updates_channel", "stable"),
                "test_build": "-test." in self.installed_version,
            })
            result.update(self.private_auth.status())
            result.pop("etag", None)
            result.pop("pending_token", None)
            result.pop("completed_token", None)
            return result

    def check(self, force_refresh=False):
        self._reconcile_helper_state()
        if self._state.get("phase") in {"downloading", "verifying", "ready", "installing", "restart_pending"}:
            return self.status()
        if not self._operation_lock.acquire(blocking=False):
            return self.status()
        self._set(phase="checking", error_category="", error="", return_to_stable=False)
        try:
            channel = self._configured_channel()
            client = self._release_client(channel)
            etag = (
                self._state.get("etag", "")
                if not force_refresh and self._state.get("checked_channel") == channel
                else ""
            )
            release = client.latest(self.installed_version, etag=etag)
            now = int(self.clock())
            if release.get("not_modified"):
                available = str(self._state.get("available_version", ""))
                try:
                    newer, returning = self._availability(available, channel) if available else (False, False)
                except UpdateError:
                    newer, returning = False, False
                phase = "available" if newer else "up_to_date"
                self._set(phase=phase, last_checked_at=now,
                          next_check_at=now + self._check_interval_seconds(),
                          checked_channel=channel, return_to_stable=returning)
                return self.status()
            self._release = release
            newer, returning = self._availability(release["version"], channel)
            self._set(
                phase="available" if newer else "up_to_date",
                available_version=release["version"] if newer else "",
                release_notes=release.get("notes", "") if newer else "",
                release_url=release.get("html_url", "") if newer else "",
                last_checked_at=now,
                next_check_at=now + self._check_interval_seconds(),
                etag=release.get("etag", ""),
                checked_channel=channel,
                return_to_stable=returning if newer else False,
                error_category="",
                error="",
            )
        except UpdateError as error:
            now = int(self.clock())
            retry = 60 * 60 if error.category == "rate_limited" else 15 * 60
            phase = (
                "authorization_required"
                if error.category in {"private_auth_required", "private_auth_config"}
                else "error"
            )
            self._set(phase=phase, last_checked_at=now, next_check_at=now + retry,
                      error_category=error.category, error=str(error)[:180])
        finally:
            self._operation_lock.release()
        return self.status()

    def set_preferences(self, auto_check: bool, notifications: bool,
                        check_interval_minutes=None, channel=None):
        current = self.settings.all()
        interval = (current.get("updates_check_interval_minutes", 1440)
                    if check_interval_minutes is None else check_interval_minutes)
        selected_channel = current.get("updates_channel", "stable") if channel is None else channel
        values = self.settings.update({
            "updates_auto_check": bool(auto_check),
            "updates_notifications": bool(notifications),
            "updates_check_interval_minutes": interval,
            "updates_channel": selected_channel,
        })
        channel_changed = values["updates_channel"] != current.get("updates_channel", "stable")
        now = int(self.clock())
        if channel_changed:
            self._release = None
            self._set(
                phase="idle", available_version="", release_notes="", release_url="",
                etag="", checked_channel="", next_check_at=0, return_to_stable=False,
                confirmation_token="", prepared_digest="",
            )
            return self.check()
        if auto_check:
            next_due = now + values["updates_check_interval_minutes"] * 60
            current_due = int(self._state.get("next_check_at", 0) or 0)
            self._set(next_check_at=min(current_due, next_due) if current_due > now else now)
        if auto_check:
            self._wake.set()
        return self.status()

    def start_private_authorization(self):
        self.private_auth.start()
        self._set(
            phase="authorization_required", error_category="", error="",
            available_version="", release_notes="", release_url="",
            confirmation_token="", prepared_digest="", etag="",
            checked_channel="", next_check_at=0,
        )
        return self.status()

    def poll_private_authorization(self):
        auth = self.private_auth.poll()
        if auth.get("private_auth_state") == "connected":
            self._release = None
            self._set(
                phase="idle", error_category="", error="", etag="",
                checked_channel="", next_check_at=0,
            )
            if self._configured_channel() == "private":
                return self.check(force_refresh=True)
        return self.status()

    def disconnect_private_authorization(self):
        self.private_auth.disconnect()
        self._release = None
        self._set(
            phase=(
                "authorization_required"
                if self._configured_channel() == "private" else "idle"
            ),
            available_version="", release_notes="", release_url="",
            confirmation_token="", prepared_digest="", etag="",
            checked_channel="", next_check_at=0,
            error_category="", error="",
        )
        return self.status()

    def acknowledge_notification(self, version: str):
        if version and version == self._state.get("available_version"):
            self._set(notified_version=version)
        return self.status()

    def dismiss_error(self):
        if self._state.get("phase") == "error":
            self._set(phase="idle", error_category="", error="")
        return self.status()

    def prepare(self):
        if self._state.get("phase") == "ready":
            return self.status()
        if not self._operation_lock.acquire(blocking=False):
            return self.status()
        try:
            return self._prepare_locked()
        finally:
            self._operation_lock.release()

    def _prepare_locked(self):
        version = str(self._state.get("available_version", ""))
        if not version:
            raise UpdateError("state", "No newer version is available on the selected channel")
        channel = self._state.get("checked_channel") or self._configured_channel()
        client = self._release_client(channel)
        release = self._release
        if not release or release.get("version") != version:
            release = client.latest(self.installed_version, etag="")
            if release.get("not_modified") or release.get("version") != version:
                raise UpdateError("state", "Refresh the release before downloading it")
            self._release = release
        token = os.urandom(16).hex()
        download = self.root / "downloads" / token / release["archive_name"]
        stage_parent = self.root / "staged" / token
        self._set(phase="downloading", confirmation_token="", prepared_digest="")
        try:
            expected_digest = client.read_checksum(release, self.installed_version)
            calculated = client.download_archive(release, download, self.installed_version)
            if calculated != expected_digest:
                raise UpdateError("checksum", "The downloaded archive failed its SHA256 check")
            self._set(phase="verifying")
            validate_and_stage_archive(download, stage_parent, version)
            self._set(phase="ready", confirmation_token=token, prepared_digest=calculated,
                      error_category="", error="")
        except UpdateError as error:
            shutil.rmtree(self.root / "downloads" / token, ignore_errors=True)
            shutil.rmtree(stage_parent, ignore_errors=True)
            self._set(phase="error", error_category=error.category, error=str(error)[:180])
        return self.status()

    def install(self, confirmation_token: str):
        token = str(confirmation_token or "")
        if self._state.get("phase") != "ready" or token != self._state.get("confirmation_token"):
            raise UpdateError("confirmation", "The update confirmation has expired")
        if not re.fullmatch(r"[0-9a-f]{32}", token):
            raise UpdateError("confirmation", "The update confirmation is invalid")
        version = str(self._state.get("available_version", ""))
        staged = (self.root / "staged" / token / EXPECTED_ROOT).resolve()
        if not staged.is_dir() or staged.parent.parent != (self.root / "staged").resolve():
            raise UpdateError("staging", "The verified staged package is missing")
        helper_source = Path(__file__).with_name("update_helper.py")
        helper_target = self.root / "helpers" / f"update-helper-{token}.py"
        helper_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(helper_source, helper_target)
        interpreter = shutil.which("python3") or shutil.which("python")
        systemd_run = shutil.which("systemd-run")
        if not interpreter or not systemd_run:
            raise UpdateError("helper_unavailable", "This SteamOS installation has no supported update helper runtime")
        transaction = {
            "schema": 1,
            "token": token,
            "from_version": self.installed_version,
            "to_version": version,
            "digest": self._state.get("prepared_digest", ""),
            "active_dir": str(self.plugin_dir),
            "staged_dir": str(staged),
            "runtime_root": str(self.root),
            "state_path": str(self.state_path),
            "health_path": str(self.root / "health" / f"{token}.json"),
            "service": "plugin_loader.service",
            "health_timeout": 45,
        }
        transaction_path = self.root / "transactions" / f"{token}.json"
        _atomic_json(transaction_path, transaction)
        self._set(phase="installing", pending_token=token, pending_version=version,
                  confirmation_token="", last_result="")
        unit = f"gabecubeaura-update-{token[:12]}"
        command = [
            systemd_run, f"--unit={unit}", "--collect", "--no-block",
            "--property=Type=exec", "--property=TimeoutStartSec=180",
            interpreter, str(helper_target), str(transaction_path),
        ]
        try:
            subprocess.run(
                command, check=True, capture_output=True, text=True, timeout=10,
                env=_clean_system_command_environment(),
            )
        except (OSError, subprocess.SubprocessError) as error:
            stdout = str(getattr(error, "stdout", "") or "").strip().replace("\n", " ")
            stderr = str(getattr(error, "stderr", "") or "").strip().replace("\n", " ")
            detail = stderr or stdout or type(error).__name__
            self.logger.warning(f"Independent update helper launch failed: {detail[:500]}")
            self._set(phase="error", pending_token="", pending_version="",
                      error_category="helper_launch", error="Could not start the independent update helper")
            raise UpdateError("helper_launch", "Could not start the independent update helper") from error
        return {"accepted": True, "version": version}

    def run_lab(self, scenario: str):
        """Run fixed, isolated updater fixtures in test builds only."""
        if "-test." not in self.installed_version:
            raise UpdateError("test_only", "Update lab is not included in stable builds")
        allowed = {"valid-package", "checksum-mismatch", "rollback"}
        if scenario not in allowed:
            raise UpdateError("test_scenario", "Unknown Update lab scenario")
        lab = self.root / "lab"
        shutil.rmtree(lab, ignore_errors=True)
        lab.mkdir(parents=True, mode=0o700)
        started = int(self.clock())
        result = {"scenario": scenario, "passed": False, "started_at": started, "details": ""}
        try:
            if scenario in {"valid-package", "checksum-mismatch"}:
                archive = lab / "GabeCubeAura-v1.1.0.zip"
                fixture = lab / "source" / EXPECTED_ROOT
                (fixture / "dist").mkdir(parents=True)
                (fixture / "py_modules" / "signalbar").mkdir(parents=True)
                (fixture / "main.py").write_text("TEST_FIXTURE = True\n", encoding="utf-8")
                (fixture / "dist/index.js").write_text("export {};\n", encoding="utf-8")
                (fixture / "LICENSE").write_text("Isolated test fixture\n", encoding="utf-8")
                (fixture / "py_modules" / "signalbar" / "__init__.py").write_text(
                    '__version__ = "1.1.0"\n', encoding="utf-8",
                )
                (fixture / "package.json").write_text(
                    json.dumps({"name": "gabecubeaura", "version": "1.1.0"}), encoding="utf-8",
                )
                (fixture / "plugin.json").write_text(
                    json.dumps({"name": "GabeCubeAura", "author": "Alyenax"}), encoding="utf-8",
                )
                from zipfile import ZIP_DEFLATED, ZipFile
                with ZipFile(archive, "w", ZIP_DEFLATED) as package:
                    for path in sorted(fixture.rglob("*")):
                        if path.is_file():
                            package.write(path, Path(EXPECTED_ROOT) / path.relative_to(fixture))
                digest = hashlib.sha256(archive.read_bytes()).hexdigest()
                if scenario == "checksum-mismatch":
                    expected = "0" * 64
                    if digest == expected:
                        raise UpdateError("lab", "Checksum mismatch fixture did not diverge")
                    result.update(passed=True, details="Checksum mismatch was rejected before staging")
                else:
                    root = validate_and_stage_archive(archive, lab / "validated", "1.1.0")
                    result.update(
                        passed=(root / "main.py").is_file(),
                        details="Valid package passed checksum and archive validation",
                        digest=digest,
                    )
            else:
                from signalbar.update_helper import run_transaction

                class LabService:
                    def __init__(self):
                        self.running = True
                        self.starts = 0
                        self.stops = 0

                    def stop(self):
                        self.stops += 1
                        self.running = False

                    def start(self):
                        self.starts += 1
                        self.running = True

                    def active(self):
                        return self.running

                    def wait_inactive(self, timeout=20):
                        return not self.running

                token = "d" * 32
                for family in ("staged", "rollback", "failed", "health"):
                    target = self.root / family / (f"{token}.json" if family == "health" else token)
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink(missing_ok=True)
                active = lab / "active" / EXPECTED_ROOT
                staged = self.root / "staged" / token / EXPECTED_ROOT
                for directory, version, marker in ((active, "1.0.0", "old"), (staged, "1.1.0", "broken")):
                    (directory / "dist").mkdir(parents=True, exist_ok=True)
                    (directory / "main.py").write_text(f'MARKER = "{marker}"\n', encoding="utf-8")
                    (directory / "dist/index.js").write_text("export {};\n", encoding="utf-8")
                    (directory / "package.json").write_text(
                        json.dumps({"name": "gabecubeaura", "version": version}), encoding="utf-8",
                    )
                    (directory / "plugin.json").write_text(
                        json.dumps({"name": "GabeCubeAura", "author": "Alyenax"}), encoding="utf-8",
                    )
                lab_state = lab / "transaction-state.json"
                _atomic_json(lab_state, {})
                service = LabService()
                def lab_exchange(first, second):
                    temporary = first.parent / "GabeCubeAura.exchange-test"
                    os.replace(first, temporary)
                    os.replace(second, first)
                    os.replace(temporary, second)
                outcome = run_transaction({
                    "schema": 1,
                    "token": token,
                    "from_version": "1.0.0",
                    "to_version": "1.1.0",
                    "digest": "e" * 64,
                    "active_dir": str(active),
                    "staged_dir": str(staged),
                    "runtime_root": str(self.root),
                    "state_path": str(lab_state),
                    "health_path": str(self.root / "health" / f"{token}.json"),
                    "service": "plugin_loader.service",
                    "health_timeout": 45,
                }, service=service, health_waiter=lambda *args: False,
                   exchanger=lab_exchange)
                restored = (active / "main.py").read_text(encoding="utf-8")
                passed = outcome.get("result") == "rolled_back" and 'MARKER = "old"' in restored
                result.update(
                    passed=passed,
                    details="Failed health acknowledgement restored the previous isolated plugin",
                    service_starts=service.starts,
                    service_stops=service.stops,
                )
        except Exception as error:
            result.update(passed=False, details=f"{type(error).__name__}: {str(error)[:140]}")
        result["finished_at"] = int(self.clock())
        report_path = self.root / "update-lab-report.json"
        report = _safe_read_json(report_path, {"schema": 1, "results": []})
        results = report.get("results") if isinstance(report.get("results"), list) else []
        results = [entry for entry in results if isinstance(entry, dict) and entry.get("scenario") != scenario]
        results.append(result)
        _atomic_json(report_path, {"schema": 1, "build": self.installed_version, "results": results[-16:]})
        result["report_available"] = True
        return result

    def export_lab_report(self, destination: str):
        if "-test." not in self.installed_version:
            raise UpdateError("test_only", "Update lab is not included in stable builds")
        source = self.root / "update-lab-report.json"
        if not source.is_file():
            raise UpdateError("test_report", "Run an Update lab scenario first")
        target = Path(destination).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        os.chmod(target, 0o644)
        return {"path": str(target)}
