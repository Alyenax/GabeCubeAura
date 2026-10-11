"""The running game's session, remembered across a Decky restart.

Session length counts awake time on the monotonic clock, which a new process
starts afresh. So the bridge records the game, the wall time its session
began and the awake seconds so far, at most once a minute while it runs. A
bridge that starts with the same game running carries on from the record if
it is recent and from the same boot; any other game, an old record, another
boot or a damaged file starts from 0.

The file holds an appid, three numbers and the boot ID, lives next to
mqtt.json in the owner-only runtime directory and is written atomically.

published.json beside it keeps what a restart should carry on from what was
published: the content type each image entity was last announced with, so the
same game sends the same discovery, the settled light bar owner, so a restart
that ends where it began is no owner_changed event, and the boot it was
written in. The bridge holds the broker's values through a start only on the
same boot; after a reboot they are all stale.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import threading

FILENAME = "session.json"
PUBLISHED_FILENAME = "published.json"
# A Decky restart takes seconds. A record older than this belongs to a game
# that has since been quit or relaunched.
RESUME_WITHIN_S = 600.0
# A game cannot outlive a reboot, however quick. Absent off Linux, and then
# not checked.
BOOT_ID_PATH = "/proc/sys/kernel/random/boot_id"


def _boot_id():
    try:
        with open(BOOT_ID_PATH, encoding="ascii") as handle:
            return handle.read().strip() or None
    except (OSError, ValueError):
        return None


def _write(path, record, lock):
    """Write a small JSON record atomically; a failure leaves the old file."""
    with lock:
        temporary = None
        try:
            os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp",
                                             dir=os.path.dirname(path))
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(record, handle, sort_keys=True, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except (OSError, TypeError, ValueError):  # a value that is not JSON writes nothing
            if temporary:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class SessionRecord:
    def __init__(self, directory=None):
        self.path = os.path.join(directory, FILENAME) if directory else None
        # The worker and stop() on an executor thread can both save.
        self._lock = threading.Lock()

    def resume(self, wall):
        """Return (appid, wall time it started, awake seconds) of a recent session, else None."""
        if not self.path:
            return None
        try:
            with open(self.path, encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, ValueError, RecursionError):
            return None
        appid = raw.get("appid") if isinstance(raw, dict) else None
        if not isinstance(appid, int) or isinstance(appid, bool) or appid <= 0:
            return None
        if "boot_id" not in raw or raw["boot_id"] != _boot_id():
            return None
        started, awake, saved = raw.get("started_at"), raw.get("awake_s"), raw.get("saved_at")
        if not (_number(started) and _number(awake) and _number(saved)):
            return None
        if not (0 <= wall - saved <= RESUME_WITHIN_S and started <= saved and 0 <= awake <= saved - started + 1.0):
            return None
        return appid, float(started), float(awake)

    def save(self, appid=0, started=None, awake=0.0, saved=None):
        """Record a session; with no appid, record that none is running."""
        if not self.path:
            return
        record = {"version": 1, "appid": appid}
        if appid:
            record.update(started_at=started, awake_s=round(awake, 1), saved_at=saved, boot_id=_boot_id())
        # On failure the session starts from 0 after a restart; nothing else
        # depends on it.
        _write(self.path, record, self._lock)


class Published:
    """Image content types by kind and the settled light bar owner, as last published."""

    def __init__(self, directory=None, allowed_types=()):
        self.path = os.path.join(directory, PUBLISHED_FILENAME) if directory else None
        self._allowed = frozenset(allowed_types)
        self._lock = threading.Lock()
        self.art_types, self.owner, self.same_boot = {}, None, False
        self._load()

    def _load(self):
        if not self.path:
            return
        try:
            with open(self.path, encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, ValueError, RecursionError):
            return
        raw = raw if isinstance(raw, dict) else {}
        types = raw.get("art_types") if isinstance(raw.get("art_types"), dict) else {}
        self.art_types = {kind: value for kind, value in types.items()
                          if isinstance(kind, str) and value in self._allowed}
        owner = raw.get("owner")
        self.owner = owner[:64] if isinstance(owner, str) and owner else None
        self.same_boot = "boot_id" in raw and raw["boot_id"] == _boot_id()

    def save(self, art_types=None, owner=None):
        if art_types is not None:
            self.art_types = dict(art_types)
        if owner is not None:
            self.owner = owner
        if self.path:
            _write(self.path, {"version": 1, "art_types": self.art_types, "owner": self.owner,
                               "boot_id": _boot_id()}, self._lock)
