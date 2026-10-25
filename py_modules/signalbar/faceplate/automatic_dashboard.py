# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Bounded, offline single-frame backgrounds for automatic game Dashboards."""

from collections import OrderedDict
from pathlib import Path
import threading

from . import artwork
from .protocol import WIDTH, HEIGHT


class AutomaticDashboardBackgrounds:
    """Decode in the Faceplate worker, once per local source/layout revision.

    The existing decoder runs GStreamer in a bounded subprocess. This cache
    holds at most eight native RGB frames, never a source image or animation.
    It does not touch Studio selections or contact SteamGridDB.
    """

    def __init__(self):
        self.frames = OrderedDict()
        self.lock = threading.RLock()

    @staticmethod
    def _file_identity(path):
        if path is None:
            return None
        path = Path(path)
        try:
            stat = path.stat()
            return (str(path), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
        except OSError:
            return (str(path), None)

    def get(self, appid, source="hero", style="logo_dim", position="bottom"):
        appid = int(appid)
        if appid <= 0:
            return None
        sources = tuple(dict.fromkeys((source, "hero", "capsule", "header")))
        identities = tuple(
            (kind, self._file_identity(artwork._find_artwork_details(appid, kind)[0]))
            for kind in sources if kind in {"hero", "capsule", "header"}
        )
        key = (appid, source, style, position, identities,
               self._file_identity(artwork.find_logo(appid)) if style != "art" else None)
        with self.lock:
            if key in self.frames:
                self.frames.move_to_end(key)
                return self.frames[key]
            rgb, path, actual_source = artwork.artwork(appid, source, style, position)
            if rgb is None:
                return None
            if len(rgb) != WIDTH * HEIGHT * 3:
                raise ValueError("Automatic Dashboard requires one native RGB frame")
            result = (bytes(rgb), str(path), str(actual_source))
            self.frames[key] = result
            while len(self.frames) > 8:
                self.frames.popitem(last=False)
            return result
