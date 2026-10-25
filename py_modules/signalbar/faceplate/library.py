# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Read-only discovery of installed Steam applications.

Pixel Studio uses this small parser instead of asking Steam or Decky to build a
library view.  Only local ``appmanifest_*.acf`` files are inspected.
"""

from __future__ import annotations

import os
from pathlib import Path
import re


_PAIR = re.compile(r'^\s*"([^"]+)"\s+"([^"]*)"\s*$')


def _steam_home(user_home=None):
    home = Path(user_home or os.environ.get("DECKY_USER_HOME") or Path.home())
    override = os.environ.get("SIGNALBAR_STEAM_ROOT")
    candidates = [
        Path(override) if override else None,
        home / ".steam/steam",
        home / ".steam/root",
        home / ".local/share/Steam",
    ]
    # Decky runs as root on SteamOS. If its user-home environment is absent,
    # Path.home() points at root, not at the user owning the Steam session.
    # Only fall back for implicit discovery; never override a caller's home.
    if user_home is None and hasattr(os,"geteuid") and os.geteuid() == 0:
        try:
            import pwd
            homes = [Path(pwd.getpwuid(int(uid)).pw_dir) for uid in os.listdir('/run/user') if uid.isdigit() and int(uid)>0]
        except (OSError,KeyError,ValueError): homes = []
        for candidate in [*homes, Path('/home/deck')]:
            candidates.extend((candidate/'.steam/steam',candidate/'.steam/root',candidate/'.local/share/Steam'))
    return next((path for path in candidates if path and path.is_dir()), None)


def _pairs(path):
    try:
        if path.stat().st_size > 4 * 1024 * 1024:
            return []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [match.groups() for line in lines if (match := _PAIR.match(line))]


def steam_library_roots(user_home=None):
    root = _steam_home(user_home)
    if root is None:
        return []
    roots = [root]
    config = root / "steamapps/libraryfolders.vdf"
    for key, value in _pairs(config):
        if key.lower() != "path":
            continue
        candidate = Path(value.replace("\\\\", "\\"))
        if candidate.is_dir() and candidate not in roots:
            roots.append(candidate)
    return roots


def installed_games(user_home=None, limit=2000):
    """Return unique installed Steam games sorted by display name."""
    games = {}
    for root in steam_library_roots(user_home):
        for manifest in (root / "steamapps").glob("appmanifest_*.acf"):
            values = {key.lower(): value for key, value in _pairs(manifest)}
            try:
                appid = int(values.get("appid", "0"))
            except ValueError:
                continue
            name = values.get("name", "").strip()
            if appid > 0 and name:
                games[appid] = {"appid": appid, "name": name[:160]}
            if len(games) >= max(1, int(limit)):
                break
    return sorted(games.values(), key=lambda item: (item["name"].casefold(), item["appid"]))


def last_played_game(games, user_home=None):
    """Use Steam's LastPlayed, not download/update time or alphabetical order."""
    installed={game['appid']:game for game in games}
    newest=(0,0)
    for root in steam_library_roots(user_home):
        for manifest in (root/'steamapps').glob('appmanifest_*.acf'):
            values={key.lower():value for key,value in _pairs(manifest)}
            try: appid=int(values.get('appid','0')); played=int(values.get('lastplayed','0'))
            except ValueError: continue
            if appid in installed and played>newest[0]: newest=(played,appid)
    game=installed.get(newest[1])
    return {**game,'last_played':newest[0]} if game else None
