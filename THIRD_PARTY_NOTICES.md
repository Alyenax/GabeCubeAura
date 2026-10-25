# Third-party notices

GCA's own code is GPL-3.0-only. Only the original graphics positively identified in `licenses/faceplate-assets.json` use CC-BY-NC-SA-4.0. See [LICENSING.md](LICENSING.md) for scope. Upstream rights below remain unchanged.

## Pixel Faceplate

The JSAUX PIXEL Faceplate transport, GIF encoder, artwork/layout and logind power-event adaptations use work from https://github.com/hodapp/pixel-faceplate at revision `5614dd167b8a72504258558b13c4073002a4d6aa`, Copyright (c) 2026 Eli Hodapp, BSD-3-Clause. Complete terms: `licenses/Pixel-Faceplate-BSD-3-Clause.txt`. Upstream portions in artwork.py, gif.py, protocol.py, transport.py, artwork_layout.py and power_events.py retain their terms and credits. GCA original additions remain GPL-3.0-only. The upstream plugin itself is not a runtime dependency.

## Decky API and UI

`@decky/api` 1.1.3, SteamDeckHomebrew Team, LGPL-2.1, https://github.com/SteamDeckHomebrew/loader-api. Its short connection wrapper is incorporated into `dist/index.js`. Exact installed source files, distributed wrapper, package metadata and LGPL text are supplied unchanged under `licenses/decky-api-1.1.3/`. File hashes are recorded in `licenses/third-party-files.json`.

`@decky/ui` 4.12.1 declares LGPL-2.1. The Rollup configuration treats it as the external Decky host library (`DFL`); its implementation is not copied wholesale into this plugin bundle. Its unchanged LGPL text is `licenses/Decky-UI-LGPL-2.1.txt`. React, React DOM and JSX runtime are likewise supplied externally by the host.

For rebuilding or replacing the API wrapper, use the complete corresponding GCA source tree with its pnpm lockfile, `pnpm install --frozen-lockfile`, then `pnpm build`. Replace/edit the API dependency source as needed before rebuilding. The exact wrapper snapshot accompanying this release identifies the incorporated code; the complete corresponding source and lockfile accompany version 1.5.0. No extra noncommercial restriction is imposed on that code or its modification.

## Icons

`react-icons` 5.7.0 helpers, Copyright 2018 kamijin_fanta, MIT: unchanged upstream notice `licenses/React-Icons-LICENSE.txt`. Only the selected Tabler icons imported from `react-icons/tb` are used here; the upstream licence file also describes other icon families, which are not thereby claimed as bundled.

Tabler Icons, selected icons incorporated through react-icons/tb, Copyright (c) 2020-2026 Paweł Kuna, MIT. Complete text: `licenses/Tabler-Icons-MIT.txt`; upstream licence snapshot https://github.com/tabler/tabler-icons/blob/a4ce1404bc6d24d3c365afe7b258d6bf6f48d62d/LICENSE. This identifies the captured licence text; the exact Tabler icon revision inside react-icons 5.7.0 has not been established.

The top-bar weather indicator includes selected Material Symbols Rounded 0.47.6, Copyright Google LLC, Apache-2.0, and Phosphor Icons Core 2.1.1, Copyright 2023 Phosphor Icons, MIT. Texts: `licenses/Material-Symbols-Apache-2.0.txt`, `licenses/Phosphor-Icons-MIT.txt`. These third-party icons are excluded from the Faceplate artwork licence.

## Weather, Steam artwork and host tools

Weather city matches and conditions come from Open-Meteo, https://open-meteo.com/. The service/data terms are separate from the licence on GCA's original weather illustrations. No API key or automatic location detection is used.

SteamGridDB artwork remains in the user's local library with its artist/source information. User imports and third-party game images are not relicensed by GCA.

Screen Sync invokes GStreamer and PipeWire supplied by SteamOS; their binaries/libraries are not copied into this archive. Initial hardware discovery and local Steam Library Hero lookup were informed by SteamLED 1.1, Copyright (c) 2026 SteamLED contributors, BSD-3-Clause. GCA does not retain its effect engine, decorative effects, curated palettes or runtime architecture.

## Historical sources and licence records

Earlier Studio/player adaptations from Alyenax's Steam Animated Screensaver keep their applicable GPL terms. GPL text is retained in `licenses/Steam-Animated-Screensaver-GPL-3.0.txt`; older applicable MIT records remain in `licenses/SteamOS-Animated-Screensaver-MIT.txt`. The current runtime allowlist excludes the historical standalone player, voice/assistant, Studio and Cinema directories. Their earlier source notices are archived at `docs/HISTORICAL_THIRD_PARTY_NOTICES.md`, not asserted as current runtime components.

`licenses/BSD-3-Clause-previous.txt` is the historical GCA root licence, not today's default licence. Actual historical grants and upstream notices are not revoked. Build tools such as @decky/rollup and tslib are development dependencies and retain their own terms; the installed tool versions alone do not imply that their entire code is bundled.
