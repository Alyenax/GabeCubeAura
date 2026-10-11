"""The running game's session, remembered across a Decky restart.

Session length counts awake time on the monotonic clock, which a new process
starts afresh. So the bridge records the game, the wall time its session
began and the awake seconds so far, at most once a minute while it runs. A
bridge that starts with the same game running carries on from the record if
it is recent; any other game, an old record or a damaged file starts from 0.

The file holds an appid and three numbers, lives next to mqtt.json in the
owner-only runtime directory and is written atomically.
"""

from __future__ import annotations

import json
import math
import os

FILENAME = "session.json"
# A Decky restart takes seconds. A record older than this belongs to a game
# that has since been quit or relaunched.
RESUME_WITHIN_S = 600.0


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class SessionRecord:
    def __init__(self, directory=None):
        self.path = os.path.join(directory, FILENAME) if directory else None

    def resume(self, appid, wall):
        """Return (wall time it started, awake seconds) for this appid's recent session, else None."""
        if not self.path:
            return None
        try:
            with open(self.path, encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, ValueError, RecursionError):
            return None
        if not isinstance(raw, dict) or raw.get("appid") != appid or isinstance(appid, bool):
            return None
        started, awake, saved = raw.get("started_at"), raw.get("awake_s"), raw.get("saved_at")
        if not (_number(started) and _number(awake) and _number(saved)):
            return None
        if not (0 <= wall - saved <= RESUME_WITHIN_S and started <= saved and 0 <= awake <= saved - started + 1.0):
            return None
        return float(started), float(awake)

    def save(self, appid=0, started=None, awake=0.0, saved=None):
        """Record a session; with no appid, record that none is running."""
        if not self.path:
            return
        record = {"version": 1, "appid": appid}
        if appid:
            record.update(started_at=started, awake_s=round(awake, 1), saved_at=saved)
        try:
            os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
            temporary = self.path + ".tmp"
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(record, handle, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError:
            pass  # the session then starts from 0 after a restart; nothing else depends on it
