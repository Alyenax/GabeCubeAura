# GabeCubeAura 1.3.0

GabeCubeAura 1.3.0 adds Audio Sync as a permanent display for Home, games and
individual Steam AppIDs.

## Audio Sync

- 17-band Spectrum gives every LED its own logarithmic frequency range.
- Stereo field follows left and right channel energy.
- Bass pulse mirrors the selected three-colour gradient around its low-frequency
  centre.
- Screen colours + audio pulse extracts three dominant colours from the current
  Gamescope image, mirrors their gradient around the centre and applies one
  global audio pulse.
- Screen colours + stereo field keeps those same three live hues while stereo
  energy controls their intensity through the exact Stereo field renderer. The
  selected audio palette remains the fallback for both screen-colour modes.
- Calm, Balanced and Fast response profiles, sensitivity, brightness, three
  built-in palettes and custom low/middle/high colours are included.
- A 15-second preview tests the real PipeWire path without changing routing.

Audio capture stays local in memory. The backend connects to the active user
PipeWire session, rejects stale samples and restarts after a session change.

## Priority safety

Audio Sync is integrated into the existing arbiter. Steam system animations,
native thermal warnings, playtime countdowns, Light Events, controller alerts
and Game launches keep their current priority. StripMine and TW3 SteamRGB keep
their explicit handoff behavior.

When Steam's screensaver requests Screen Sync, Audio Sync stops and Screen Sync
takes the bar. The selected Audio Sync route returns automatically when the
screensaver closes.

The read-only Gamescope capture remains stable across temporary Steam LED
ownership. If the Gamescope session itself disappears, GabeCubeAura closes the
capture, waits for the session to settle and only then reconnects.

## Before publishing

Validate the physical light direction, diffuser response, PipeWire session
identity and reaction latency on the target Steam Machine. This local release
has not been submitted to GitHub.
