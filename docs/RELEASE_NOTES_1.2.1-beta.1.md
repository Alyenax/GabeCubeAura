# GabeCubeAura 1.2.1-beta.1

This is a local beta build without the experimental game telemetry Lab. It is
not published on GitHub and cannot be discovered by the in-plugin updater.

## Included

- Screen Sync, including game routing, Steam screensaver activation and the
  Customization+ fallback used during capture conflicts.
- Screen Sync session recovery v7: the read-only Gamescope capture stays warm
  while Steam temporarily owns the LEDs, failed or PAUSED pipelines are closed
  before retry, and rediscovery waits for the Gamescope/PipeWire session to
  settle after screensaver or Desktop/Gaming Mode transitions.
- Fixed one-to-four-controller battery layouts and controller event patterns.
- Weather displays and night variants.
- Stable and Beta update-channel support for versions that are actually
  published on GitHub.
- Existing Artwork, Performance, Customization+, Game launches, Light events
  and Playtime features.

## Removed from this build

- The experimental game HUD page and quick-panel entry.
- Its runtime provider, telemetry reader, installer and diagnostics export.
- Its companion script, packaging helper, settings and automated tests.

Install `out/GabeCubeAura-v1.2.1-beta.1.zip` manually through Decky Developer
settings. Its Screen Sync diagnostics report revision
`1.2.1-session-release-v7`. Keep the stable v1.1.3 package and a configuration
export available for rollback.
