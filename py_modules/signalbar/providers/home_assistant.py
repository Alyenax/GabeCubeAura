"""The Home Assistant display: what Home Assistant last asked the light bar to show.

The MQTT bridge fills one slot, newest first: a colour and brightness, or a
17-pixel frame. The engine reads it each tick while the Home Assistant
display is selected. No MQTT and no hardware I/O live here.
"""

from __future__ import annotations

import threading

from signalbar.models import LED_COUNT, ProviderOutput, normalize_frame

WHITE = (255, 255, 255)


def _scaled(pixel, brightness):
    return tuple(round(channel * brightness / 255) for channel in pixel)


class HomeAssistantProvider:
    name = "home-assistant"

    def __init__(self):
        self._lock = threading.Lock()
        self._attached = False
        self._on = False
        self._colour = WHITE
        self._brightness = 255
        self._frame = None  # None shows the colour

    def attach(self, attached):
        """Called as the light bar's tier rises above or drops to Watch only; dropping empties the slot."""
        with self._lock:
            self._attached = bool(attached)
            if not attached:
                self._on, self._frame = False, None

    def set_light(self, on, colour=None, brightness=None):
        """Switch the light on or off, optionally with a new colour and brightness (0-255).

        Ignored while detached, so a bridge worker that outlived stop() can
        never light the bar.
        """
        try:
            clean = normalize_frame([colour] * LED_COUNT)[0] if colour is not None else None
        except (TypeError, OverflowError, ValueError) as exc:
            raise ValueError("colour is not three numbers") from exc
        try:
            level = max(0, min(255, int(brightness))) if brightness is not None else None
        except (TypeError, OverflowError, ValueError) as exc:
            raise ValueError("brightness is not a number") from exc
        with self._lock:
            if not self._attached:
                return
            if clean is not None:
                self._colour, self._frame = clean, None
            if level is not None:
                self._brightness = level
            self._on = bool(on)
            if not on:
                self._frame = None

    def set_frame(self, frame):
        """Show seventeen pixels as sent, scaled by the brightness, and turn the light on."""
        try:
            clean = normalize_frame(frame)
        except (TypeError, OverflowError, ValueError) as exc:
            raise ValueError("frame is not seventeen colours") from exc
        with self._lock:
            if not self._attached:
                return
            self._frame, self._on = clean, True

    def light(self) -> dict:
        with self._lock:
            return {"on": self._on, "colour": self._colour, "brightness": self._brightness,
                    "frame": self._frame is not None}

    def output(self) -> ProviderOutput:
        with self._lock:
            on, frame, colour, brightness = self._on, self._frame, self._colour, self._brightness
        if not on:
            return ProviderOutput(self.name, None, "Home Assistant light is off")
        if frame is not None:
            return ProviderOutput(f"{self.name}:frame",
                                  normalize_frame([_scaled(pixel, brightness) for pixel in frame]),
                                  "Home Assistant frame")
        return ProviderOutput(self.name, normalize_frame([_scaled(colour, brightness)] * LED_COUNT),
                              "Home Assistant colour")

    def status(self) -> dict:
        with self._lock:
            return {
                "offered": self._attached,
                "on": self._on,
                "source": ("frame" if self._frame is not None else "colour") if self._on else "",
                "colour": list(self._colour),
                "brightness": self._brightness,
            }
