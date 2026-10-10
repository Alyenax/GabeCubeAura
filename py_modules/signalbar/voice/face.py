"""Gabe's face on the JSAUX pixel faceplate, if there is one.

The panel only takes GIFs, and every upload goes into its SPI flash and takes
a noticeable moment. So drawing a face frame by frame is out. Instead there
are four pre-made animated GIFs (idle, curious, thinking, talking) and each
mood change sends one whole file. The panel answers "already stored" when it
gets a GIF it's holding, so sending the same mood twice in a row costs
nothing. Whether it keeps more than one GIF around, so switching between
moods gets cheap after the first time, I'm not sure yet. That's worth
checking with the write counter the faceplate service keeps.

The faceplate code is in a separate PR. When it isn't installed, or the
service has no way to show a GIF, this does nothing at all and the assistant
works the same with a blank front.
"""

from __future__ import annotations

import os

MOODS = ("idle", "curious", "thinking", "talking")


class NoFace:
    """Used when there's no faceplate. Every call does nothing."""

    def show(self, mood):
        pass


class Face:
    """Shows a mood by handing the matching GIF to the faceplate service.

    The faceplate service doesn't have a "show this GIF" call today. This
    expects one called show_gif(path) that takes the link lock, uploads the
    file with Link.send_gif and returns to the user's chosen mode later. That's
    a small addition on the faceplate side and the one bit of glue left.
    """

    def __init__(self, show_gif, faces_dir, logger=None):
        self._show_gif = show_gif
        self.faces_dir = faces_dir
        self.log = logger
        self._current = None

    def show(self, mood):
        if mood not in MOODS or mood == self._current:
            return
        path = os.path.join(self.faces_dir, mood + ".gif")
        if not os.path.isfile(path):
            return
        try:
            self._show_gif(path)
            self._current = mood
        except Exception as error:
            # A busy or unplugged faceplate never gets to stop an answer.
            if self.log:
                self.log.warning(f"[GabeCubeAura] voice face: {type(error).__name__}: {error}")


def for_faceplate(service, faces_dir, logger=None):
    show_gif = getattr(service, "show_gif", None)
    if not callable(show_gif) or not os.path.isdir(faces_dir or ""):
        return NoFace()
    return Face(show_gif, faces_dir, logger)
