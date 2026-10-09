# GabeCubeAura architecture

## Pipeline

`Providers → Arbiter → Renderer`

- **Providers** collect or hold facts and produce optional 17-pixel frames.
  `PerformanceProvider` reads local CPU/GPU Linux metrics at 2 Hz,
  `ArtworkProvider` owns validated/cacheable browser samples. A separate
  launch-artwork cache owns the two- and three-colour palettes used by
  `LaunchArtworkProvider`,
  `CountdownProvider` owns independent parental/free/preview deadlines,
  `EventProvider` owns short queued animations and recording state,
  `ControllerProvider` owns controller inventory, battery thresholds and
  optional gauges, `ScreenSyncProvider` owns the newest derived Gamescope
  colours, and `IdleProvider` deliberately emits no frame (Vanilla).
- **Display routing** selects one permanent provider independently for Home and
  in-game contexts, with an optional AppID override. Game launches, Playtime,
  Light events and Controller alerts are temporary layers; they do not change
  the selected permanent provider.
- **Arbiter** is pure policy. Disabled is an explicit user stop. Short, opted-in
  events can play over a stable native frame even when no game is running.
  Otherwise Valve/explicit Steam activity is above GabeCubeAura providers, Steam
  Families is above the personal timer. A launch animation is above a regular
  timer but below its critical final five minutes. Short alerts pause the
  launch's visible timer, then it resumes; critical countdowns cancel it.
  A recording marker may decorate only a base display. Its centre pixel
  replaces, rather than blends with, the base colour. Optional isolation makes
  its immediate neighbours black to reduce optical bleed through the diffuser;
  this isolation is enabled by default.
  Low-battery animations outrank ordinary short events. The controller gauge,
  Weather, Artwork, Performance, Screen Sync, or Steam/default is the routed permanent
  display for a context and never displaces a temporary layer.
- **Renderer** is the only production component holding the hardware adapter.
  It validates exactly 17 RGB pixels, serializes access, coalesces identical
  frames, rate-limits writes, reads back the actual signature and fails closed.

## Startup lifecycle

Decky's one-time frontend plugin initializer starts a background GabeCubeAura
runtime immediately when the bundle loads. That runtime reports the already
running game, polls as a fallback, subscribes to game lifetime, Steam Families,
download, controller and resume events, and samples local Artwork without waiting for the
settings panel to mount. Backend calls that race plugin startup are retried.
The panel is only a view and settings surface; closing or never opening it does
not stop providers. `onDismount` unregisters every Steam callback and timer.
Steam notification types supply generic notices, achievements and recording
transitions. The GameSessions screenshot hook accepts only written captures;
the generic screenshot type is fallback. The frontend sends only a validated
event kind to the backend, never notification contents.

## Controller battery flow

The Decky runtime subscribes to Steam controller-list and battery callbacks.
Steam sends battery percentages as an ordered array aligned with the latest
controller list, so the runtime retains that order and serializes snapshots
before sending them to the backend. A battery snapshot received before the
initial list is deferred rather than discarded. The first inventory snapshot
is a baseline, not a fake connection alert. The backend validates at most eight
entries and never converts an unknown or coarse battery reading to a displayed exact percentage.
Coarse one-to-four levels can still drive a labelled approximate gauge; the
lowest level can trigger a warning. Exact percentages use a configurable
low-battery threshold with hysteresis to avoid repeated alerts.

Brief alerts have an independent Home / In-game policy and can run with the
permanent gauge off. The provider's short animation expires by monotonic time;
the arbiter then recomputes the current display. A second controller can use
an eight-plus-dark-centre-plus-eight view. Critical playtime countdowns clear
controller animations, and a new native LED write cancels them through the
same ownership guard as other light events. The callbacks are private SteamUI
APIs, so controller-model compatibility requires device testing.

## Light-event arbitration

All animations start from a dark frame, suspend the selected base for 1.2 to 4.85
seconds, and expire by monotonic time. A per-category variant is validated and
persisted; queued effects retain the variant selected when they arrived, while
a manual preview plays immediately without changing the saved choice. At most
three pending effects queue; near-duplicate callbacks are coalesced. The current permanent display
or still-running countdown is recomputed after the animation. Critical
countdowns clear pending effects. Disabled is checked before event selection.
An event may take over a stable native frame, which Renderer snapshots and
restores only if its last write is still present. A fresh native write during
the animation cancels it immediately, without restoring the stale snapshot.
Recording start
sets a persistent centre marker over a compatible permanent display after its transient
effect; stop removes it, and game exit clears it. It is never applied to a
countdown or event frame. Previews do not set that persistent state.

## Vanilla Guard

The backend polls all `multi_intensity` and `brightness` attributes. After a
GabeCubeAura write, Renderer records the read-back signature. A later signature
that differs from that verified value is treated as external ownership:

1. abandon GabeCubeAura's remembered frame without restoring it;
2. report Valve as owner;
3. renew a cooldown on further changes;
4. require both cooldown expiry and a stable observation window;
5. only then allow Arbiter to select a GabeCubeAura provider again.

Native download callbacks in the Decky frontend create short renewable Steam
activity leases so the backend can yield before or during a known transition.
The lease expires automatically if the frontend vanishes.

No kernel module, binary patch, read-only OS modification or ownership fight
is used.

## Artwork flow

The backend locates the selected cached Library Hero, Header or Capsule for the
AppID and returns local bytes as a data URI. Steam's browser decodes the image using Canvas, evaluates
5.5%-high bands around 35, 45, 55, 65, 75 and 82 percent, then scores
saturation, contrast, adjacent colour diversity, black/white excess and
uniformity. The selected band is horizontally reduced to 17 zones with a mild
perceptual correction. Results are cached by AppID, artwork fingerprint and row
setting; no service or network is involved. Image source, row mode and manual
position are stored per AppID. Games without a profile use the global default
and never inherit the previously running game's custom Artwork choices. The
Library Logo is not sampled because it is a transparent overlay rather than a
complete backdrop.

## Screen Sync flow

`ScreenCaptureService` discovers the current Gamescope video source from the
user PipeWire graph. It starts a GStreamer child process only while Screen Sync
is the effective display for a running game. The process requests fixed 34 by
18 BGRx frames at 10 Hz and writes them to stdout through a one-frame leaky
queue. No screen pixels are saved, logged or returned to the frontend.

The service checks the PipeWire graph before capture and periodically while it
runs. An existing consumer prevents startup. A second consumer appearing later
stops capture. This conservative policy protects recording and screen sharing
until safe multi-consumer behaviour is proven on the official Steam Machine.
Missing tools, a vanished Gamescope source, a stalled stream or a frame older
than one second produces no provider frame. The child process is terminated and
retried with bounded backoff.

`ScreenSyncProcessor` decodes the tiny raw image, waits for three consistent
frames before cropping top and bottom black bars, converts samples to linear
RGB, removes the brightest five percent to reduce HUD influence and calculates
either 17 horizontal Panorama zones or one Ambient colour. It then applies the
dark threshold, brightness, optional saturation gain, horizontal diffuser blur
and asymmetric temporal smoothing. Three consistently black frames force an
exact black result. The final frame passes through the same exact 17-pixel
validation as every other provider.

Screen Sync is a permanent in-game display. It stays below countdowns, Game
Launches, Light Events and controller alerts, remains subject to Vanilla Guard,
and has its own StripMine priority. The renderer remains the only component
that writes the light bar.

## Performance layouts and orientation

CPU and GPU full-bar modes map 0 to 100% load to 0 to 17 pixels. Mixed maps CPU to
the left 8 pixels, keeps the centre pixel black, and maps GPU to the right 8.
The user can make both halves grow left-to-right, or mirror the GPU half so the
two signals grow from the outside edges toward the separator. Colour comes
from a selected three-stop palette and blends continuously between configurable
Cool and Hot temperature thresholds. Built-in palettes live in provider code;
the custom palette is persisted as three validated RGB triplets and follows the
same interpolation path in both the backend renderer and frontend preview.

Performance normally becomes eligible only while a game is running. The
optional `performance_always` setting also makes it eligible on the Steam home
screen, without bypassing Vanilla Guard or changing the priority of countdowns
and events.

The persisted 0 to 6 **Extra dark LEDs** value is applied only to the physical
Performance frame; the Decky preview remains logical. Full CPU/GPU meters also
receive the compensation. Mixed mode removes that number across both halves in
total, favouring the fuller side and retaining one pixel for each active meter.
Artwork bypasses this calibration.

Raw CPU and GPU percentages are sampled at 2 Hz, then independently filtered
through the selected Responsive, Balanced or Smooth response profile. Each
profile uses asymmetric exponential smoothing, time-based slew limits and a
different number of lower samples required before decay. Balanced defaults to
two lower samples and a slower release, so transient dips do not make the LED
length oscillate. Status and rendered frames both use the filtered values;
temperature values remain unfiltered because they already change slowly.

Frames are always logical left-to-right. The hardware adapter reverses the
physical sysfs path order by default for the official Steam Machine, so UI
previews and the user's physical viewpoint agree without contaminating provider
logic.

## Countdown signals

Parental, free and preview timers keep separate monotonic deadlines. Preview
has deliberate short-lived priority; otherwise Steam Families is authoritative
over the personal timer and appears only while a game is active. The frontend
re-registers Steam's remaining-time callback on each game launch. The callback
is registered only after the backend accepts the new AppID, because
Steam may answer synchronously. Disabling parental display, leaving the game or
switching AppID deletes that session's parental state, including its final alert.
The lit portion occupies the logical left side, so its disappearing edge moves
right-to-left. The shared persisted 0 to 6 physical dark-edge compensation counters
light-guide bloom in Countdown and Performance and defaults to two. Status
exposes uncompensated logical frames plus logical/physical lit counts, while
Renderer receives compensated frames. Countdown full bars remain 17 pixels and
a running timer retains at least one physical pixel. Artwork bypasses the
calibration.
A rendering scale of zero uses the timer's initial duration. Fixed scales from
one to four hours map that remaining window to 17 pixels and clamp longer durations to a
full bar. Preview deliberately ignores the fixed scale.
A brighter highlight circulates right-to-left. Below five minutes the palette
becomes constant pure red; circulation remains the sole animation until the
final eight seconds. Then a three-white-flash pattern repeats until zero before
the arbiter returns immediately to the unchanged base provider.

## Faceplate flow

The JSAUX faceplate is a second, independent display. It does not take part in
light-bar arbitration and never writes `valve-leds`; Light bar glow only reads
them, in the bar's logical order. `FaceplateService`
(`py_modules/signalbar/faceplate`) runs its own worker thread and is the only
component holding the serial port, a CH340 adapter found by USB ID at 1 Mbaud.
It takes an exclusive `flock` on the tty, so the standalone Pixel Faceplate
plugin and GabeCubeAura cannot write to the panel at the same time; whichever
loses reports `busy` and retries. The CH340 is a common chip, so nothing is
sent to a port until it answers the panel's power command; a port that does
not answer is left alone for a minute. Mode Off closes the port.

The panel has no raw-frame command. Every picture is a one-frame GIF stored in
its SPI flash. The service hashes each 64x54 frame, skips identical frames,
waits at least one second between uploads and treats the panel's
already-stored reply as no write. Brightness is lowered before a bright frame
is uploaded, because the panel replays the stored picture at the stored
brightness when it powers on and a white frame at full brightness browns out a
USB-A port. After any reconnect the service assumes the panel may be showing
a bright picture until its own next upload.

Settings live in the main store with a `faceplate_` prefix and are validated
in `faceplate/options.py`, so configuration export and import include them.
They pass through `Engine.update_settings` unused by the light bar. `main.py`
passes the unprefixed view to the service after every change and forwards
`game_changed`. While the mode is not Off it also writes
`faceplate-claim.json` (`faceplate_claim.py`), which tells the standalone
plugin to step aside. The service also reads `/proc` for a running
`SteamLaunch AppId=` as a fallback. Artwork uses `find_library_artwork` and
`find_library_logo` and is decoded by a short-lived `gst-launch-1.0` process,
which reads the image on stdin so no path is ever parsed as pipeline text.

Sleep and shutdown use logind's `PrepareForSleep` and `PrepareForShutdown`
through `gdbus monitor`, with a `systemd-inhibit` delay lock. Both helpers run
only while the faceplate mode is not Off, and both die with the plugin process.

## Runtime diagnostics

Frontend lifecycle milestones are reported to the backend without influencing
provider policy. Debug exposes the game detection source, backend RPC latency,
and elapsed time waiting for Steam's parental callback. Renderer retains the
last successful-write timestamp across relinquish operations. Vanilla Guard
reports cooldown and stable-window time independently, avoiding a misleading
zero cooldown while stability is still pending. Debug is rendered last in the
Decky panel.

## Extending providers

A provider returns `ProviderOutput(name, frame, reason)`. New providers should
collect data at their natural low frequency, never import hardware code, and
leave priority/order to Arbiter. Renderer remains unchanged.
