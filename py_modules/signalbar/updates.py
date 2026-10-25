"""Verified GitHub release discovery and staged GabeCubeAura updates."""

from __future__ import annotations

import hashlib
import base64
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
import uuid
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import HTTPSHandler, Request, build_opener, HTTPRedirectHandler
from zipfile import BadZipFile, ZipFile
from http.client import HTTPException
from .distribution import supports_private_tools, require_private_tools


from .product import PRODUCT, PACKAGE, SLUG, REPO, PRIVATE_REPO, PRIVATE_ID, CLIENT_ID

OWNER = "Alyenax"
REPOSITORY = REPO
API_URL = f"https://api.github.com/repos/{OWNER}/{REPOSITORY}/releases/latest"
RELEASES_API_URL = f"https://api.github.com/repos/{OWNER}/{REPOSITORY}/releases?per_page=50"
TEST_RELEASE_API_URL = f"https://api.github.com/repos/{OWNER}/{REPOSITORY}/releases/tags/v1.1.0"
PRIVATE_OWNER = "Alyenax"
PRIVATE_REPOSITORY = PRIVATE_REPO
PRIVATE_REPOSITORY_ID = PRIVATE_ID
# Public identifier for the repository-scoped GitHub App. Release access is
# read-only in normal use; Lab diagnostics can write only their fixed reports/
# JSON path. No client secret is embedded in the plugin.
PRIVATE_GITHUB_CLIENT_ID = CLIENT_ID
PRIVATE_RELEASES_API_URL = (
    f"https://api.github.com/repos/{PRIVATE_OWNER}/{PRIVATE_REPOSITORY}/releases?per_page=50"
)
DEVICE_CODE_URL = "https://github.com/login/device/code"
ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
EXPECTED_ROOT = PRODUCT
CHECK_INTERVAL_MINUTES = {60, 180, 360, 720, 1440}
STARTUP_DELAY_SECONDS = 20
HEALTHY_TRANSACTION_RECOVERY_SECONDS = 5
MAX_METADATA_BYTES = 512 * 1024
MAX_CHECKSUM_BYTES = 64 * 1024
from .archive_policy import (MAX_ARCHIVE_BYTES, MAX_UNCOMPRESSED_BYTES,
                             MAX_ARCHIVE_ENTRIES, MAX_MANIFEST_BYTES, CHUNK_BYTES, require_space, check_zip_envelope)
BUNDLE_MANIFEST = "update-manifest.json"
COMPONENT_PATHS = {
    "plugin": PurePosixPath("."),
    "faceplate-service": PurePosixPath("components/faceplate-service"),
    "pixel-studio": PurePosixPath("components/pixel-studio"),
}
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


LAB114_ROLLBACK_SHA256 = "8dbd281e887cb6f08343059303e04d8055408b72ad05f4e9e207f8ab8191626c"


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
    """Compatibility facade: no authentication or private network access."""
    def __init__(self, path, **_kwargs): self.path = Path(path)
    def status(self):
        return {'private_auth_configured': False, 'private_auth_state': 'disconnected',
                'private_user_code': '', 'private_verification_uri': '', 'private_error': ''}
    def suspend(self): pass
    def resume(self): pass
    def access_token(self): raise RuntimeError('Private updates are unavailable')
    def start(self): raise RuntimeError('Private updates are unavailable')
    def poll(self): raise RuntimeError('Private updates are unavailable')
    def disconnect(self):
        # Only an explicit reset/forget operation may remove a legacy credential.
        self.path.unlink(missing_ok=True)



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
        expected_archive = f"{PRODUCT.replace(chr(32), chr(45))}-v{version}.zip"
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

    def download_archive(self, release: dict, destination: Path, installed_version: str,
                         *, cancelled=None, progress=None):
        request = self._request(release["archive_url"], installed_version)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".part")
        digest = hashlib.sha256()
        total = 0
        deadline = time.monotonic() + 300
        try:
            expected_size = int(release["archive_size"])
            if not 0 < expected_size <= MAX_ARCHIVE_BYTES:
                raise UpdateError("archive_size", "Archive must be at most 1 GiB")
            try:
                require_space(destination.parent, expected_size)
            except OSError as error:
                raise UpdateError("disk_space", str(error)) from error
            with self._open(request, timeout=15) as response, temporary.open("wb") as handle:
                length = response.headers.get("Content-Length")
                if length and (int(length) < 0 or int(length) > MAX_ARCHIVE_BYTES):
                    raise UpdateError("archive_size", "Archive must be at most 1 GiB")
                while True:
                    if cancelled and cancelled():
                        raise UpdateError("cancelled", "Archive preparation cancelled")
                    if time.monotonic() > deadline:
                        raise UpdateError("archive_download", "Archive download exceeded five minutes. Retry on a stable connection.")
                    chunk = response.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_ARCHIVE_BYTES or total > expected_size:
                        raise UpdateError("archive_size", "Archive exceeds 1 GiB")
                    digest.update(chunk)
                    handle.write(chunk)
                    if progress:
                        progress(total, expected_size)
                handle.flush()
                os.fsync(handle.fileno())
            if cancelled and cancelled():
                raise UpdateError("cancelled", "Archive preparation cancelled")
            if total != expected_size:
                raise UpdateError("archive_size", "The downloaded archive size does not match GitHub")
            os.replace(temporary, destination)
            return digest.hexdigest()
        except UpdateError:
            temporary.unlink(missing_ok=True)
            raise
        except (HTTPError, URLError, HTTPException, TimeoutError, OSError, ValueError) as error:
            temporary.unlink(missing_ok=True)
            raise UpdateError("archive_download", "Could not download the release archive") from error


def _sha256_file(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(64 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _manifest_relative_path(value):
    text = str(value or "")
    if not text or "\\" in text or text.startswith("/"):
        raise UpdateError("bundle_manifest", "The component manifest contains an unsafe path")
    path = PurePosixPath(text)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise UpdateError("bundle_manifest", "The component manifest contains an unsafe path")
    return path


def _component_root(root: Path, component: str):
    relative = COMPONENT_PATHS[component]
    return root if component == "plugin" else root.joinpath(*relative.parts)


def _component_disk_files(root: Path, component: str):
    base = _component_root(root, component)
    if not base.is_dir() or base.is_symlink():
        return {}
    result = {}
    for path in sorted(base.rglob("*")):
        if path.is_symlink():
            raise UpdateError("bundle_manifest", "A staged component contains a symbolic link")
        if not path.is_file():
            continue
        relative = path.relative_to(base)
        if component == "plugin" and (
            relative.as_posix() == BUNDLE_MANIFEST
            or relative.parts and relative.parts[0] == "components"
        ):
            continue
        result[relative.as_posix()] = path
    return result


def _legacy_bundle_contract(root: Path, expected_version: str):
    return {
        "schema": 0,
        "product": PRODUCT,
        "version": expected_version,
        "legacy_plugin_only": True,
        "components": [{
            "id": "plugin",
            "version": expected_version,
            "required": True,
            "files": [],
            "executables": [],
        }],
    }


def read_bundle_contract(root: Path, expected_version: str):
    """Validate the optional multi-component manifest from an extracted ZIP.

    Archives produced before the companion service remain accepted as an
    explicit plugin-only contract. A schema-1 manifest is closed over the
    three known component identifiers and hashes every installed file.
    """
    path = root / BUNDLE_MANIFEST
    if not path.exists():
        return _legacy_bundle_contract(root, expected_version)
    if not path.is_file() or path.is_symlink():
        raise UpdateError("bundle_manifest", "The update manifest is not a regular file")
    try:
        if path.stat().st_size > MAX_MANIFEST_BYTES:
            raise UpdateError("bundle_manifest", "The update manifest is too large")
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except UpdateError:
        raise
    except (OSError, ValueError, TypeError) as error:
        raise UpdateError("bundle_manifest", "The update manifest is invalid") from error
    if (not isinstance(manifest, dict) or manifest.get("schema") != 1
            or manifest.get("product") != PRODUCT
            or manifest.get("version") != expected_version):
        raise UpdateError("bundle_manifest", "The update manifest identity does not match the release")
    raw_components = manifest.get("components")
    if not isinstance(raw_components, list) or not 1 <= len(raw_components) <= len(COMPONENT_PATHS):
        raise UpdateError("bundle_manifest", "The update manifest has an invalid component list")
    components = []
    seen = set()
    for raw in raw_components:
        if not isinstance(raw, dict):
            raise UpdateError("bundle_manifest", "The update manifest has an invalid component")
        component = str(raw.get("id", ""))
        if component not in COMPONENT_PATHS or component in seen or (PRODUCT == "Decky Vocal Assistant" and component != "plugin"):
            raise UpdateError("bundle_manifest", "The update manifest has an unknown or duplicate component")
        seen.add(component)
        if raw.get("version") != expected_version:
            raise UpdateError("bundle_manifest", "A component version does not match the release")
        required = raw.get("required")
        if type(required) is not bool or (component == "plugin" and not required):
            raise UpdateError("bundle_manifest", "A component has an invalid required flag")
        raw_files = raw.get("files")
        if not isinstance(raw_files, list) or not raw_files or len(raw_files) > MAX_ARCHIVE_ENTRIES:
            raise UpdateError("bundle_manifest", "A component has an invalid file list")
        disk_files = _component_disk_files(root, component)
        records = []
        listed = set()
        for record in raw_files:
            if not isinstance(record, dict):
                raise UpdateError("bundle_manifest", "A component file record is invalid")
            relative = _manifest_relative_path(record.get("path")).as_posix()
            digest = str(record.get("sha256", "")).lower()
            try:
                size = int(record.get("size"))
            except (TypeError, ValueError, OverflowError) as error:
                raise UpdateError("bundle_manifest", "A component file size is invalid") from error
            if relative in listed or not HEX_DIGEST.fullmatch(digest) or size < 0:
                raise UpdateError("bundle_manifest", "A component file record is invalid")
            listed.add(relative)
            staged = disk_files.get(relative)
            if staged is None or staged.stat().st_size != size or _sha256_file(staged) != digest:
                raise UpdateError("bundle_checksum", f"The staged {component} component failed verification")
            records.append({"path": relative, "size": size, "sha256": digest})
        if listed != set(disk_files):
            raise UpdateError("bundle_manifest", f"The staged {component} file set is not fully declared")
        executables = raw.get("executables", [])
        if not isinstance(executables, list):
            raise UpdateError("bundle_manifest", "A component executable list is invalid")
        clean_executables = []
        for value in executables:
            relative = _manifest_relative_path(value).as_posix()
            if relative not in listed or relative in clean_executables:
                raise UpdateError("bundle_manifest", "A component executable is not a declared file")
            clean_executables.append(relative)
            os.chmod(disk_files[relative], 0o755)
        components.append({
            "id": component,
            "version": expected_version,
            "required": required,
            "files": records,
            "executables": clean_executables,
        })
    if "plugin" not in seen:
        raise UpdateError("bundle_manifest", "The update manifest does not declare the plugin")
    return {
        "schema": 1,
        "product": PRODUCT,
        "version": expected_version,
        "legacy_plugin_only": False,
        "components": components,
    }


def validate_and_stage_archive(archive_path: Path, staging_parent: Path, expected_version: str,
                               *, cancelled=None):
    """Validate and extract one Decky archive without trusting ZIP paths."""
    _version_tuple(expected_version, allow_test=True)
    if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise UpdateError("archive_size", "The archive is larger than the allowed limit")
    # Never erase a caller's existing directory or follow a staging symlink.
    if staging_parent.exists() or any(p.is_symlink() for p in (staging_parent, *staging_parent.parents)):
        raise UpdateError("archive_path", "Staging directory must be new and contain no symbolic links")
    staging_parent.mkdir(parents=True, mode=0o700)
    names = set()
    total = 0
    try:
        check_zip_envelope(archive_path)
        with ZipFile(archive_path) as archive:
            infos = archive.infolist()
            if not infos or len(infos) > MAX_ARCHIVE_ENTRIES:
                raise UpdateError("archive_entries", "The archive contains an invalid number of entries")
            for info in infos:
                name = info.filename
                if (not name or "\\" in name or name.startswith("/")
                        or len(name.encode('utf-8')) > 1024 or len(info.extra) > 4096
                        or info.orig_filename != name or any(ord(c) < 32 for c in name)):
                    raise UpdateError("archive_path", "The archive contains an unsafe path")
                parts = tuple(name.rstrip("/").split("/"))
                if not parts or parts[0] != EXPECTED_ROOT or any(part in {"", ".", ".."} for part in parts):
                    raise UpdateError("archive_path", "The archive must contain one GabeCubeAura directory")
                normalized = "/".join(parts)
                if normalized in names:
                    raise UpdateError("archive_duplicate", "The archive contains a duplicate path")
                names.add(normalized)
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise UpdateError("archive_symlink", "The archive contains a symbolic link")
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR) or info.flag_bits & 1:
                    raise UpdateError("archive_path", "Special or encrypted archive entries are not supported")
                total += int(info.file_size)
                if total > MAX_UNCOMPRESSED_BYTES:
                    raise UpdateError("archive_size", "The extracted archive would be too large")
            try:
                require_space(staging_parent, total)
            except OSError as error:
                raise UpdateError("disk_space", str(error)) from error
            extracted = 0
            for info in infos:
                if cancelled and cancelled():
                    raise UpdateError("cancelled", "Archive preparation cancelled")
                parts = PurePosixPath(info.filename).parts
                destination = staging_parent.joinpath(*parts)
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, destination.open("wb") as target:
                    member_size = 0
                    while True:
                        if cancelled and cancelled():
                            raise UpdateError("cancelled", "Archive preparation cancelled")
                        block = source.read(CHUNK_BYTES)
                        if not block:
                            break
                        member_size += len(block)
                        extracted += len(block)
                        if extracted > MAX_UNCOMPRESSED_BYTES or member_size > info.file_size:
                            raise UpdateError("archive_size", "Extracted archive exceeds its bounded size")
                        target.write(block)
                    if member_size != info.file_size:
                        raise UpdateError("archive_size", "Extracted entry size differs from ZIP metadata")
                os.chmod(destination, 0o644)
    except UpdateError:
        shutil.rmtree(staging_parent, ignore_errors=True)
        raise
    except (BadZipFile, OSError, RuntimeError, ValueError) as error:
        shutil.rmtree(staging_parent, ignore_errors=True)
        raise UpdateError("archive", "The release archive is corrupt or unreadable") from error

    root = staging_parent / EXPECTED_ROOT
    missing = [name for name in REQUIRED_FILES if not (root / name).is_file()]
    if missing:
        shutil.rmtree(staging_parent, ignore_errors=True)
        raise UpdateError("package", f"The package is missing {missing[0]}")
    try:
        if any((root / name).stat().st_size > MAX_METADATA_BYTES for name in ("package.json", "plugin.json")):
            raise ValueError("oversized package metadata")
        package = json.loads((root / "package.json").read_text(encoding="utf-8"))
        plugin = json.loads((root / "plugin.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as error:
        shutil.rmtree(staging_parent, ignore_errors=True)
        raise UpdateError("package", "The package manifests are invalid") from error
    if package.get("name") != PACKAGE or package.get("version") != expected_version:
        shutil.rmtree(staging_parent, ignore_errors=True)
        raise UpdateError("package", "The package name or version does not match the release")
    if plugin.get("name") != PRODUCT:
        shutil.rmtree(staging_parent, ignore_errors=True)
        raise UpdateError("package", "The Decky plugin name does not match this product")
    try:
        read_bundle_contract(root, expected_version)
    except UpdateError:
        shutil.rmtree(staging_parent, ignore_errors=True)
        raise
    return root


class UpdateManager:
    """Own release state, background checks and transaction preparation."""

    def __init__(self, installed_version: str, settings, runtime_dir: str, plugin_dir: str,
                 logger, client=None, private_auth=None, clock=time.time,
                 monotonic=time.monotonic, companion_root=None):
        self.installed_version = installed_version
        self.settings = settings
        self.runtime_dir = Path(runtime_dir).resolve()
        self.plugin_dir = Path(plugin_dir).resolve()
        user_home = Path(os.environ.get("DECKY_USER_HOME", "/home/deck"))
        self.companion_root = Path(
            companion_root or user_home / f".local/share/{SLUG}/components"
        ).resolve()
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
        self._prepare_cancel = threading.Event()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._release = None
        self._auto_install_generation = 0
        self._automatic_preparing = False
        self._preferences_generation = 0
        self._release_context = None
        self._check_pending = False
        from .recovery import RecoveryVault
        self.recovery = RecoveryVault(
            self.root, self.settings.path, self.companion_root.parent,
        )
        self._recovery_retry_after = 0.0
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
        state.pop("next_aggressive_check_at", None)  # Lab186 had an extra fixed cadence.
        state.pop("aggressive_check_minutes", None)
        state.setdefault("automatic_retry_at", 0)
        state.setdefault("auto_attempt_version", "")
        state.setdefault("auto_attempt_channel", "")
        state.setdefault("notified_version", "")
        state.setdefault("etag", "")
        state.setdefault("checked_channel", "")
        state.setdefault("return_to_stable", False)
        state.setdefault("error_category", "")
        state.setdefault("error", "")
        state.setdefault("release_notes", "")
        state.setdefault("release_url", "")
        state.setdefault("prepared_digest", "")
        state.setdefault("prepared_components", [])
        state.setdefault("confirmation_token", "")
        state.setdefault("pending_token", "")
        state.setdefault("pending_version", "")
        state.setdefault("rollback_version", "")
        state.setdefault("last_result", "")
        state.setdefault("completed_token", "")
        state["installed_version"] = self.installed_version
        if (not supports_private_tools(self.installed_version)
                and not state.get("pending_token") and not state.get("recovery_source_token")
                and (self.settings.all().get("updates_channel") == "private"
                     or state.get("checked_channel") == "private")):
            # A public installation must not offer a previously staged private
            # release or demand inherited authorization. Keep credentials,
            # local backups and in-progress transaction health intact.
            state.update(phase="idle", available_version="", release_notes="",
                         release_url="", prepared_digest="", prepared_components=[],
                         confirmation_token="", checked_channel="", etag="",
                         error_category="", error="", next_check_at=0,
                         return_to_stable=False)
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
            if state.get("phase") == "ready" and (state.get("recovery_source_token")):
                stale_available = False
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
        if state.get("phase") in {"downloading", "verifying"} and not state.get("pending_token"):
            token = str(state.get("preparation_token", ""))
            if re.fullmatch(r"[0-9a-f]{32}", token):
                for family in ("downloads", "staged"):
                    target = self.root / family / token
                    if target.is_dir() and not target.is_symlink():
                        shutil.rmtree(target)
            state.update(phase="error", error_category="interrupted", preparation_token="",
                         error="Archive preparation was interrupted. The installed version is unchanged; download again.")
        if state.get("phase") == "preparing_install" and not state.get("pending_token"):
            state.update(phase="error", error_category="interrupted",
                         error="Installation preparation was interrupted. Retry the verified update.")
        return state

    def _cleanup_completed_transaction(self):
        token = str(self._state.get("completed_token", ""))
        if not re.fullmatch(r"[0-9a-f]{32}", token) or self._state.get("pending_token"):
            return
        previous = self.root / "rollback" / token / EXPECTED_ROOT
        if self._state.get("last_result") == "updated" and previous.is_dir():
            if self.monotonic() < self._recovery_retry_after:
                return
            try:
                self.recovery.capture(token, self._state.get("rollback_version", ""), previous)
                self._state["recovery_error"] = ""
            except Exception as error:
                # Never delete the only previous package when preservation fails.
                self._state["recovery_error"] = str(error)[:180]
                self._recovery_retry_after = self.monotonic() + 60
                self._save()
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
        retained = str(self._state.get("completed_token", ""))
        for family in ("downloads", "staged", "rollback", "failed", "helpers", "transactions", "health"):
            directory = self.root / family
            if not directory.is_dir():
                continue
            for target in list(directory.iterdir())[:256]:
                if pending and pending in target.name:
                    continue
                if family == "rollback" and retained and retained in target.name:
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
            self._cleanup_completed_transaction()

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self.root.mkdir(parents=True, exist_ok=True)
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="gabecubeaura-updates", daemon=True)
            self._thread.start()

    def stop(self, timeout=2):
        self.private_auth.suspend()
        with self._lock:
            self._preferences_generation+=1
            self._release_context=None
            self._check_pending=False
        self._stop.set()
        self._prepare_cancel.set()
        self._wake.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=max(0.0, float(timeout)))

    def _run(self):
        initial = STARTUP_DELAY_SECONDS + random.uniform(0, 30)
        if self._stop.wait(initial):
            return
        self._check_on_startup()
        while not self._stop.is_set():
            try:
                self._automatic_tick()
            except Exception as error:
                self.logger.warning(f"[GabeCubeAura] background update failed: {error}")
            self._wake.wait(30)
            self._wake.clear()

    def _automatic_tick(self):
        """Use the chosen interval for checks, with or without automatic install."""
        values = self.settings.all()
        if not (values.get("updates_auto_check", True) or values.get("updates_auto_install", False)):
            return self.status()
        now = self.clock()
        with self._lock:
            due = now >= float(self._state.get("next_check_at", 0))
            retry = float(self._state.get("automatic_retry_at", 0))
            protected_recovery = bool(self._state.get("recovery_source_token") or self._state.get("lab114_rollback"))
            prepared = self._state.get("phase") == "ready"
        if now >= retry and due and not protected_recovery:
            self.check(force_refresh=prepared)
        if values.get("updates_auto_install", False):
            self._automatic_update()
        return self.status()

    def _require_automatic_context(self, channel, generation, auto_generation):
        self._require_update_context(channel, generation)
        if (self._stop.is_set() or auto_generation != self._auto_install_generation
                or not self.settings.all().get("updates_auto_install", False)):
            raise UpdateError("cancelled", "Automatic installation is disabled")

    def _automatic_update(self):
        """Opt-in only; latest verified newer release, never a recovery package."""
        if not self._operation_lock.acquire(blocking=False):
            return self.status()
        try:
            with self._lock:
                if (self._stop.is_set() or not self.settings.all().get("updates_auto_install", False)
                        or self._state.get("phase") not in {"available", "ready"}
                        or self._state.get("pending_token") or self._state.get("recovery_source_token")
                        or self._state.get("lab114_rollback")):
                    return self.status()
                channel = self._configured_channel()
                generation = self._preferences_generation
                auto_generation = self._auto_install_generation
                version = str(self._state.get("available_version", ""))
                if (version == self._state.get("auto_attempt_version")
                        and channel == self._state.get("auto_attempt_channel")):
                    return self.status()
            # A fresh lookup prevents installing an older prepared release.
            self._check_once(True)
            with self._lock:
                self._require_automatic_context(channel, generation, auto_generation)
                if self._state.get("phase") not in {"available", "ready"}:
                    return self.status()
                version = str(self._state.get("available_version", ""))
                if (not version or _version_order(version, allow_test=True)
                        <= _version_order(self.installed_version, allow_test=True)):
                    return self.status()
                if (version == self._state.get("auto_attempt_version")
                        and channel == self._state.get("auto_attempt_channel")):
                    return self.status()
                self._set(auto_attempt_version=version, auto_attempt_channel=channel)
                self._automatic_preparing = True
            if self._state.get("phase") != "ready":
                self._prepare_locked()
            with self._lock:
                self._require_automatic_context(channel, generation, auto_generation)
                if self._state.get("phase") != "ready":
                    return self.status()
                token = self._state.get("confirmation_token", "")
            return self._install_locked(token, automatic_context=(channel, generation, auto_generation))
        except UpdateError as error:
            with self._lock:
                if error.category not in {"cancelled", "superseded"} and not self._state.get("pending_token"):
                    self._set(phase="error", error_category=error.category, error=str(error)[:180])
            return self.status()
        except Exception as error:
            self.logger.warning(f"[GabeCubeAura] automatic installation failed: {type(error).__name__}")
            if not self._state.get("pending_token"):
                self._set(phase="error", error_category="installation", error="Automatic installation failed. Retry manually or turn the option off and on.")
            return self.status()
        finally:
            with self._lock:
                self._automatic_preparing = False
            self._operation_lock.release()

    def _check_on_startup(self):
        values = self.settings.all()
        if not (values.get("updates_auto_check", True) or values.get("updates_auto_install", False)):
            return self.status()
        try:
            return self.check()
        except Exception as error:
            self.logger.warning(f"[GabeCubeAura] startup update check failed: {error}")
            return self.status()

    def _configured_channel(self):
        channel = self.settings.all().get("updates_channel", "stable")
        if channel == "private" and not supports_private_tools(self.installed_version):
            return "stable"
        return channel if channel in {"stable", "beta", "private"} else "stable"

    def _release_client(self, channel=None):
        channel = channel or self._configured_channel()
        if channel == 'private': raise RuntimeError('Private updates are unavailable')
        if self.client is not None: return self.client
        return GitHubReleaseClient(api_url=RELEASES_API_URL if channel == 'beta' else API_URL,
                                   allow_prerelease=channel == 'beta')

    def upload_diagnostic_report(self, report: dict):
        raise RuntimeError('Private delivery is unavailable. Export a local file instead.')

    def upload_configuration_backup(self, payload: bytes):
        raise RuntimeError('Private delivery is unavailable. Export a local file instead.')

    def upload_creation_archive(self, payload: bytes):
        raise RuntimeError('Private delivery is unavailable. Export a local file instead.')

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
                "auto_install": bool(values.get("updates_auto_install", False)),
                "auto_install_paused": bool(values.get("updates_auto_install", False)
                    and result.get("auto_attempt_version")
                    and result.get("auto_attempt_version") == result.get("available_version")
                    and result.get("auto_attempt_channel") == self._configured_channel()
                    and not result.get("pending_token")
                    and result.get("phase") not in {"checking", "downloading", "verifying", "preparing_install", "installing", "restart_pending"}),
                "notifications": bool(values.get("updates_notifications", True)),
                "check_interval_minutes": int(values.get("updates_check_interval_minutes", 1440)),
                "channel": self._configured_channel(),
                "private_tools": supports_private_tools(self.installed_version),
                "test_build": "-test." in self.installed_version,
                "bundle_components": list(result.get("prepared_components", [])),
                "recovery_available": False,
                "recovery_version": "",
                "recovery_prepared": bool(result.get("recovery_source_token")),
                "recovery_preserves_current_settings": bool(result.get("lab114_rollback") and not result.get("recovery_source_token")),
            })
            try:
                recovery = self.recovery.describe()
                result["recovery_available"] = recovery["version"] != self.installed_version
                result["recovery_version"] = recovery["version"]
            except Exception:
                pass
            if supports_private_tools(self.installed_version):
                result.update(self.private_auth.status())
            else:
                result.update(private_auth_configured=False, private_auth_state="disconnected",
                              private_user_code="", private_verification_uri="",
                              private_auth_expires_at=0, private_repository="")
            result.pop("etag", None)
            result.pop("pending_token", None)
            result.pop("completed_token", None)
            result.pop("prepared_components", None)
            return result

    def _require_update_context(self,channel,generation):
        if generation!=self._preferences_generation or channel!=self._configured_channel():
            raise UpdateError('superseded','Update channel changed. Refresh the selected channel.')

    def check(self, force_refresh=False):
        while True:
            if not self._operation_lock.acquire(blocking=False):return self.status()
            try:self._check_once(force_refresh)
            finally:
                with self._lock:
                    self._operation_lock.release()
                    retry=self._check_pending
            if not retry:
                if self.settings.all().get("updates_auto_install", False): self._wake.set()
                return self.status()
            force_refresh=True

    def _check_once(self, force_refresh=False):
        self._reconcile_helper_state()
        ready = dict(self._state) if self._state.get("phase") == "ready" else None
        if self._state.get("phase") in {"downloading", "verifying", "preparing_install", "installing", "restart_pending"} or (ready and not force_refresh):
            return self.status()
        with self._lock:
            channel = self._configured_channel();generation=self._preferences_generation
            self._check_pending=False
            self._set(phase="checking", error_category="", error="", return_to_stable=False)
        try:
            client = self._release_client(channel)
            etag = (
                self._state.get("etag", "")
                if not force_refresh and self._state.get("checked_channel") == channel
                else ""
            )
            release = client.latest(self.installed_version, etag=etag)
            with self._lock:
                self._require_update_context(channel,generation)
                self._release_context=(channel,generation)
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
                              automatic_retry_at=0,
                              checked_channel=channel, return_to_stable=returning)
                    return self.status()
                self._release = release
                if ready and release["version"] == ready.get("available_version"):
                    self._set(phase="ready", error="", error_category="", last_checked_at=now,
                              next_check_at=now + self._check_interval_seconds(),
                              automatic_retry_at=0)
                    return self.status()
                newer, returning = self._availability(release["version"], channel)
                self._set(
                    phase="available" if newer else "up_to_date",
                    available_version=release["version"] if newer else "",
                    release_notes=release.get("notes", "") if newer else "",
                    release_url=release.get("html_url", "") if newer else "",
                    last_checked_at=now,
                    next_check_at=now + self._check_interval_seconds(),
                    automatic_retry_at=0,
                    etag=release.get("etag", ""),
                    checked_channel=channel,
                    return_to_stable=returning if newer else False,
                    error_category="",
                    error="",
                    confirmation_token="", prepared_digest="", prepared_components=[],
                )
        except UpdateError as error:
            with self._lock:
                if generation!=self._preferences_generation or channel!=self._configured_channel():return self.status()
                now = int(self.clock())
                retry = 60 * 60 if error.category == "rate_limited" else 15 * 60
                phase = (
                    "authorization_required"
                    if error.category in {"private_auth_required", "private_auth_config"}
                    else "error"
                )
                self._set(phase=phase, last_checked_at=now, next_check_at=now + retry,
                          automatic_retry_at=now + retry,
                          error_category=error.category, error=str(error)[:180])
        return self.status()

    def set_preferences(self, auto_check: bool, notifications: bool,
                        check_interval_minutes=None, channel=None, auto_install=None):
        with self._lock:
            current = self.settings.all()
            interval = (current.get("updates_check_interval_minutes", 1440)
                        if check_interval_minutes is None else check_interval_minutes)
            selected_channel = current.get("updates_channel", "stable") if channel is None else channel
            if selected_channel == "private":
                if channel is not None:
                    require_private_tools(self.installed_version)
                elif not supports_private_tools(self.installed_version):
                    selected_channel = "stable"
            if selected_channel!=current.get('updates_channel','stable') and self._state.get('phase') in {'preparing_install','installing','restart_pending'}:
                raise UpdateError('busy','Wait for the current installation before changing update channel')
            selected_auto = current.get("updates_auto_install", False) if auto_install is None else bool(auto_install)
            values = self.settings.update({
                "updates_auto_install": selected_auto,
                "updates_auto_check": bool(auto_check),
                "updates_notifications": bool(notifications),
                "updates_check_interval_minutes": interval,
                "updates_channel": selected_channel,
            })
            channel_changed = values["updates_channel"] != current.get("updates_channel", "stable")
            if selected_auto != bool(current.get("updates_auto_install", False)):
                self._auto_install_generation += 1
                self._set(auto_attempt_version="", auto_attempt_channel="")
                if not selected_auto and self._automatic_preparing:
                    self._prepare_cancel.set()
                if selected_auto:
                    self._set(next_check_at=0)
                self._wake.set()
            now = int(self.clock())
            if channel_changed:
                self._preferences_generation+=1
                self._release_context=None
                self._release = None
                self._set(
                    phase="idle", available_version="", release_notes="", release_url="",
                    etag="", checked_channel="", next_check_at=0, return_to_stable=False,
                    confirmation_token="", prepared_digest="",
                )
                self._check_pending=True
                self._prepare_cancel.set()
                self._wake.set()
            if auto_check or selected_auto:
                if values["updates_check_interval_minutes"] != current.get("updates_check_interval_minutes", 1440):
                    # Both a shorter and a longer selection take effect from
                    # the last check; changing cadence cannot bypass backoff.
                    last_checked = float(self._state.get("last_checked_at", 0) or 0)
                    next_due = last_checked + values["updates_check_interval_minutes"] * 60 if last_checked else now
                    self._set(next_check_at=max(now, next_due, float(self._state.get("automatic_retry_at", 0))))
                self._wake.set()

        return self.check() if channel_changed else self.status()

    def start_private_authorization(self):
        raise RuntimeError('Private delivery is unavailable. Export a local file instead.')

    def poll_private_authorization(self):
        raise RuntimeError('Private delivery is unavailable. Export a local file instead.')

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
            self._set(phase="ready" if self._state.get("confirmation_token") else "idle", error_category="", error="")
        return self.status()

    def prepare(self):
        if self._state.get("phase") == "ready":
            return self.status()
        if not self._operation_lock.acquire(blocking=False):
            return self.status()
        try:
            self._prepare_locked()
        finally:
            self._operation_lock.release()
            if self._check_pending:self.check(force_refresh=True)
        return self.status()

    def _prepare_locked(self):
        self._prepare_cancel.clear()
        self._state.pop("recovery_source_token", None)
        self._state.pop("lab114_rollback", None)
        version = str(self._state.get("available_version", ""))
        if not version:
            raise UpdateError("state", "No newer version is available on the selected channel")
        with self._lock:
            channel=self._configured_channel();generation=self._preferences_generation
            if self._state.get('checked_channel')!=channel or self._release_context!=(channel,generation):
                raise UpdateError('state','Refresh the selected channel before preparation')
            release = self._release
        client = self._release_client(channel)
        if not release or release.get("version") != version:
            release = client.latest(self.installed_version, etag="")
            if release.get("not_modified") or release.get("version") != version:
                raise UpdateError("state", "Refresh the release before downloading it")
            with self._lock:
                self._require_update_context(channel,generation)
                self._release = release
        token = os.urandom(16).hex()
        download = self.root / "downloads" / token / release["archive_name"]
        stage_parent = self.root / "staged" / token
        try:
            with self._lock:
                self._require_update_context(channel,generation)
                self._set(phase="downloading", confirmation_token="", prepared_digest="",
                          preparation_token=token, download_bytes=0, download_total_bytes=release['archive_size'])
            expected_digest = client.read_checksum(release, self.installed_version)
            if isinstance(client, GitHubReleaseClient):
                last_progress = [-1]
                def progress(received, total):
                    percent = received * 100 // total
                    if percent != last_progress[0]:
                        last_progress[0] = percent
                        with self._lock:
                            if generation==self._preferences_generation and channel==self._configured_channel():
                                self._state.update(download_bytes=received, download_total_bytes=total)
                calculated = client.download_archive(release, download, self.installed_version,
                    cancelled=self._prepare_cancel.is_set, progress=progress)
            else:
                calculated = client.download_archive(release, download, self.installed_version)
            if calculated != expected_digest:
                raise UpdateError("checksum", "The downloaded archive failed its SHA256 check")
            with self._lock:
                self._require_update_context(channel,generation)
                self._set(phase="verifying")
            staged = validate_and_stage_archive(download, stage_parent, version,
                                                 cancelled=self._prepare_cancel.is_set)
            contract = read_bundle_contract(staged, version)
            if self._prepare_cancel.is_set():
                raise UpdateError("cancelled", "Archive preparation cancelled")
            components = [item["id"] for item in contract["components"]]
            with self._lock:
                self._require_update_context(channel,generation)
                self._set(phase="ready", confirmation_token=token, prepared_digest=calculated, preparation_token="",
                          prepared_components=components, error_category="", error="")
        except UpdateError as error:
            shutil.rmtree(self.root / "downloads" / token, ignore_errors=True)
            shutil.rmtree(stage_parent, ignore_errors=True)
            with self._lock:
                if generation==self._preferences_generation and channel==self._configured_channel():
                    self._set(phase="error", error_category=error.category, error=str(error)[:180], preparation_token="")
        return self.status()

    def cancel_preparation(self):
        # No cancellation once a systemd transaction has begun swapping code.
        with self._lock:
            if self._state.get("phase") in {"downloading", "verifying"}:
                self._prepare_cancel.set()
        return self.status()

    def prepare_lab114_rollback(self):
        raise RuntimeError('Private delivery is unavailable. Export a local file instead.')

    def prepare_previous_version(self):
        """Stage a retained, verified local package using the normal installer."""
        if not self._operation_lock.acquire(blocking=False):
            raise UpdateError("busy", "Another update operation is running")
        try:
            if self._state.get("pending_token"):
                raise UpdateError("busy", "Wait for the current installation to finish")
            metadata, archive, _snapshot = self.recovery.current()
            version = metadata["version"]
            if version == self.installed_version:
                raise UpdateError("recovery", "The retained version is already installed")
            token = os.urandom(16).hex()
            staged = validate_and_stage_archive(archive, self.root / "staged" / token, version)
            contract = read_bundle_contract(staged, version)
            self._set(phase="ready", available_version=version, confirmation_token=token,
                      prepared_digest=metadata["sha256"],
                      prepared_components=[item["id"] for item in contract["components"]],
                      recovery_source_token=metadata["token"],
                      release_notes="Local recovery restores the previous package, settings and saved artwork.",
                      release_url="", error="", error_category="")
            return self.status()
        except UpdateError:
            raise
        except Exception as error:
            raise UpdateError("recovery", str(error)[:180]) from error
        finally:
            self._operation_lock.release()

    def install(self, confirmation_token: str):
        if not self._operation_lock.acquire(blocking=False):
            raise UpdateError("busy", "Another update operation is running")
        try:
            try:
                return self._install_locked(confirmation_token)
            except UpdateError as error:
                if not self._state.get("pending_token"):
                    self._set(phase="error", error_category=error.category, error=str(error)[:180])
                raise
            except Exception as error:
                category = "permissions" if isinstance(error, PermissionError) else "installation"
                message = "Update preparation could not write its files. Check available space and Decky permissions." if isinstance(error, OSError) else "Update preparation failed before Decky could restart. Retry or send the diagnostic report."
                self.logger.warning(f"Update preparation failed: {type(error).__name__}")
                self._set(phase="error", error_category=category, error=message)
                raise UpdateError(category, message) from error
        finally:
            self._operation_lock.release()

    def _install_locked(self, confirmation_token: str, *, automatic_context=None):
        with self._lock:
            if automatic_context is not None:
                self._require_automatic_context(*automatic_context)
            token = str(confirmation_token or "")
            if self._state.get("phase") not in {"ready", "error"} or token != self._state.get("confirmation_token"):
                raise UpdateError("confirmation", "The update confirmation has expired")
            if not re.fullmatch(r"[0-9a-f]{32}", token):
                raise UpdateError("confirmation", "The update confirmation is invalid")
            # This is the commit to installation: preferences may prevent it
            # up to here; an accepted helper transaction must finish/rollback.
            self._set(phase="preparing_install", error="", error_category="")
        version = str(self._state.get("available_version", ""))
        staged = (self.root / "staged" / token / EXPECTED_ROOT).resolve()
        if not staged.is_dir() or staged.parent.parent != (self.root / "staged").resolve():
            raise UpdateError("staging", "The verified staged package is missing")
        contract = read_bundle_contract(staged, version)
        if PRODUCT == 'GabeCubeAura' and (self.plugin_dir.parent / 'Decky Vocal Assistant').exists():
            try:
                generic=staged/'integration-contract.json'
                receipt=json.loads((generic if generic.exists() else staged/'vocal-contract.json').read_text())
                if receipt.get('protocol') != 1 or (receipt.get('capture_owner') is not False if generic.exists() else receipt.get('legacy_voice') is not False): raise ValueError()
                for relative in ('main.py','py_modules/signalbar/backend/engine.py'):
                    if receipt.get('files',{}).get(relative) != hashlib.sha256((staged/relative).read_bytes()).hexdigest(): raise ValueError()
            except (OSError, ValueError, TypeError):
                raise UpdateError('voice_compatibility', 'Remove DVA before restoring a GCA version with embedded voice')
        components = [item["id"] for item in contract["components"]]
        helper_source = Path(__file__).with_name("update_helper.py")
        helper_target = self.root / "helpers" / f"update-helper-{token}.py"
        helper_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(helper_source, helper_target)
        interpreter = shutil.which("python3") or shutil.which("python")
        systemd_run = shutil.which("systemd-run")
        if not interpreter or not systemd_run:
            raise UpdateError("helper_unavailable", "This SteamOS installation has no supported update helper runtime")
        transaction = {
            "schema": 2 if not contract["legacy_plugin_only"] else 1,
            "product": PRODUCT,
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
        if transaction["schema"] == 2:
            transaction.update({
                "components": components,
                "companion_root": str(self.companion_root),
            })
        try:
            snapshot = self.recovery.snapshot(token)
            restore = snapshot
            source_token = str(self._state.get("recovery_source_token", ""))
            if source_token:
                metadata, _archive, restore = self.recovery.current()
                if metadata["token"] != source_token or metadata["version"] != version:
                    raise UpdateError("recovery", "The recovery selection has changed")
            transaction["restore_state"] = {
                "snapshot": str(restore), "failure_snapshot": str(snapshot),
                "settings_path": str(Path(self.settings.path).absolute()),
                "user_root": str(self.companion_root.parent),
            }
        except Exception as error:
            from .update_helper import TransactionError
            detail = str(error) if isinstance(error, TransactionError) else "Not enough space or insufficient permissions for the backup."
            raise UpdateError("recovery", "Could not preserve settings and artwork: " + detail) from error
        transaction_path = self.root / "transactions" / f"{token}.json"
        _atomic_json(transaction_path, transaction)
        self._set(phase="installing", pending_token=token, pending_version=version,
                  confirmation_token="", last_result="", recovery_source_token="")
        unit = f"{SLUG}-update-{token[:12]}"
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
        raise RuntimeError('Private delivery is unavailable. Export a local file instead.')

    def export_lab_report(self, destination: str):
        raise RuntimeError('Private delivery is unavailable. Export a local file instead.')
