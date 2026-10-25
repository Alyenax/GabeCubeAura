"""Independent transactional swap helper for GabeCubeAura updates.

This file uses only the Python standard library because it runs after Decky
Loader has stopped. It is copied to the persistent plugin runtime directory
before launch.
"""

from __future__ import annotations

import json
import fcntl
import hashlib
import ctypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time


TOKEN = re.compile(r"^[0-9a-f]{32}$")
AT_FDCWD = -100
RENAME_EXCHANGE = 2
MAX_STATE_BYTES = 4 * 1024 * 1024 * 1024
MAX_STATE_FILES = 32768
MAX_HELPER_METADATA_BYTES = 16 * 1024 * 1024
STATE_CHUNK_BYTES = 1024 * 1024


class TransactionError(RuntimeError):
    pass


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


def _read_json(path: Path):
    if path.stat().st_size > MAX_HELPER_METADATA_BYTES:
        raise TransactionError("transaction file is too large")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TransactionError("transaction file is invalid")
    return value


def _within(path: Path, parent: Path):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _state_files(settings_path, user_root):
    _no_symlink_ancestors(Path(settings_path))
    _no_symlink_ancestors(Path(user_root))
    yield "settings/config.json", Path(settings_path)
    user_root = Path(user_root)
    for relative in ("faceplate/preferences.json", "steamgriddb/preferences.json"):
        _no_symlink_ancestors(user_root / relative)
        yield "user/" + relative, user_root / relative
    artwork = user_root / "steamgriddb/artwork"
    _no_symlink_ancestors(artwork)
    if artwork.exists():
        for path in sorted(artwork.rglob("*")):
            if path.is_symlink():
                raise TransactionError("Artwork backup contains a symbolic link")
            if path.is_file():
                yield "user/" + path.relative_to(user_root).as_posix(), path


def _no_symlink_ancestors(path):
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise TransactionError("Recovery path contains a symbolic link")


def _state_relative(relative):
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise TransactionError("Recovery state path is invalid")
    allowed = (relative == "settings/config.json" or relative in {
        "user/faceplate/preferences.json", "user/steamgriddb/preferences.json",
    } or relative.startswith("user/steamgriddb/artwork/"))
    if not allowed:
        raise TransactionError("Recovery state includes an unsupported file")
    return path


def _stream_state_file(source, target=None, limit=MAX_STATE_BYTES):
    """Copy/hash bounded chunks, never load a large artwork into RAM."""
    digest = hashlib.sha256()
    size = 0
    output = target.open("wb") if target is not None else None
    try:
        with source.open("rb") as incoming:
            while True:
                block = incoming.read(STATE_CHUNK_BYTES)
                if not block:
                    break
                size += len(block)
                if size > limit:
                    raise TransactionError("Recovery artwork backup exceeds 1 GB")
                digest.update(block)
                if output is not None:
                    output.write(block)
    finally:
        if output is not None:
            output.close()
    return size, digest.hexdigest()


def snapshot_user_state(settings_path, user_root, destination):
    destination = Path(destination)
    _no_symlink_ancestors(destination)
    destination.mkdir(parents=True, mode=0o700)
    records, total = [], 0
    try:
        for relative, source in _state_files(settings_path, user_root):
            if source.is_symlink():
                raise TransactionError("User state contains a symbolic link")
            if not source.exists():
                continue
            if source.stat().st_size + total > MAX_STATE_BYTES or len(records) >= MAX_STATE_FILES:
                raise TransactionError("Recovery artwork backup exceeds its storage limit (4 GiB / 32768 files)")
            if shutil.disk_usage(destination).free < source.stat().st_size + 256 * 1024 * 1024:
                raise TransactionError("Insufficient free space for the recovery snapshot")
            target = destination / _state_relative(relative)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            size, digest = _stream_state_file(source, target, MAX_STATE_BYTES - total)
            total += size
            target.chmod(0o600)
            records.append({"path": relative, "size": size, "sha256": digest})
        _atomic_json(destination / "manifest.json", {"schema": 1, "files": records})
    except Exception:
        shutil.rmtree(destination)
        raise


def verify_snapshot(directory):
    directory = Path(directory)
    _no_symlink_ancestors(directory)
    if directory.is_symlink():
        raise TransactionError("Recovery snapshot is a symbolic link")
    _no_symlink_ancestors(directory / "manifest.json")
    manifest = _read_json(directory / "manifest.json")
    if manifest.get("schema") != 1 or not isinstance(manifest.get("files"), list):
        raise TransactionError("Recovery snapshot is invalid")
    if len(manifest["files"]) > MAX_STATE_FILES:
        raise TransactionError("Recovery snapshot has too many files")
    seen, total = set(), 0
    for record in manifest["files"]:
        relative = _state_relative(record["path"])
        source = directory / relative
        if relative in seen or source.is_symlink() or not source.resolve().is_relative_to(directory.resolve()):
            raise TransactionError("Recovery snapshot path is invalid")
        seen.add(relative)
        if source.stat().st_size + total > MAX_STATE_BYTES:
            raise TransactionError("Recovery state exceeds its storage limit")
        size, digest = _stream_state_file(source, limit=MAX_STATE_BYTES - total)
        total += size
        if (total > MAX_STATE_BYTES or size != record["size"]
                or digest != record["sha256"]):
            raise TransactionError("Recovery snapshot failed verification")
    return manifest


def restore_user_state(directory, settings_path, user_root):
    directory, user_root = Path(directory), Path(user_root)
    manifest = verify_snapshot(directory)  # Verify every file before writing any.
    wanted = {record["path"] for record in manifest["files"]}
    current = list(_state_files(settings_path, user_root))
    destinations = []
    for record in manifest["files"]:
        relative = record["path"]
        target = Path(settings_path) if relative == "settings/config.json" else user_root / relative[5:]
        _no_symlink_ancestors(target)
        destinations.append((relative, target))
    # Preflight every destination before deleting selections or replacing files.
    for relative, target in current:
        # Keep newly prepared artwork; remove only selections absent at backup.
        if relative not in wanted and (relative == "settings/config.json"
                or relative.endswith("/preferences.json") or relative.endswith("/active.json")
                or relative.endswith("/home.json")):
            if target.is_symlink():
                raise TransactionError("Recovery destination is a symbolic link")
            target.unlink(missing_ok=True)
    for relative, target in destinations:
        if target.is_symlink() or (relative.startswith("user/")
                and not target.resolve().is_relative_to(user_root.resolve())):
            raise TransactionError("Recovery destination escapes user state")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".recovery-tmp")
        _stream_state_file(directory / relative, temporary)
        temporary.chmod(0o600)
        os.replace(temporary, target)


def _validate_transaction(raw: dict):
    schema = raw.get("schema")
    if schema not in {1, 2} or not TOKEN.fullmatch(str(raw.get("token", ""))):
        raise TransactionError("transaction identity is invalid")
    token = raw["token"]
    product = raw.get("product", "GabeCubeAura")
    products = {"GabeCubeAura": "gabecubeaura", "Decky Vocal Assistant": "decky-vocal-assistant"}
    if product not in products: raise TransactionError("unknown plugin product")
    slug = products[product]
    runtime = Path(raw["runtime_root"]).resolve()
    active = Path(raw["active_dir"]).resolve()
    staged = Path(raw["staged_dir"]).resolve()
    state = Path(raw["state_path"]).resolve()
    health = Path(raw["health_path"]).resolve()
    if active.name != product or active.is_symlink():
        raise TransactionError("active plugin path is invalid")
    if not _within(staged, runtime / "staged") or staged.name != product or staged.is_symlink():
        raise TransactionError("staged plugin path is invalid")
    if not _within(state, runtime) or not _within(health, runtime):
        raise TransactionError("runtime paths are invalid")
    if staged.parent.name != token or health.name != f"{token}.json":
        raise TransactionError("transaction paths do not match the token")
    if not active.is_dir():
        raise TransactionError("active plugin directory is missing")
    for directory in (active, staged) if staged.exists() else (active,):
        if not directory.is_dir() or directory.is_symlink():
            raise TransactionError("required plugin directory is invalid")
        for required in ("main.py", "plugin.json", "package.json", "dist/index.js"):
            if not (directory / required).is_file():
                raise TransactionError("plugin directory is incomplete")
    service = str(raw.get("service", ""))
    if service != "plugin_loader.service":
        raise TransactionError("service name is invalid")
    timeout = int(raw.get("health_timeout", 45))
    if not 15 <= timeout <= 120:
        raise TransactionError("health timeout is invalid")
    result = {
        **raw,
        "product": product,
        "runtime": runtime,
        "active": active,
        "staged": staged,
        "state": state,
        "health": health,
        "service": service,
        "health_timeout": timeout,
    }
    result["components"] = []
    recovery = raw.get("restore_state")
    if recovery is not None:
        if not isinstance(recovery, dict):
            raise TransactionError("Recovery transaction is invalid")
        config = Path(recovery["settings_path"])
        user = Path(recovery["user_root"])
        if (config.name != "config.json" or config.parent.name != product
                or user.name != slug or user.parent.name != "share"
                or not config.is_absolute() or not user.is_absolute()
                or config.is_symlink() or user.is_symlink()):
            raise TransactionError("Recovery user paths are invalid")
        for field in ("snapshot", "failure_snapshot"):
            directory = Path(recovery[field])
            if directory.is_symlink() or not directory.resolve().is_relative_to(runtime / "recovery"):
                raise TransactionError("Recovery snapshot escapes the update runtime")
            verify_snapshot(directory)
    if schema == 2:
        companion_root = Path(raw.get("companion_root", "")).resolve()
        if (companion_root.name != "components"
                or companion_root.parent.name != slug
                or companion_root.is_symlink()):
            raise TransactionError("companion component path is invalid")
        raw_components = raw.get("components")
        if not isinstance(raw_components, list) or "plugin" not in raw_components:
            raise TransactionError("transaction component list is invalid")
        allowed = {"plugin"} if product == "Decky Vocal Assistant" else {"plugin", "faceplate-service", "pixel-studio"}
        if len(raw_components) != len(set(raw_components)) or not set(raw_components) <= allowed:
            raise TransactionError("transaction component list is invalid")
        for component in raw_components:
            if component == "plugin":
                continue
            source = staged / "components" / component
            if not source.is_dir() or source.is_symlink():
                raise TransactionError(f"staged {component} component is missing")
        result["companion_root"] = companion_root
        result["components"] = [item for item in raw_components if item != "plugin"]
    return result


def _plugin_version(directory: Path):
    try:
        package = _read_json(directory / "package.json")
        return str(package.get("version", ""))
    except (OSError, ValueError, TypeError, TransactionError):
        return ""


def _component_version(directory: Path):
    try:
        value = _read_json(directory / "component.json")
        return str(value.get("version", ""))
    except (OSError, ValueError, TypeError, TransactionError):
        return ""


def _exchange_directories(first: Path, second: Path):
    """Atomically exchange two Linux directory entries on one filesystem."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = libc.renameat2
    except (AttributeError, OSError) as error:
        raise TransactionError("atomic directory exchange is unavailable") from error
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        AT_FDCWD, os.fsencode(first), AT_FDCWD, os.fsencode(second), RENAME_EXCHANGE,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise TransactionError(f"atomic directory exchange failed with errno {error_number}")


def _merge_state(path: Path, **changes):
    try:
        state = _read_json(path)
    except (OSError, ValueError, TypeError, TransactionError):
        state = {}
    state.update(changes)
    _atomic_json(path, state)


def _install_companions(tx: dict, rollback_parent: Path):
    """Atomically replace each declared companion and keep per-component rollback."""
    installed = []
    tx["_companions_touched"] = []
    companion_root = tx.get("companion_root")
    if not companion_root:
        return installed
    companion_root.mkdir(parents=True, mode=0o755, exist_ok=True)
    backup_root = rollback_parent / "components"
    temporary_root = tx["runtime"] / "component-staged" / tx["token"]
    if temporary_root.exists():
        shutil.rmtree(temporary_root)
    temporary_root.mkdir(parents=True, mode=0o700)
    for component in tx["components"]:
        source = tx["staged"] / "components" / component
        size = sum(p.stat().st_size for p in source.rglob("*") if p.is_file())
        if shutil.disk_usage(temporary_root).free < size + 256 * 1024 * 1024:
            raise TransactionError("Insufficient free space for component staging")
        prepared = temporary_root / component
        shutil.copytree(source, prepared, symlinks=False)
        active = companion_root / component
        backup = backup_root / component
        if _component_version(active) == tx["to_version"]:
            if backup.is_dir(): tx["_companions_touched"].append(component)
            installed.append((component, backup.is_dir()))
            shutil.rmtree(prepared)
            continue
        had_previous = active.is_dir() and not active.is_symlink()
        if active.exists() and not had_previous:
            raise TransactionError(f"active {component} component path is unsafe")
        if had_previous:
            backup.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            if backup.exists():
                shutil.rmtree(backup)
            os.replace(active, backup)
        try:
            os.replace(prepared, active)
        except Exception:
            if had_previous and backup.exists() and not active.exists():
                os.replace(backup, active)
            raise
        installed.append((component, had_previous))
        tx["_companions_touched"].append(component)
    shutil.rmtree(temporary_root, ignore_errors=True)
    if "faceplate-service" in tx["components"]:
        applications = companion_root.parent.parent / "applications"
        desktop = applications / "gabecubeaura-pixel-studio.desktop"
        desktop_backup = rollback_parent / "desktop" / desktop.name
        if desktop.is_file() and not desktop_backup.exists():
            desktop_backup.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            shutil.copy2(desktop, desktop_backup)
        # Lab 21 retires the standalone web editor. Keep a rollback copy for a
        # failed transaction, but a successful update must remove its launcher.
        tx['_desktop_touched'] = True
        desktop.unlink(missing_ok=True)
    return installed


def _rollback_companions(tx: dict, rollback_parent: Path):
    companion_root = tx.get("companion_root")
    if not companion_root:
        return
    backup_root = rollback_parent / "components"
    quarantine_root = tx["runtime"] / "failed" / tx["token"] / "components"
    for component in reversed(tx["components"]):
        if "_companions_touched" in tx and component not in tx["_companions_touched"]:
            continue
        active = companion_root / component
        backup = backup_root / component
        if active.exists():
            quarantine_root.mkdir(parents=True, mode=0o700, exist_ok=True)
            quarantine = quarantine_root / component
            if quarantine.exists():
                shutil.rmtree(quarantine)
            os.replace(active, quarantine)
        if backup.exists():
            companion_root.mkdir(parents=True, mode=0o755, exist_ok=True)
            os.replace(backup, active)
    if "faceplate-service" in tx["components"]:
        desktop = companion_root.parent.parent / "applications/gabecubeaura-pixel-studio.desktop"
        desktop_backup = rollback_parent / "desktop" / desktop.name
        if not tx.get('_desktop_touched') and not desktop_backup.is_file():
            return  # A prior component failed before this launcher was touched.
        desktop.unlink(missing_ok=True)
        if desktop_backup.is_file():
            desktop.parent.mkdir(parents=True, mode=0o755, exist_ok=True)
            os.replace(desktop_backup, desktop)


def _companions_target_active(tx: dict):
    """Return true only when every declared companion is already the target build.

    This also makes an interrupted transaction resumable without treating an
    early Decky stop failure as if companion installation had started.
    """
    companion_root = tx.get("companion_root")
    return bool(
        companion_root
        and tx["components"]
        and all(
            _component_version(companion_root / component) == tx["to_version"]
            for component in tx["components"]
        )
    )


def _set_component_permissions(tx: dict):
    companion_root = tx.get("companion_root")
    if not companion_root:
        return
    executable_names = {"server.py", "launch-pixel-studio.sh"}
    for component in tx["components"]:
        root = companion_root / component
        for directory, subdirectories, files in os.walk(root):
            os.chmod(directory, 0o755)
            for name in subdirectories:
                os.chmod(Path(directory) / name, 0o755)
            for name in files:
                mode = 0o755 if name in executable_names else 0o644
                os.chmod(Path(directory) / name, mode)


class SystemdService:
    def __init__(self, name: str):
        self.name = name

    def _run(self, action: str, *, check=True):
        return subprocess.run(
            ["systemctl", action, self.name],
            check=check, capture_output=True, text=True, timeout=25,
        )

    def stop(self):
        self._run("stop")

    def start(self):
        self._run("start")

    def active(self):
        result = self._run("is-active", check=False)
        return result.returncode == 0 and result.stdout.strip() == "active"

    def wait_inactive(self, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.active():
                return True
            time.sleep(0.25)
        return False


def _wait_for_health(path: Path, token: str, version: str, timeout: int):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            health = _read_json(path)
            if health.get("token") == token and health.get("version") == version:
                return True
        except (OSError, ValueError, TypeError, TransactionError):
            pass
        time.sleep(0.5)
    return False


def _run_locked_transaction(raw: dict, service=None, health_waiter=_wait_for_health,
                    exchanger=_exchange_directories):
    tx = _validate_transaction(raw)
    if tx['product'] == 'GabeCubeAura' and (tx['active'].parent / 'Decky Vocal Assistant').exists() and tx['staged'].exists():
        try:
            generic=tx['staged']/'integration-contract.json'
            receipt=_read_json(generic if generic.exists() else tx['staged']/'vocal-contract.json')
            if receipt.get('protocol') != 1 or (receipt.get('capture_owner') is not False if generic.exists() else receipt.get('legacy_voice') is not False): raise ValueError()
            for relative in ('main.py','py_modules/signalbar/backend/engine.py'):
                if receipt.get('files',{}).get(relative) != hashlib.sha256((tx['staged']/relative).read_bytes()).hexdigest(): raise ValueError()
        except (OSError, ValueError, TypeError):
            raise TransactionError('Remove DVA before restoring embedded GCA voice')
    service = service or SystemdService(tx["service"])
    token = tx["token"]
    rollback_parent = tx["runtime"] / "rollback" / token
    rollback = rollback_parent / tx["product"]
    quarantine = tx["runtime"] / "failed" / token / tx["product"]
    companions_installed = False
    state_restore_started = False
    existing_state = {}
    try:
        existing_state = _read_json(tx["state"])
    except (OSError, ValueError, TypeError, TransactionError):
        pass
    if (existing_state.get("completed_token") == token and existing_state.get("last_result") == "updated"
            and existing_state.get("installed_version") == tx["to_version"]):
        return {"result": "updated", "version": tx["to_version"]}
    if (existing_state.get("completed_token") == token and existing_state.get("last_result") == "rolled_back"
            and existing_state.get("installed_version") == tx["from_version"]):
        return {"result": "rolled_back", "version": tx["from_version"]}
    tx["health"].unlink(missing_ok=True)
    _merge_state(tx["state"], phase="installing", pending_token=token,
                 pending_version=tx["to_version"], error="", error_category="")
    try:
        service.stop()
        if not service.wait_inactive(20):
            raise TransactionError("Decky Loader did not stop")
        active_version = _plugin_version(tx["active"])
        staged_version = _plugin_version(tx["staged"]) if tx["staged"].exists() else ""
        rollback_version = _plugin_version(rollback) if rollback.exists() else ""
        if active_version == tx["from_version"] and staged_version == tx["to_version"]:
            _merge_state(tx["state"], phase="swap_started")
            _install_companions(tx, rollback_parent)
            companions_installed = bool(tx["components"])
            exchanger(tx["active"], tx["staged"])
            active_version, staged_version = staged_version, active_version
            _merge_state(tx["state"], phase="swapped")
        if active_version != tx["to_version"]:
            raise TransactionError("active directory does not contain the target version")
        if staged_version == tx["from_version"] and not rollback.exists():
            rollback_parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            os.replace(tx["staged"], rollback)
            rollback_version = tx["from_version"]
        if rollback_version != tx["from_version"]:
            raise TransactionError("rollback directory does not contain the previous version")
        for directory, subdirectories, files in os.walk(tx["active"]):
            os.chmod(directory, 0o755)
            for name in subdirectories:
                os.chmod(Path(directory) / name, 0o755)
            for name in files:
                os.chmod(Path(directory) / name, 0o644)
        _set_component_permissions(tx)
        if tx.get("restore_state"):
            recovery = tx["restore_state"]
            state_restore_started = True
            restore_user_state(recovery["snapshot"], recovery["settings_path"], recovery["user_root"])
        _merge_state(tx["state"], phase="restart_pending")
        service.start()
        if not health_waiter(tx["health"], token, tx["to_version"], tx["health_timeout"]):
            raise TransactionError("new plugin did not acknowledge a healthy startup")
        _merge_state(
            tx["state"], phase="updated", installed_version=tx["to_version"],
            pending_token="", pending_version="", confirmation_token="",
            available_version="", release_notes="", release_url="",
            prepared_digest="",
            rollback_version=tx["from_version"], last_result="updated",
            completed_token=token,
            error="", error_category="",
        )
        return {"result": "updated", "version": tx["to_version"]}
    except Exception as error:
        rollback_error = ""
        try:
            if service.active():
                service.stop()
                if not service.wait_inactive(20):
                    raise TransactionError("Decky Loader did not stop for recovery")
            previous = rollback if _plugin_version(rollback) == tx["from_version"] else tx["staged"]
            if (_plugin_version(tx["active"]) == tx["to_version"]
                    and _plugin_version(previous) == tx["from_version"]):
                exchanger(tx["active"], previous)
                quarantine.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                if quarantine.exists():
                    shutil.rmtree(quarantine)
                os.replace(previous, quarantine)
            if companions_installed or tx.get("_companions_touched") or _companions_target_active(tx):
                _rollback_companions(tx, rollback_parent)
            if state_restore_started:
                recovery = tx["restore_state"]
                restore_user_state(recovery["failure_snapshot"], recovery["settings_path"], recovery["user_root"])
            service.start()
        except Exception as caught:
            rollback_error = type(caught).__name__
        message = str(error)[:140] or type(error).__name__
        if rollback_error:
            message = f"{message}; rollback restart failed ({rollback_error})"[:180]
        restored = not rollback_error and _plugin_version(tx["active"]) == tx["from_version"]
        _merge_state(
            tx["state"], phase="rolled_back" if restored else "error",
            installed_version=tx["from_version"] if restored else _plugin_version(tx["active"]),
            pending_token="", pending_version="", confirmation_token="",
            rollback_version=tx["from_version"], last_result="rolled_back" if restored else "recovery_failed",
            completed_token=token,
            error_category="install", error=message,
        )
        return {"result": "rolled_back" if restored else "recovery_failed",
                "version": tx["from_version"] if restored else _plugin_version(tx["active"]), "error": message}


def run_transaction(raw: dict, service=None, health_waiter=_wait_for_health,
                    exchanger=_exchange_directories, install_lock=None):
    # The helper survives Decky stopping. Hold the same cross-product lock
    # until health ACK or rollback completes, never only during the rename.
    tx = _validate_transaction(raw)
    path = Path(install_lock) if install_lock else (tx['runtime'].parent / '.decky-install.lock'
            if service is not None else Path('/run/decky/plugin-install.lock'))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a+') as lock:
        deadline = time.monotonic() + 90
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB); break
            except BlockingIOError:
                if time.monotonic() >= deadline: raise TransactionError('Another Decky installation is still running')
                time.sleep(.2)
        return _run_locked_transaction(raw, service, health_waiter, exchanger)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        return 2
    path = Path(argv[0]).resolve()
    try:
        raw = _read_json(path)
        result = run_transaction(raw)
        result_path = Path(raw["runtime_root"]).resolve() / "transactions" / f"{raw['token']}.result.json"
        _atomic_json(result_path, result)
        return 0 if result["result"] == "updated" else 1
    except Exception as error:
        try:
            failure = path.with_suffix(".fatal.json")
            _atomic_json(failure, {"result": "fatal", "error": str(error)[:180]})
        except Exception:
            pass
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
