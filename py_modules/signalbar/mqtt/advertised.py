"""The retained entity topics this plugin has put on the broker, remembered across restarts.

Setting entities exist only while a device is at "settings" or "drive", and
the light and alert buttons only at "drive". When a level drops, or the
plugin starts at Report only after a session that had one, the bridge clears
the topics recorded here and forgets them. With nothing recorded it
sends nothing. Topics are recorded before they are published, so a crash in
between still gets them cleared later.

The file holds topic names only, but lives next to mqtt.json in the
owner-only runtime directory and is written atomically. Only topics shaped
like the ones this bridge creates are accepted, so a damaged or edited file
can never make it delete someone else's retained messages.
"""

from __future__ import annotations

import json
import os
import re
import threading

FILENAME = "advertised.json"
MAX_TOPICS = 1024
_OURS = re.compile(
    r"[A-Za-z0-9_\-/]{1,200}/(switch|select|number)/gabecubeaura_[a-z0-9_]{1,80}_setting_[a-z0-9_]{1,80}/config"
    r"|[A-Za-z0-9_\-/]{1,200}/(light|button)/gabecubeaura_[a-z0-9_]{1,80}_drive_[a-z0-9_]{1,80}/config"
    r"|[A-Za-z0-9_\-/]{1,200}/(state/settings|state/drive|attributes/display_preset_note)"
)


def is_ours(topic) -> bool:
    return isinstance(topic, str) and len(topic) <= 512 and bool(_OURS.fullmatch(topic))


class AdvertisedTopics:
    def __init__(self, directory=None):
        self.path = os.path.join(directory, FILENAME) if directory else None
        self._lock = threading.Lock()
        self._topics = set()
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
            self.error = f"advertised topics unreadable: {type(error).__name__}"
            return
        topics = raw.get("topics") if isinstance(raw, dict) else None
        if isinstance(topics, list):
            self._topics = {topic for topic in topics[:MAX_TOPICS] if is_ours(topic)}

    def topics(self) -> frozenset:
        with self._lock:
            return frozenset(self._topics)

    def add(self, topics):
        with self._lock:
            new = {topic for topic in topics if is_ours(topic)} - self._topics
            if new:
                self._topics |= new
                self._save()

    def discard(self, topics):
        with self._lock:
            gone = set(topics) & self._topics
            if gone:
                self._topics -= gone
                self._save()

    def _save(self):
        if not self.path:
            return
        try:
            os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
            temporary = self.path + ".tmp"
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump({"version": 1, "topics": sorted(self._topics)}, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            self.error = ""
        except OSError as error:
            self.error = f"advertised topics not saved: {type(error).__name__}"
