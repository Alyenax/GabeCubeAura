"""Human-retrievable exports of GabeCubeAura's saved configuration."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path


EXPORT_FILENAME = "GabeCubeAura-configuration.json"
MAX_IMPORT_BYTES = 1024 * 1024


def configuration_export_path(settings_directory: str, user_home: str | None = None) -> Path:
    """Prefer the Steam user's Documents folder, with a safe settings fallback."""
    if user_home:
        home = Path(user_home).expanduser()
        if home.is_absolute():
            return home / "Documents" / EXPORT_FILENAME

    settings = Path(settings_directory).expanduser()
    if not settings.is_absolute():
        settings = Path.cwd() / settings
    for parent in (settings, *settings.parents):
        if parent.name == "homebrew" and parent.parent != parent:
            return parent.parent / "Documents" / EXPORT_FILENAME
    return settings / EXPORT_FILENAME


def build_configuration_export(settings, version: str, current_game=None, generated_at=None):
    """Build a stable, controller-ID-free document from persisted choices."""
    values = deepcopy(settings.all())
    display_profiles = values.pop("display_profiles", {})
    artwork_profiles = values.pop("artwork_profiles", {})
    launch_artwork_profiles = values.pop("launch_artwork_profiles", {})
    # A preset's restore snapshot is local undo state, not user configuration.
    # Export the currently effective recipe as an ordinary custom setup.
    values.pop("display_preset_restore", None)
    values["display_preset"] = "custom"

    game = None
    raw_game = current_game if isinstance(current_game, dict) else {}
    try:
        appid = int(raw_game.get("appid", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        appid = 0
    if appid > 0:
        game = {
            "appid": appid,
            "title": str(raw_game.get("title", "")),
            "display": settings.display_for(appid),
            "artwork": settings.artwork_for(appid),
            "launch_artwork": settings.launch_artwork_for(appid),
        }

    timestamp = generated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": 1,
        "gabecubeaura_version": version,
        "exported_at": timestamp,
        "configuration": {
            "global": values,
            "profiles": {
                "display_by_appid": display_profiles,
                "artwork_by_appid": artwork_profiles,
                "launch_artwork_by_appid": launch_artwork_profiles,
            },
            "current_game": game,
        },
    }


def read_configuration_import(path: str):
    """Read a user-selected export, never executable settings or runtime state."""
    target = Path(path).expanduser()
    if not target.is_absolute() or target.suffix.lower() != ".json":
        raise ValueError("Choose an absolute .json configuration file")
    try:
        size = target.stat().st_size
    except OSError as error:
        raise ValueError("Configuration file cannot be read") from error
    if not target.is_file() or not 0 < size <= MAX_IMPORT_BYTES:
        raise ValueError("Configuration must be a non-empty JSON file under 1 MB")
    try:
        with target.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Configuration is not readable JSON") from error
    if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int \
            or payload["schema_version"] != 1:
        raise ValueError("Unsupported GabeCubeAura configuration schema")
    configuration = payload.get("configuration")
    if not isinstance(configuration, dict):
        raise ValueError("Configuration section is missing")
    global_values = configuration.get("global")
    profiles = configuration.get("profiles")
    if not isinstance(global_values, dict) or not isinstance(profiles, dict):
        raise ValueError("Global settings or game profiles are missing")
    display = profiles.get("display_by_appid")
    artwork = profiles.get("artwork_by_appid")
    launch_artwork = profiles.get("launch_artwork_by_appid", {})
    if not isinstance(display, dict) or not isinstance(artwork, dict) or not isinstance(launch_artwork, dict):
        raise ValueError("Game profiles must be objects")
    if len(display) > 512 or len(artwork) > 512 or len(launch_artwork) > 512:
        raise ValueError("Too many game profiles in configuration")
    # current_game, version and export date are informational, not settings.
    return global_values, display, artwork, launch_artwork


def write_configuration_export(settings, path: Path, version: str, current_game=None):
    """Atomically write the export and return UI-ready metadata."""
    target = Path(path)
    parent_existed = target.parent.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    if not parent_existed and hasattr(os, "geteuid") and os.geteuid() == 0:
        owner = target.parent.parent.stat()
        os.chown(target.parent, owner.st_uid, owner.st_gid)
    payload = build_configuration_export(settings, version, current_game)
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            owner = target.parent.stat()
            os.chown(target, owner.st_uid, owner.st_gid)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return {"path": str(target), "exported_at": payload["exported_at"]}
