"""The displays Home Assistant's light replaced, remembered across restarts.

Turning the light on selects the Home Assistant display for what is on
screen. The display it replaces is recorded here, per settings key, just
before that write. Turning the light off, or a tier change, puts it back
and clears the record; if the plugin stops first, main.py does that at the
next start, before the bridge runs.

The file holds display names only, but lives next to mqtt.json in the
owner-only runtime directory and is written atomically. Only the two display
keys with a plain display name are accepted, so a damaged or edited file can
never make GabeCubeAura write any other setting.
"""

from __future__ import annotations

import json
import os
import re
import threading

FILENAME = "routed.json"
KEYS = ("home_display", "game_display")
_NAME = re.compile(r"[a-z_]{1,32}")  # fullmatch only


def _valid(key, value) -> bool:
    return (key in KEYS and isinstance(value, str) and bool(_NAME.fullmatch(value))
            and value != "home_assistant")


class RoutedDisplays:
    def __init__(self, directory=None):
        self.path = os.path.join(directory, FILENAME) if directory else None
        self._lock = threading.Lock()
        self._displays = {}
        self.error = ""
        self._load()

    def _load(self):
        if not self.path:
            return
        try:
            with open(self.path, encoding="utf-8") as handle:
                raw = json.load(handle)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as error:
            self.error = f"displaced displays unreadable: {type(error).__name__}"
            return
        displays = raw.get("displays") if isinstance(raw, dict) else None
        if isinstance(displays, dict):
            self._displays = {key: value for key, value in displays.items() if _valid(key, value)}

    def displays(self) -> dict:
        with self._lock:
            return dict(self._displays)

    def remember(self, key, previous) -> bool:
        """Record the display the light is about to replace; True if it was recorded.

        The newest record wins. Routing only writes where another display is
        selected, so whatever it finds is current, and an older record for the
        key may predate a choice made on the Steam Machine since.
        """
        with self._lock:
            if not _valid(key, previous):
                return False
            if self._displays.get(key) != previous:
                self._displays[key] = previous
                self._save()
            return True

    def forget(self, key):
        with self._lock:
            if self._displays.pop(key, None) is not None:
                self._save()

    def _save(self):
        if not self.path:
            return
        try:
            os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
            temporary = self.path + ".tmp"
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump({"version": 1, "displays": self._displays}, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            self.error = ""
        except OSError as error:
            self.error = f"displaced displays not saved: {type(error).__name__}"
