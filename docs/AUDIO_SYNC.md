# Audio Sync

Audio Sync is a permanent GabeCubeAura display for the official Steam Machine's
17-pixel light bar. It captures the default PipeWire output as raw 48 kHz stereo
audio, analyses it locally and keeps a bounded in-memory queue of complete
sample blocks. Partial reads remain in the buffer for the following block, so
no audio is discarded merely because PipeWire's requested 50 ms cadence differs
from the 60 ms analysis hop. Audio is never written to disk or sent over the
network.

GabeCubeAura's Light bar brightness remains a global hardware gain after these
RGB calculations. Day brightness applies to every route; optional night
brightness is a percentage of it. The default `9 / 255` preserves the approved
1.3.2 output, and Steam's original value is restored exactly on every normal
handoff. Audio Sync's own Brightness control still sets the pattern's RGB
ceiling. Automatic programme-level matching handles different source levels
without a manual gain.

## Modes

- **Hi-Fi Crest** is the adaptive zoned pattern. Bass impact occupies the
  centre, mid attack uses two broad shoulders and high texture reaches both
  edges. Stereo balance weights each side without moving the colour roles. A
  strong bass onset launches one restrained centre-out crest.
- **Velvet Relay** is experimental. It passes a bass impact from the centre to
  the shoulders and then the edges in three broad, overlapping zones.
- **Negative Bloom** is experimental. It keeps a safe luminous base while a
  moving gap uses exact black instead of unreliable dark brown or grey RGB.
- **Stereo Lanterns** is experimental. It uses two broad, stationary left and
  right lobes with a restrained mono centre instead of a travelling meter.
- **Constellation** is experimental. It limits the strip to five tinted cores
  with weaker immediate neighbours so the strong diffuser keeps visible gaps.
- **Slow Prism** is experimental. Its hue target changes once every eight
  60 ms analysis blocks while audio controls the illuminated width.
- **17-band spectrum** assigns one logarithmic frequency range from about 45 Hz
  to 16 kHz to every LED.
- **Stereo field** maps left and right channel energy across the physical bar.
- **Bass pulse** mirrors the selected three-colour palette as an edge, shoulder,
  centre, shoulder, edge gradient, with low-frequency energy strongest at the
  centre and softer toward both edges.
- **Audio pulse** arranges the selected three-colour palette as a mirrored edge,
  shoulder, centre, shoulder, edge gradient and lets one global audio envelope
  drive brightness.

Patterns and palettes are independent. Screen Sync or Artwork can therefore
colour Hi-Fi Crest, Slow Prism, Stereo Field, Audio Pulse or any other pattern.
The former Screen colours + audio pulse setting migrates to Audio Pulse with
Screen Sync. Screen colours + stereo field migrates to Stereo Field with Screen
Sync.

Every pattern uses a Blackman-windowed 2048-sample FFT every 60 ms and automatic
source-level matching. Bass, mid, high and shared stereo ranges adapt to the
15th and 92nd percentiles of a bounded 10.2-second window. The 17-band Spectrum
uses one shared dB reference for the full bar, so it follows programme loudness
without flattening the real differences between its frequency bands. Positive
spectral flux keeps attacks visible without forcing the entire strip to full
brightness. Calm, Balanced, Fast and Punchy change the response times. Punchy
is the explicit maximum-response profile: all envelopes follow one 60 ms
analysis block, a Hi-Fi Crest wave may retrigger every 120 ms and travels from
centre to edge in 120 ms. Brightness remains bounded by the same 34 to 255
hardware-safe range as the other permanent displays.

Selecting a pattern loads a hardware-oriented recommendation for Brightness
and Reactivity. Broad, white-sensitive modes are intentionally
lower; sparse patterns such as Constellation receive more headroom. Fast is
used where attack shape, a travelling gap or Slow Prism's deliberately slow
colour drift needs definition. Balanced remains the reference for broader
stereo fields and Hi-Fi Crest. The controls stay editable after selection, and
Restore recommended tuning reloads only those reference values without
replacing the chosen palette.

Pattern, palette and Custom colours are selected independently for Home and
in-game use. Brightness, Reactivity and the Hi-Fi Crest Lab controls are
shared. Selecting a pattern recommendation in either context therefore changes
the shared response values, while leaving both contextual palettes untouched.
A settings migration copies the former single pattern, palette and custom
colours to both contexts. Fresh installations use Slow Prism with Screen Sync
at Home and in games, Fast response and brightness 180.

The five experimental patterns share an additional optical encoder. Values
below the useful threshold become exact black. Active points are raised to a
minimum useful peak, near-neutral colours receive a modest warm counter-bias,
white-rich colours become a warm neutral and every channel is capped at 212.
This is intentionally unlike a textbook RGB visualizer: motion is expressed
mainly by coverage and spatial shape because low RGB values and white blending
are unreliable on this diffuser. The normal Brightness control remains the
overall ceiling.

Aurora, Ember, Magma, Forest, Ice, Copper, Solar, Pearl, Glacier, Lagoon, Lime,
Orchid, Plasma, Sunset, Deep Sea, Silver, Candy, Sapphire and Coastline are
built in. The expanded
bank deliberately includes saturated, pastel and white-rich combinations for
physical testing against the Steam Machine diffuser. Custom supplies three colour
roles. Screen Sync extracts three stable roles directly from the raw 34 by 18 Gamescope
sample, then falls back to the current game's three-colour artwork palette and
finally Sapphire. Artwork uses that active game palette directly, with Sapphire as
its fallback. Its three colours follow the current game's Artwork colour
intensity setting without resampling the image. The Audio Sync page reports
Screen Sync, Artwork or Sapphire fallback so this state is not ambiguous.

Sapphire fallback is used only when no stable palette has ever been rendered.
During a game launch or exit, the renderer preserves the last stable palette
while PipeWire and the new contextual source restart. Once a fresh Screen Sync
or Artwork palette arrives, the existing interpolation fades toward it. This
prevents a temporary fallback frame from appearing between contexts.

## Temporary Hi-Fi Crest Lab

The Decky Audio Sync tab exposes three live calibration controls only while
Hi-Fi Crest is selected. Crest strength isolates the travelling wave, Edge
reach controls how much of that wave remains at the outer LEDs and Background
level controls the permanent three-band visualizer underneath it. All three
default to 100%, which reproduces the reference renderer. These controls are a
temporary physical-hardware lab and can be removed after the target values are
validated.

The Lab also reports the timing path directly: 50 ms requested PipeWire
latency, 42.7 ms FFT window, 60 ms analysis hop, measured blocks per second,
sample age, residual buffer, queue depth, 60 ms LED request cadence and the
renderer 50 ms floor. Calm, Balanced, Fast and Punchy expose their discrete
90% rise and fall times for level, impact, attack, texture and background
envelopes, plus crest retrigger, centre-to-edge and lifetime timing. This live
telemetry is hidden by default behind Show live diagnostics in both the quick
Decky view and the detailed settings page. Screen Sync uses the same opt-in
presentation for its own technical telemetry.

## Ownership and screensaver handoff

Audio Sync uses GabeCubeAura's existing provider, arbiter and renderer path. It
does not write around the LED ownership guard.

The priority order remains unchanged:

1. Steam hard system activity and native thermal warnings.
2. Critical playtime countdowns.
3. Short Light Events and controller alerts.
4. Game launch animations and regular countdowns.
5. The selected permanent display, including Audio Sync.

When Steam's screensaver is detected and **Use during Steam screensaver** is
enabled on the Screen Sync page, the engine deactivates Audio Sync before
selecting Screen Sync. When the screensaver lease ends, the saved Home or
in-game route is resolved again and Audio Sync starts a fresh PipeWire capture.
TW3 SteamRGB and StripMine retain their configured ownership handoffs.

The read-only Gamescope capture is kept warm across temporary LED ownership
changes. This prevents Steam's native writes during screensaver return from
repeatedly destroying and recreating the video PipeWire client.

## Capture and recovery

The backend uses `pw-record` or `pw-cat` from the PipeWire tools already present
on SteamOS. It connects as the owner of the active `/run/user/<uid>` PipeWire
session even when Decky runs the backend as root. The stream requests raw S16LE,
48 kHz, two-channel data and the PipeWire `stream.capture.sink=true` property.

The supervisor rejects audio blocks older than one second. A silent, stopped or
replaced PipeWire stream is closed and retried with bounded backoff. Game and
session changes stop the former reader so the next activation cannot reuse a
stale connection.

The Audio Sync page reports:

- capture revision and state;
- PipeWire runtime directory and Unix identity;
- sample rate, channel count, target and measured block rate, FFT window,
  requested capture latency, residual buffer and queue depth;
- latest block age, left/right levels, Hi-Fi Crest impact, attack, texture,
  stereo and rolling-window values, the extracted three-colour image palette
  and the 17 rendered colours;
- LED request timing, renderer floor and the selected reactivity profile's 90%
  rise/fall times;
- an explicit dropped-block warning if the bounded processing queue ever fills;
- bounded stderr details when capture cannot start.

## Validation boundary

Automated tests validate FFT band order, all ten 17-pixel renderers, Hi-Fi
Crest optical zones, centre-out propagation and lab bounds, stereo direction,
bass selectivity, stale-data
rejection, settings migration and the arbiter priority order. A local build can
confirm that the backend starts and packages correctly. Physical diffuser
appearance, reaction latency and the Decky-to-user PipeWire session must still
be checked on the target Steam Machine before public release.
