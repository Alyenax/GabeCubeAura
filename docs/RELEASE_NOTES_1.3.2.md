GabeCubeAura 1.3.2 turns Audio Sync into a complete permanent display, adds
one-step lighting presets and gives SteamOS integration clearer, safer control.

## Highlights

- Audio Sync reacts to game and system audio with ten patterns, including
  Hi-Fi Crest, Slow Prism, Spectrum and Stereo Field.
- Home and in-game Audio Sync can use different patterns, palettes and custom
  colours. Artwork and live Screen Sync colours work with every pattern.
- Nine lighting presets switch the complete setup in one action: Lights out,
  Focus, Essential, Moderate, Atmosphere, Signals, Immersive, Immersive+ and
  Festive.
- Artwork colour intensity ranges from greyscale to vivid colour without
  changing brightness or reloading the image.
- The optional SteamOS top-bar indicator shows current weather beside the clock
  with three locally bundled icon styles.
- Consistent output calibration, Blackout and three Steam ownership policies
  provide predictable brightness and safer handoff to native effects.
- Fresh installations use Stable updates, check every 24 hours and contain no
  Private Lab authorization or token.

## Major fixes

- Audio Sync now preserves partial PipeWire reads, processes every complete
  analysis block in order and never renders stale samples.
- Audio and live colour state survive Home/game changes, launch animations and
  capture restarts without blue or fallback-colour flashes.
- Steam download detection no longer treats queued or deferred work as an
  active transfer, and LED manager ownership recovers correctly after Decky
  restarts or rejected requests.
- Screen Sync releases stale capture clients and recovers cleanly across plugin
  replacement, AppID changes and Desktop/Gaming Mode transitions.
- Artwork colour intensity now passes through the real Decky RPC allowlist and
  remains stored instead of returning to 100%.

## Minor fixes

- Improve Hi-Fi Crest timing and optional diagnostics.
- Add Sapphire and Coastline palettes and smoother live-source transitions.
- Make every lighting preset explicit about Audio Sync, controller and Steam
  event routing.
- Reduce only the Clear sky night moon whites while preserving every other
  Weather scene.
- Simplify colour controls, quick-panel copy and advanced diagnostics.

## Installation

Download `GabeCubeAura-v1.3.2.zip` and install it through Decky Loader without
extracting it. `GabeCubeAura.zip` is the identical fixed-name archive used by
the updater and recovery flow. SHA256 values are provided in `SHA256SUMS`.

Software tests cover rendering, routing, capture recovery, updates, ownership
and packaging. Physical diffuser appearance and response latency still depend
on the SteamOS build and target Steam Machine hardware.
