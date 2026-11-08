# Screen Sync

Screen Sync is integrated into GabeCubeAura's normal display routing. It uses
the same Providers to Arbiter to Renderer pipeline as Artwork, Performance,
Weather and Customization+. The renderer remains the only production component
that writes to the LED hardware.

## Activation

Screen Sync can run for four reasons:

1. it is the selected in-game display;
2. it is saved for the current Steam AppID;
3. Steam's screensaver is active and the independent option is enabled;
4. the user starts the bounded 15-second preview.

Screensaver and preview activation do not rewrite Home, in-game or per-game
display choices.

The Steam adapter only requires the read-only `GetActiveState` capability. It
uses an active-state notification when available and keeps bounded polling as a
fallback. During the screensaver, Screen Sync replaces Audio Sync, Weather,
Controllers, Customization+ or Performance without displacing temporary Light Events,
controller alerts, previews, Game Launches or Steam hard-priority animations.

## Local capture and processing

The backend checks every local PipeWire runtime with `pw-dump`, selects the
session that actually exposes the Gamescope video node, then starts a
GStreamer process without a shell and requests a 34 by 18 BGRx stream at 10
frames per second. Only the newest frame is retained. Captured pixels are not
saved, returned through Decky or sent over the network.

During live capture, a separate worker checks complete PipeWire registry
snapshots every two seconds, or every half-second during Preview. Waiting for
an inventory no longer holds up video-frame reception. Failed or stale
observations stop the current capture through the bounded recovery path;
they are never treated as evidence that the graph is empty. The polling
frequency and conflict policy remain unchanged.

The preferred selector uses the stable `gamescope` target name, the dedicated
GabeCubeAura client name and a short keepalive for Gamescope's variable-rate
stream. If no frame arrives, supervision closes the failed client before
trying the same target name without the keepalive property, then the discovered
numeric node ID when one is available. This keeps compatibility with PipeWire
builds that expose different source properties.

`Selector (compatibility): Gamescope name` is an expected fallback when
`pw-dump` cannot enumerate a numeric Gamescope node. If frames arrive, the
Screen Sync page reports that the direct source is active and no action is
required. A pipeline stuck in PAUSED is released before retry. A complete
failed selector cycle or repeated short sessions pause automatic reconnection;
the page reports the failure and an explicit Preview can request another try.
Temporarily unavailable session discovery uses bounded backoff.

Panorama maps 17 horizontal image zones to 17 LEDs. Ambient calculates one
robust screen colour and repeats it across the bar. Processing includes linear
RGB averaging, bright-HUD reduction, stable cinematic-bar detection, a black
threshold, colour intensity, brightness, spatial blending and asymmetric
temporal smoothing.

## Capture safety

Camera, V4L2 and loopback nodes are rejected. Capture stops when Screen Sync is
no longer requested, the plugin is disabled, StripMine owns the feature, Steam
Game Recording starts, another Gamescope consumer appears, the stream becomes
stale or the plugin unloads. Temporary LED priorities do not stop the read-only
capture; the arbiter blocks LED writes while keeping the Gamescope client warm.

When capture is unavailable because recording or another consumer is active,
the saved Customization+ effect becomes the fallback. Steam recording can keep
a pure red centre LED over that fallback. Missing capture tools or a missing
Gamescope source produce a visible status error. GabeCubeAura does not install
system packages.

## Steam ownership and continuity

Steam's game-lifetime service confirms the active AppID. Temporary zero values
from `Router.MainRunningApp` during menus, overlays or idle periods do not end
that session. Polling remains a recovery source when lifetime callbacks are
unavailable.

Steam keeps hard priority during startup, active downloads and repeated native
LED writes. One isolated native transition receives a settle period before one
automatic recovery. Genuine system activity can renew the priority lease, so
GabeCubeAura does not fight Steam for the bar.

While the renderer owns the bar, Linux sysfs reads reuse a bounded set of read
descriptors. Every attribute is read again at offset zero, and its device,
inode, permissions and ownership are checked before reuse. Each read obtains
the current attribute contents. A changed identity or read error invalidates
the hardware instance for rediscovery. Descriptors close on handoff, render failure,
orientation change and suspend/resume; the write path remains unchanged.

An AppID transition is also a capture-session boundary. GabeCubeAura terminates
the current `gst-launch-1.0` process and creates a new supervisor if Screen Sync
is still requested, preventing a stale Gamescope/PipeWire client from being
carried into the replacement pipeline's PAUSED preroll.

A Decky plugin replacement can cross the Desktop and Gaming Mode boundary
without giving the former backend time to reap its GStreamer child. Every new
capture now runs in a dedicated process group. Before connecting to Gamescope,
the supervisor also releases only orphaned `gst-launch-1.0` processes carrying
the exact `GabeCubeAura-Screen-Sync` client marker. It never uses a broad process
name match and therefore does not stop Steam Game Recording or another capture
application. The recovery count is visible on the Screen Sync page.

A pipeline that fails during PAUSED preroll is terminated before any retry
delay begins. GabeCubeAura clears its stale frame, releases its own PipeWire
link and only then tries the compatibility selector or performs fresh
discovery. The release counter and last GStreamer error are visible on the
Screen Sync page. Other PipeWire clients are never terminated by this path.

If a pipeline that had already delivered frames loses Gamescope, the supervisor
treats it as a session transition. It closes the complete capture process group,
waits at least two seconds and then starts discovery again from the stable
Gamescope name. A Desktop session without a Gamescope source remains closed and
uses bounded rediscovery instead of rapidly cycling GStreamer clients.

## Target-hardware checks still required

- Gamescope source discovery in Gaming Mode
- 30 minutes near 10 frames per second without stale frames
- CPU, GPU and frame-time impact in bright, dark and high-motion games
- SDR, HDR, letterboxing, Steam overlay and Quick Access Menu
- launch, exit, switch, suspend and resume continuity
- Steam Game Recording and another capture consumer
- screensaver start and stop without changing saved display routing
- physical left-to-right orientation, diffuser colour and black behaviour
- Steam downloads, Game Launches, Light Events, controllers and countdowns
- StripMine handoff and restoration

Software checks cannot close these hardware items.

## Capture pipeline and supervision

The 10 fps videorate stage now precedes pixel conversion and scaling. Its input queue remains limited to one frame and leaky downstream. Final BGRx 34 × 18 caps, interpolation and colour processing are unchanged. A displayed 10 fps is the received Python rate; it does not establish the Gamescope producer rate or resolution. Software validation includes a native variable-rate synthetic producer and the real GCA capture supervisor. Gamescope GPU cost, source-side reduced-size negotiation and Steam game frame-time improvement remain target-system validation items.

Capture v12 retains that pipeline and moves registry polling away from the
frame-draining thread. It continues using complete inventories.
