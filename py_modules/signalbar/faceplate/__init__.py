"""JSAUX Pixel Matrix Faceplate: the 64x54 RGB panel on the front of the Steam Machine.

It sits behind a CH340 USB serial adapter and keeps whatever it is sent in
its own flash, so the service sends a picture only when it changes. Protocol
notes and the hardware write-up: https://github.com/hodapp/pixel-faceplate
"""

from __future__ import annotations

from .power_events import PowerEvents
from .service import FaceplateService

__all__ = ["FaceplateService", "PowerEvents"]
