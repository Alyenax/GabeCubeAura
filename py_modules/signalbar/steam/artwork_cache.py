"""Read-only discovery of Steam's Library cache and custom grid artwork."""

from __future__ import annotations

import base64
import glob
import hashlib
import mimetypes
import os
import re
from pathlib import Path

IMAGE_EXTENSIONS = ("jpg", "jpeg", "png", "webp")
MAX_BYTES = 12 * 1024 * 1024
ARTWORK_SOURCES = {
    "hero": {
        "label": "Library Hero",
        "stems": ("library_hero", "library_hero_2x", "library_hero@2x"),
    },
    "header": {
        "label": "Library Header",
        "stems": ("library_header", "library_header_2x", "header"),
    },
    "capsule": {
        "label": "Library Capsule",
        "stems": ("library_capsule", "library_600x900", "library_600x900_2x"),
    },
}
CUSTOM_GRID_SUFFIXES = {
    "hero": "_hero",
    "header": "",
    "capsule": "p",
}


def steam_roots():
    candidates = []
    for raw in (
        os.environ.get("SIGNALBAR_STEAM_ROOT"),
        os.environ.get("STEAM_COMPAT_CLIENT_INSTALL_PATH"),
        os.environ.get("STEAM_DIR"),
    ):
        if raw:
            candidates.append(Path(raw).expanduser())
    decky_home = os.environ.get("DECKY_USER_HOME")
    if decky_home:
        home = Path(decky_home)
        candidates.extend((home / ".local/share/Steam", home / ".steam/steam"))
    home = Path(os.path.expanduser("~"))
    candidates.extend((home / ".local/share/Steam", home / ".steam/steam"))
    for pattern in ("/home/*/.local/share/Steam", "/home/*/.steam/steam"):
        candidates.extend(Path(value) for value in glob.glob(pattern))

    found, seen = [], set()
    for candidate in candidates:
        key = str(candidate.resolve())
        if key not in seen and (
            (candidate / "appcache/librarycache").is_dir()
            or (candidate / "userdata").is_dir()
        ):
            seen.add(key)
            found.append(candidate)
    return found


def artwork_candidates(cache: Path, appid: int, source="hero"):
    aid = str(int(appid))
    specification = ARTWORK_SOURCES.get(source, ARTWORK_SOURCES["hero"])
    candidates = []
    for extension in IMAGE_EXTENSIONS:
        for name in specification["stems"]:
            candidates.append(cache / aid / f"{name}.{extension}")
            candidates.extend(Path(value) for value in glob.glob(str(cache / aid / "*" / f"{name}.{extension}")))
            candidates.append(cache / f"{aid}_{name}.{extension}")
    return candidates


def _active_account_id(root: Path):
    """Steam's most recent login uses the low 32 bits as its userdata ID."""
    try:
        content = (root / "config/loginusers.vdf").read_text(encoding="utf-8")
    except OSError:
        return None
    for match in re.finditer(r'"(\d{16,20})"\s*\{([^{}]*)\}', content):
        if re.search(r'"MostRecent"\s*"1"', match.group(2), re.IGNORECASE):
            return str(int(match.group(1)) & 0xFFFFFFFF)
    return None


def _grid_directories(root: Path):
    userdata = root / "userdata"
    active_id = _active_account_id(root)
    if active_id:
        active = userdata / active_id / "config/grid"
        # Never show another account's artwork merely because the active
        # account has not customized this game yet.
        return [active] if active.is_dir() else []
    try:
        accounts = sorted(
            (path for path in userdata.iterdir() if path.is_dir() and path.name.isdigit()),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
    except OSError:
        return []
    # Without loginusers.vdf, use only the most recently touched account.
    # Searching every account could apply somebody else's grid override.
    for account in accounts:
        grid = account / "config/grid"
        if grid.is_dir():
            return [grid]
    return []


def _valid_image(path: Path):
    try:
        return path.is_file() and 0 < path.stat().st_size <= MAX_BYTES
    except OSError:
        return False


def _custom_artwork(root: Path, appid: int, source: str):
    filename = f"{appid & 0xFFFFFFFF}{CUSTOM_GRID_SUFFIXES[source]}"
    for grid in _grid_directories(root):
        for extension in IMAGE_EXTENSIONS:
            candidate = grid / f"{filename}.{extension}"
            if _valid_image(candidate):
                return candidate
    return None


def _find_artwork_details(appid: int, source="hero"):
    try:
        appid = int(appid)
    except (TypeError, ValueError):
        return None, source, False
    if appid <= 0:
        return None, source, False
    source = source if source in ARTWORK_SOURCES else "hero"
    roots = steam_roots()
    for root in roots:
        custom = _custom_artwork(root, appid, source)
        if custom is not None:
            return custom, source, True
    for root in roots:
        for candidate in artwork_candidates(root / "appcache/librarycache", appid, source):
            if _valid_image(candidate):
                return candidate, source, False
    # Non-Steam shortcuts may have only a custom capsule or header. Prefer
    # another available local image over showing no Artwork at all.
    for fallback in ("hero", "header", "capsule"):
        if fallback == source:
            continue
        for root in roots:
            custom = _custom_artwork(root, appid, fallback)
            if custom is not None:
                return custom, fallback, True
    return None, source, False


def find_library_artwork(appid: int, source="hero"):
    return _find_artwork_details(appid, source)[0]


def get_library_artwork(appid: int, source="hero"):
    source = source if source in ARTWORK_SOURCES else "hero"
    path, actual_source, custom = _find_artwork_details(appid, source)
    if path is None:
        return {
            "found": False,
            "appid": int(appid or 0),
            "source": source,
            "source_label": ARTWORK_SOURCES[source]["label"],
        }
    try:
        raw = path.read_bytes()
        stat = path.stat()
    except OSError:
        return {
            "found": False,
            "appid": int(appid or 0),
            "source": source,
            "source_label": ARTWORK_SOURCES[source]["label"],
        }
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    if not mime.startswith("image/"):
        mime = "image/jpeg"
    fingerprint = hashlib.sha256(
        f"{stat.st_size}:{stat.st_mtime_ns}:".encode("ascii") + raw[:4096]
    ).hexdigest()[:20]
    return {
        "found": True,
        "appid": int(appid),
        "source": actual_source,
        "source_label": (
            f"Custom {ARTWORK_SOURCES[actual_source]['label']}"
            if custom else ARTWORK_SOURCES[actual_source]["label"]
        ),
        "mime": mime,
        "filename": path.name,
        "fingerprint": fingerprint,
        "data_uri": f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}",
    }


def find_library_hero(appid: int):
    return find_library_artwork(appid, "hero")


def get_library_hero(appid: int):
    return get_library_artwork(appid, "hero")


# The transparent title logo. Not in ARTWORK_SOURCES: it is drawn over other
# artwork (the faceplate does), never sampled as a backdrop, and a game with
# no logo must find nothing rather than fall back to another image.
LOGO_STEMS = ("logo", "logo_2x")


def find_library_logo(appid: int):
    try:
        appid = int(appid)
    except (TypeError, ValueError):
        return None
    if appid <= 0:
        return None
    roots = steam_roots()
    for root in roots:
        for grid in _grid_directories(root):
            for extension in IMAGE_EXTENSIONS:
                candidate = grid / f"{appid & 0xFFFFFFFF}_logo.{extension}"
                if _valid_image(candidate):
                    return candidate
    for root in roots:
        cache = root / "appcache/librarycache"
        for extension in IMAGE_EXTENSIONS:
            for name in LOGO_STEMS:
                for candidate in (
                    [cache / str(appid) / f"{name}.{extension}"]
                    + sorted(Path(value) for value in glob.glob(str(cache / str(appid) / "*" / f"{name}.{extension}")))
                    + [cache / f"{appid}_{name}.{extension}"]
                ):
                    if _valid_image(candidate):
                        return candidate
    return None
