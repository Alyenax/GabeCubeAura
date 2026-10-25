# Historical notices — not the current runtime inventory

Archived on 2026-10-25. This records earlier private Lab components, including voice, Cinema and Studio. Descriptions below are historical and do not assert their presence in the current candidate. Current runtime notices: ../THIRD_PARTY_NOTICES.md.

# Third-party notices

Gaby (internal asset family: playful-eyes) is original 64×54 artwork prepared from the user's approved eye
studies. Its fixed FR/EN performances were supplied by the user for private
integration on 21 October 2026. No source recording, voice model, live synthesis
or conversion engine is bundled. Source hashes and editorial boundaries are
recorded in assets/playful-voice/manifest.json; rights/redistribution permission
have not been independently verified. This bank is private-only and carries
no claim of association with a performer or game character. See its NOTICES.txt.

Animated Screensaver Studio's active HTML/CSS/JS player is adapted from Alyenax's
Steam Animated Screensaver 1.1.1, commit 8139284d160666266b909e58a3487af0fd875546,
copyright 2026 Alyenax, GPL-3.0-only. Its applicable license is shipped as
`licenses/Steam-Animated-Screensaver-GPL-3.0.txt`; modified corresponding source
is included in this repository and the plugin archive's player directory.
The older MIT grant remains retained in `licenses/SteamOS-Animated-Screensaver-MIT.txt`
for earlier incorporated work; it does not relicense the current GPL player.
Adaptations add capability-protected Decky preview, cut transitions and an
optional collection faceplate relay. No Electron, standalone Manager or background UI is shipped.
The Studio queue/catalog are a new Decky-native implementation. Low-level
verified tool downloads, process supervision and USB ownership are reused.

SteamGridDB artwork stays in the user's separate local library; artist
attribution and source URLs are retained. No downloaded game artwork, logo,
television video or generated screensaver GIF is distributed in the ZIP.

Optional Cinema video tools are downloaded only on explicit user action from
BtbN/FFmpeg-Builds, pinned to `autobuild-2026-09-30-13-08` and the Linux64 LGPL
shared variant (9.0.2 since Lab126, for native animated WebP decoding). Neither
FFmpeg binaries nor libraries are bundled in this ZIP.
The installer verifies the fixed SHA256 before extraction, preserves upstream
licence notices and records original download, builder and FFmpeg source links.
See `docs/CINEMA_STEAM_INTEGRATION.md` for exact bytes, digest and licensing
boundaries. The LGPL shared label does not imply LGPL 2.1; version-3 components
may apply. No claim of upstream review or SteamOS physical acceptance is made.

Optional voice activation uses a separately downloaded, frozen Vosk 0.3.45 phrase detector and
unmodified `vosk-model-small-fr-0.22` / `vosk-model-small-en-us-0.15` models.
Code and both models are Apache 2.0: https://alphacephei.com/vosk/models
The optional pack retains full dependency/Python/Vosk licence texts, pinned
upstream archive hashes, and model source/version notices. Only the selected
language model loads, and only after explicit local wake-listening consent.
No Vosk native package or model is imported/installed into Decky Python or
included in the plugin ZIP. Waiting PCM/text are never saved or exported.

Gabe's optional local voice pack is downloaded separately and contains native
Whisper.cpp/Piper engines, model cards, complete dependency license notices and
a companion corresponding-source archive. See `docs/GABE_VOICE_LICENSES.txt` and
the published `GabeVoice-corresponding-source-v1.zip`. No voice engine or model is
installed in Decky's Python environment. Gabe's face is a project-native
64×54 drawing. This private testing build also bundles fixed PCM responses prepared offline from
Piper Tom (French) and Joe (English), then converted with the user-supplied Gabe
RVC v2 model for private testing. Acoustic likeness is not independently verified.
The pinned model cards, source links and preparation notices are included in
`assets/gabe-launch-voice/`; no Tom/Joe ONNX or supplied RVC weights are bundled.

The legacy speech installer additionally downloads multilingual Whisper small Q5_1 weights only
through the explicit installer. OpenAI Whisper weights and whisper.cpp use the
MIT license; full texts are retained in the native pack. The public converted
model is pinned to Hugging Face revision
`5359861c739e955e79d9a303bcbc70fb988958b1`, SHA-256
`ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb`:
https://huggingface.co/ggerganov/whisper.cpp
No model download is triggered by starting the plugin or polling settings.

Current speech recognition uses the separately installed Faster-Whisper 1.2.1 / CTranslate2 4.6.0
CPU int8 runtime (MIT) and multilingual small weights pinned to
`Systran/faster-whisper-small` revision `536b0662742c02347bc0e980a01041f333bce120`.
All four model files have pinned sizes/SHA-256 values. The optional private
runtime archive retains dependency versions, full third-party license texts,
Python's license and OpenAI Whisper's model license. See
`licenses/Gabe-Faster-ASR-notices.txt` and `scripts/build_gabe_faster.py`.
No native recognition package is installed/imported into Decky Python; no
model downloads occur at activation or idle. CPP/Vulkan experiments remain
recoverable source history, not binaries in the Decky archive.

GabeCube Companion is a fan-art interpretation of Valve's Weighted Companion
Cube, not an official Valve product. The user-supplied original synthesized
musical pack contains no extracted Portal audio. It is retained only in the
private Lab candidate; public audio redistribution clearance is not established.
See `assets/companion-cube/NOTICE.txt`.

The optional musical-and-spoken Companion replies use original offline Piper
outputs, not Portal audio, Gabe's RVC bank or an actress voice clone. The
French Siwis dataset is CC BY 4.0; attribution and changes accompany the clips.
The English LJ Speech dataset is public domain in the United States. Model
cards and notices are retained in `assets/companion-voice`. The authoring
Piper engine and voice model weights are not included in the runtime archive.
Lab 107 applies the original V4 balanced WORLD-based pitch/formant treatment
offline to these synthetic outputs. No game audio, performer reference curve,
actor clone, WORLD executable or conversion model is shipped. Processing and
model provenance are recorded in `assets/companion-voice/manifest.json` and
`assets/companion-voice/NOTICES.txt`.

Lab 114 also provides the same original SIWIS/LJSpeech sources without the
robotic treatment in `assets/companion-voice-soft`, with their own model cards
and attribution. Short identity welcomes are prepared in both styles/languages.
The installed WAV storage is reversible delta/byte-shuffle plus stdlib zlib;
decoded WAV bytes are identical. This is not a voice model, lossy codec or TTS.

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

The optional JSAUX PIXEL Faceplate transport, artwork renderer and logind
power-event handling adapt
the serial framing, CH340 discovery, GIF encoder, GStreamer scaling and
hero/logo composition strategy documented and implemented by
[`hodapp/pixel-faceplate`](https://github.com/hodapp/pixel-faceplate), revision
`5614dd167b8a72504258558b13c4073002a4d6aa`, Copyright (c) 2026 Eli Hodapp,
under the BSD 3-Clause License. GabeCubeAura does not bundle or depend on that
plugin. Artwork discovery remains GabeCubeAura's own implementation. The
complete Pixel Faceplate license is reproduced in
`licenses/Pixel-Faceplate-BSD-3-Clause.txt`.

## Prospective BSD core and Faceplate-only PolyForm licensing

For future editions Alyenax-owned non-Faceplate code is BSD-3-Clause, while the scope and limitations of original Alyenax-owned Faceplate material under **PolyForm Noncommercial 1.0.0** are documented in [LICENSING.md](LICENSING.md) and `licenses/faceplate-scope.json`. The public v1.4.0 contained no Faceplate implementation or assets, so its BSD licence did not cover that absent work. Eli Hodapp's inherited BSD work and any rights actually granted to recipients remain unaffected. **v1.4.0 is the last public software release; all later development, including Lab 220, has remained private.** No blanket BSD grant to the private Faceplate implementation is inferred from a private tag, archive or repository-level licence file. Any external recipients and applicable grants must be established separately. Original private work can be included in the proposed future PolyForm scope where Alyenax owns and can license it. `licenses/BSD-3-Clause-previous.txt` preserves the previous root licence text; retaining that text does not establish public distribution of a Lab. GPL screensaver/player components keep their terms even if they enter the ZIP or JS bundle. Previously granted GPL rights are preserved. This policy does not certify authorship, third-party image rights or compatibility of GPL and noncommercial components.
