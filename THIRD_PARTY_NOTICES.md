# Third-party notices

GabeCubeAura's initial hardware discovery and local Steam Library Hero lookup were
informed by SteamLED 1.1, distributed under the BSD 3-Clause License:

Copyright (c) 2026, SteamLED contributors

GabeCubeAura is a new implementation: it does not retain SteamLED's effect engine,
decorative effects, curated palettes, or runtime architecture.

The optional local-weather feature retrieves city matches and current conditions
from [Open-Meteo](https://open-meteo.com/). Weather data is attributed to
Open-Meteo. No Open-Meteo API key or automatic location detection is used.

Screen Sync launches the GStreamer and PipeWire command-line tools supplied by
SteamOS. Those tools and libraries are not copied into or redistributed with
the GabeCubeAura archive. Screen colour processing in this project is an original
implementation and does not copy OpenRGB Effects Plugin source code.

The optional SteamOS top-bar weather indicator includes selected SVG icons from:

- Material Symbols Rounded 0.47.6, Copyright Google LLC, licensed under the
  Apache License 2.0.
- Phosphor Icons Core 2.1.1, Copyright 2023 Phosphor Icons, licensed under the
  MIT License.

Only the icons needed for GabeCubeAura's nine weather conditions are bundled.
The complete license texts are included in the `licenses` directory.
