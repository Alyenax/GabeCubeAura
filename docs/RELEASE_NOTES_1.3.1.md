# GabeCubeAura 1.3.1

GabeCubeAura 1.3.1 adds Hi-Fi Crest, an adaptive Audio Sync pattern designed
for the official Steam Machine's 17-pixel light bar and physical diffuser.

## Hi-Fi Crest

- Bass impact occupies the centre.
- Mid attack uses two broad mirrored shoulders.
- High-frequency texture reaches both edges.
- Stereo balance weights both sides without changing the colour roles.
- Strong bass onsets launch one restrained centre-out crest.
- A rolling 10.2-second window adapts independently to bass, mid, high and
  stereo energy while spectral flux preserves visible attacks.

Calm, Balanced and Fast remain available. Balanced uses the response tuned in
the Hi-Fi Crest visual study. Automatic programme-level matching adapts to
different source levels. A temporary Decky Lab exposes crest strength, edge
reach and background level for live physical calibration, with 100% preserving
the reference renderer. Palette offers Aurora, Ember, Magma, Forest, Ice,
Copper, Solar, Pearl, Glacier, Lagoon, Lime, Orchid, Plasma, Sunset, Deep Sea,
Silver, Candy, Sapphire, Coastline, Screen Sync, Artwork and Custom. Screen Sync and Artwork turn
their sampled colours into three harmonized optical roles: a light bounded
centre, darker shoulders and much darker edges. Black and pure white samples
cannot take over the centre. Screen Sync falls back to the current game's
Artwork palette, then Aurora. Artwork falls back to Aurora.

## Private Lab updates

The Updates page can connect to Alyenax's private GabeCubeAura hardware lab
through GitHub's device-code flow. The GitHub App requests read-only Contents
access and is installed only on `Alyenax/GabeCubeAura-Lab`. Private credentials
are stored in a separate owner-only runtime file, never in exported settings.
Private `vX.Y.Z-lab.N` releases use the same checksum, package validation,
manual confirmation and rollback protections as public releases.

## Lab 4 routing and ownership

The private 1.3.2 Lab 4 build adds seven routing presets: Lights out, Focus,
Essential, Moderate, Signals, Immersive and Festive. Lights out and Essential
use Blackout, which holds all 17 LEDs off without releasing the bar to Steam.
The former GabeCubeAura Off choice still releases the permanent display
normally.

Focus uses only Customization+. Moderate combines Customization+ at Home with
Artwork in games. Signals uses Controller status at Home and CPU/GPU in games.
Immersive uses Slow Prism with Sapphire at Home and Screen Sync in games.
Moderate, Signals, Immersive and Festive enable Light Events. Their Game launch and screensaver Screen Sync layers
match the concise descriptions shown in Display routing.

Lab 17 adds Atmosphere immediately after Moderate. It keeps Moderate's Artwork
game display and temporary layers, but uses Audio Sync with Slow Prism and the
Aurora palette at Home.

Lab 18 extends the bounded 10.2-second source-level matching to all eleven
Audio Sync patterns. Each pattern now loads a separate Steam Machine reference
for Brightness and Reactivity, and the Decky page can restore that
recommendation without changing the selected palette.

Lights out, Focus and Essential suppress controller alerts and charging output.
Moderate, Immersive and Festive enable connection, low-battery and brief
charging signals at Home and in games. Signals uses the same brief alerts and
keeps its continuous charging animation at Home. Presets preserve controller
colours, animation variants, brightness and the low-battery threshold.

Compatible keeps the established compatibility-first handoff. Downloads +
safety reclaims ordinary Steam writes while retaining confirmed download
animations and the critical red safeguard. It holds Steam's private Download
mode for the life of each confirmed transfer. Safety only instead holds
Customize mode, preventing the blue animation from starting. Both requests are
released when the download ends. Unsupported Steam builds are left untouched.
Steam exposes no public semantic thermal-warning source, so the red
exception is conservative physical-pattern recognition rather than guaranteed
source identification. The service path and the safety handoff still require
validation on the physical Steam Machine.

The main Decky tab now exposes the same temporary Hi-Fi Crest Lab controls as
the detailed Audio Sync page, including a real 15-second preview.

## Priority safety

Hi-Fi Crest uses the existing Audio Sync provider, arbiter and hardware
renderer. It does not write directly to the light bar. Playtime countdowns,
Light Events, controller alerts and Game launches keep their existing order.
Steam activity follows the selected Lab 3 ownership policy, and the critical
red safety pattern always wins. Screen Sync still stops Audio Sync when Steam's
screensaver takes over, then Audio Sync starts with a fresh analysis window
when the screensaver closes.

## Validation boundary

Software tests cover the six Audio Sync patterns, Hi-Fi Crest frequency zones,
stereo direction, settings, stale capture rejection and ownership priority.
Physical diffuser appearance, PipeWire session identity and reaction latency
still require validation on the target Steam Machine before publication.
