"""Durable, local previous-version recovery; never downloads or stores credentials."""

import hashlib
import json
import os
from pathlib import Path
import shutil
from zipfile import ZipFile, ZIP_DEFLATED

from .update_helper import TOKEN, _no_symlink_ancestors, _read_json, snapshot_user_state, verify_snapshot
from .product import PRODUCT
from .archive_policy import MAX_ARCHIVE_BYTES, MAX_UNCOMPRESSED_BYTES, MAX_ARCHIVE_ENTRIES, require_space


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


class RecoveryError(RuntimeError):
    pass


class RecoveryVault:
    def __init__(self, update_root, settings_path, user_root):
        self.root = Path(update_root) / "recovery"
        self.settings_path = Path(settings_path)
        self.user_root = Path(user_root)

    def snapshot(self, token):
        self._token(token)
        directory = self.root / token / "snapshot"
        _no_symlink_ancestors(directory)
        if directory.is_dir() and not (directory / "manifest.json").exists():
            # Only an uncommitted snapshot for this validated transaction.
            # Live files and every completed backup stay untouched.
            shutil.rmtree(directory)
        if not directory.exists():
            snapshot_user_state(self.settings_path, self.user_root, directory)
        verify_snapshot(directory)
        return directory

    def capture(self, token, version, source):
        """Preserve an installed package before transient rollback cleanup."""
        self._token(token)
        source = Path(source)
        _no_symlink_ancestors(source)
        if not source.is_dir() or source.is_symlink():
            raise RecoveryError("The previous installed package is unavailable")
        directory = self.root / token
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        archive = directory / "previous.zip"
        manifest_path = source / "update-manifest.json"
        if manifest_path.is_file():
            manifest = _read_json(manifest_path)
            if manifest.get("version") != version:
                raise RecoveryError("Previous package version does not match its manifest")
            files = [(Path("update-manifest.json"), manifest_path)]
            for component in manifest.get("components", []):
                if component["id"] not in ({"plugin"} if PRODUCT == "Decky Vocal Assistant" else {"plugin", "faceplate-service", "pixel-studio"}):
                    raise RecoveryError("Previous package contains an unsupported component")
                prefix = Path(".") if component["id"] == "plugin" else Path("components") / component["id"]
                for record in component["files"]:
                    relative = prefix / record["path"]
                    path = source / relative
                    if (relative.is_absolute() or ".." in relative.parts or path.is_symlink()
                            or not path.is_file() or not path.resolve().is_relative_to(source.resolve())
                            or _digest(path) != record["sha256"]):
                        raise RecoveryError("Previous package failed file verification")
                    files.append((relative, path))
        else:
            files = [(p.relative_to(source), p) for p in source.rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"]
        temporary = directory / "previous.zip.tmp"
        check = directory / "verification"
        try:
            size = sum(path.stat().st_size for _, path in files)
            if len(files) > MAX_ARCHIVE_ENTRIES or size > MAX_UNCOMPRESSED_BYTES:
                raise RecoveryError("Previous package exceeds its storage limit")
            # New ZIP plus verification extraction coexist with the installed
            # and rollback directories (those are renamed, not copied).
            require_space(directory, min(MAX_ARCHIVE_BYTES, size + 1024 * 1024) + size)
            with ZipFile(temporary, "w", ZIP_DEFLATED) as output:
                for relative, path in files:
                    if path.is_symlink() or not path.resolve().is_relative_to(source.resolve()):
                        raise RecoveryError("Previous package contains a symbolic link")
                    output.write(path, Path(PRODUCT) / relative)
            from .updates import validate_and_stage_archive
            validate_and_stage_archive(temporary, check, version)
            shutil.rmtree(check)
            os.replace(temporary, archive)
            self.snapshot(token)
            metadata = {"schema": 1, "token": token, "version": version,
                        "sha256": _digest(archive)}
            pointer = self.root / "current.json"
            temp_pointer = self.root / "current.json.tmp"
            temp_pointer.write_text(json.dumps(metadata))
            temp_pointer.chmod(0o600)
            os.replace(temp_pointer, pointer)
        finally:
            temporary.unlink(missing_ok=True)
            if check.exists():
                shutil.rmtree(check)

    def _token(self, token):
        if not isinstance(token, str) or not TOKEN.fullmatch(token):
            raise RecoveryError("Invalid recovery identity")
        _no_symlink_ancestors(self.root / token)

    def _metadata(self):
        pointer = self.root / "current.json"
        _no_symlink_ancestors(pointer)
        value = _read_json(pointer)
        self._token(value.get("token"))
        if (value.get("schema") != 1 or not isinstance(value.get("version"), str)
                or not isinstance(value.get("sha256"), str) or len(value["sha256"]) != 64):
            raise RecoveryError("Invalid recovery metadata")
        return value

    def current(self):
        try:
            value = self._metadata()
            token = value.get("token", "")
            if not TOKEN.fullmatch(token):
                raise RecoveryError("Invalid recovery identity")
            directory = self.root / token
            archive = directory / "previous.zip"
            if (archive.is_symlink() or not archive.is_file()
                    or archive.stat().st_size > MAX_ARCHIVE_BYTES
                    or _digest(archive) != value["sha256"]):
                raise RecoveryError("Recovery archive failed its SHA256 check")
            verify_snapshot(directory / "snapshot")
            return value, archive, directory / "snapshot"
        except (OSError, ValueError, KeyError) as error:
            raise RecoveryError("No verified previous-version backup is available") from error

    def describe(self):
        """Lightweight status; full hashes are checked when recovery is prepared."""
        value = self._metadata()
        if not TOKEN.fullmatch(value.get("token", "")):
            raise RecoveryError("Invalid recovery identity")
        if not (self.root / value["token"] / "previous.zip").is_file():
            raise RecoveryError("Recovery archive is unavailable")
        return value
