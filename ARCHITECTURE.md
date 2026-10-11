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

## Home Assistant bridge

`signalbar/mqtt` publishes GabeCubeAura to an MQTT broker with Home Assistant
discovery. `main.py` starts it last and stops it first. `client.py` is a small
MQTT 3.1.1 client with QoS 0, keepalive, a last will and reconnection with
backoff; it never closes its socket from another thread. `config.py` keeps the
connection settings and password in an owner-only file in the runtime
directory, outside the settings store, so export, import and reset never touch
it.

`bridge.py` reads `Engine.status()` and the update status once a second into
areas built by `snapshot.py`. Private fields are redacted by key name fragment
at any depth, which covers paths, coordinates, tokens and error output. Free
text whose key ends in `error`, `reason`, `detail` or `message` is still sent,
with every file or device path in it replaced by `<path>`; URLs are left alone.
`release_notes` is left out on the Private Lab channel.

`policy.py` then decides which changed areas to publish, because Home
Assistant's recorder stores every state change and every distinct attribute
blob. By default it sends:

- performance when a load moves 5 points or a temperature 2°C from the last
  value sent, at most every 30 seconds. Each reading has its own deadband:
  one that has not moved keeps the value last sent, so only the sensors that
  moved record a row. A reading that goes missing keeps its last value for
  up to 60 s (not across a sleep), after which the sensor is unavailable;
- the countdown in whole minutes, rounded up, at most every 60 seconds;
- session length in 5-minute steps, counted on the monotonic clock, which
  stops during suspend, so sleep pauses a session. `session.py` records the
  appid, wall start, awake seconds and boot ID in `session.json` beside
  `mqtt.json` (atomically under one lock, at most once a minute and at bridge
  stop, or as no game while a stop is held); the first game a new bridge
  reports carries on from it if the appid matches, the record is under 10
  minutes old and from the same boot, else starts from 0;
- the flattened `status` area at most every 60 seconds;
- every other area on change, at most once a second.

Thermal protection, countdown start, end, source and label, and game start,
stop and title bypass those limits. A game stop is reported only after
`GAME_STOP_HOLD_S` = 30 s, together with its held `stopped` event; if the same
appid returns within the hold, the session carries on and both events are
dropped. The game, its stop hold and its session are followed every second
whether or not the broker is connected; only publishing waits for it.
Throttling at the source keeps measurement
sensors recorded, since excluding them would lose long-term statistics. No
entity uses `force_update`, so an unchanged value costs nothing. Areas that
entities take as attributes carry no counters or timestamps, because each
distinct attribute blob is stored; a test guards this. The update check time,
and a faceplate upload counter if a faceplate service exists, go only to
`status`. That area is an MQTT-only topic that no entity takes as attributes;
the Status sensor has its own small `info` area with the version, enabled flag
and frontend connection.

The `turbo` setting is read on every step and applied without reconnecting. It
publishes every changed area once a second, with minutes to 0.1. A full
republish, and a Turbo switch in either direction, resets the policy and sends
everything at once.

`main.py` also passes a faceplate status getter. This build has no `faceplate`
service, so the getter returns `None`, the `faceplate` area reports
`available: false` and discovery leaves the Faceplate sensor out rather than
creating a permanently unavailable entity. In a build where the getter returns
status, the bridge publishes the sensor's discovery config once, before its
first state.

Engine facts reach the bridge through `signalbar/hub.py`. Engine methods call
`hub.emit("<area>.<event>", data)` for game, light event, controller and
download facts. The hub fans them out on its own thread and drops the oldest
when a subscriber falls behind. A new emit kind becomes a Home Assistant event
type automatically. Hub events are redacted the same way, and events older
than 60 seconds, queued while the broker was unreachable or the machine slept,
are dropped rather than replayed, and so is every event from before a sleep
once it ends. An event that does not go out waits for the next step until it
ages. Thermal, ownership and countdown transitions
are derived from snapshots; an ownership change is an event only once it has
lasted `OWNER_SETTLE_S` = 10 s, so notification overlays on Valve's bar fire
nothing. Light bar attributes leave out the overlay `provider`, and Current
game's `json_attributes_template` leaves out `session_minutes`.

Controllers are settled in the bridge too. A newly listed controller at 100%,
Steam's placeholder, is sent with no percent until the reading changes or
`PLACEHOLDER_HOLD_S` = 60 s pass, and `connected` events never carry that
100%. While the frontend is away the area is not sent, and for
`ROSTER_SETTLE_S` = 10 s after it returns an empty roster is not either. A
`connected` event for a controller listed more than 10 s earlier, without a
`disconnected` since, is a roster that lapsed and is dropped. Once the
frontend has been back for 10 s, a controller missing from the roster is
forgotten, so its next `connected` is published. A held roster keeps what the
bridge knew about each controller. A reconnect and Home Assistant's birth
message both trigger a full republish. It sends the retained state areas, the
frontend flag, the settings and the light state first, then `availability`
`online`, then every event, hub and derived alike, so Home Assistant does not
make the entities available with the values the broker kept from before the
outage. A republish that fails part way runs again. Before the bridge first
comes online after a start, availability also waits up to 10 s for a CPU load
reading, which needs two samples, so the last run's readings never show as
current; later reconnects do not wait.

The stop hold is decided from the game state. When the state shows the same
appid back before the hub delivers its `started`, the held `stopped` is dropped
and that `started` is dropped when it arrives. A settings save (`reconfigure`,
which is also how MQTT is turned off) restarts the bridge and keeps the held
stop and the controllers it knew. A final stop, when Decky stops, publishes a
held stop's game state and event before going offline. A held stop older than
`EVENT_MAX_AGE_S` plus the hold is dropped like a queued event.

A Decky restart starts a new engine that has no game until the frontend's
first `game_synced` (its `game_sync_ms` leaves `None`), and whose startup
settle can take the bar and give it back for 10 s or more. For up to
`COLD_START_S` = 30 s after the bridge is created, the game area waits for that
sync (or a reported game, and with a recorded session that resumes, for its
game), and the `light_bar` area is not published at all, so Home Assistant
keeps the broker's values. Home Assistant's own light ends the light bar hold.
After it, the owner from before the restart is the baseline for
`owner_changed`. The frontend flag, which 14 entities take as availability,
goes online at once and offline only after `FRONTEND_GRACE_S` = 30 s without a
heartbeat. All of this applies only on the same boot: `published.json`, beside
`session.json`, records the boot ID with the image content types and the
settled owner, and after a reboot, or with no record, the truth goes out at
once and the frontend flag is off until the first heartbeat. The content
types it keeps make a restart with the same game send the same discovery.

The bridge is not told about a suspend: Home Assistant shows the old state
until the broker's keepalive gives up and sends the last will, about 45 s
later. A step whose wall clock ran more than `SUSPEND_JUMP_S` = 20 s ahead of
the monotonic one is a wake: it makes a new connection and a full republish
at once, as the old socket may be dead without knowing it.

Key art is the hero image with the light bar's fallbacks, published as JPEG,
PNG or WebP from Steam's local artwork, at most 2 MB. Header, capsule and logo
images come from `steam.find_game_art`, which looks for one kind only (custom
grid art first, then both library cache layouts), skips any file over 2 MB and
never substitutes another kind. Each is sent once per game and run, not again
on a reconnect (a bridge restart, such as a settings save that reconfigures
it, sends them again), looked up again after 30 s when missing, and declares its
content type first. When the game stops nothing is sent: an availability
entry on the `game` area makes the image entities unavailable while no game
runs. Their entities are Header art, Cover art and Logo. There is no icon,
because the current library cache names it by a content hash.

Values that do not apply use the same kind of entry on their own state topic,
so Home Assistant shows them as unavailable: Playtime remaining without a
countdown, Light bar brightness while Valve owns the bar, a CPU or GPU reading
that is missing, Faceplate once its service is gone, and Weather without a
reading. A game title is cut to 255 characters, Home Assistant's limit.

Every field of the engine's and the updater's status reaches Home Assistant
unless `snapshot.py` excludes it as private (`is_redacted`), noisy (17-pixel
arrays, audio meters) or volatile (timers, counters, rates), or
`UPDATE_NOT_PUBLISHED` names it. Values are capped at `STATUS_KEY_LIMIT` = 400
keys, lists of at most 8 small items and strings of 256 characters. Engine
fields, debug section included, go to the `status` area. Updater fields go to
the Update sensor's attributes, with their timestamps in `status`, and
controllers keep every field. A test fails when a status field is neither
published nor listed as excluded.

The settings page's connection line comes from `bridge.status()`: `phase`
(`off`, `connecting`, `connected`, `waiting_retry`), `reason` and `retry_in_s`,
with the broker, username and topic root but never the password. `reason` is
the client's `describe_error` of the last failure: CONNACK codes 1-5, refused,
timed out, DNS, a TLS mismatch, a TLS handshake that timed out, or another TLS
failure. A mismatch is TLS switched on against a plain MQTT port. The reverse
reads "Broker closed the connection" or a timeout, since OpenSSL never sees it.
`retry_in_s` is the client's backoff, and the page counts it down each second
between polls.

## Home Assistant settings control

Each device has a tier in `mqtt.json` (`config.DEVICE_TIERS`):
`light_bar_tier` is 1 to 5 and `faceplate_tier` 1 or 2, beside the
`ha_fallback` switch. They are set only on the Steam Machine and applied
without reconnecting. A file from before tiers holds `light_bar_level` and
`faceplate_level`: `report` reads as 1, `settings` and `drive` as 2, and the
next save drops the old keys. A missing or unreadable tier is 2, and a tier
the device does not offer yet becomes its highest.

`schema.py` builds the controllable settings from the settings store. Bool keys
become switches. Keys with a `VALID_*` set, or an `EVENT_VARIANTS` or
`CONTROLLER_VARIANTS` entry, become selects with exactly those options,
narrowed by `OPTION_FILTERS` if the store ever accepts values the settings page
does not offer; a test checks every option against `src/`. Numbers come only
from an override table whose ranges a test proves against `store._validate`.

The settings store, rather than the bridge, decides what only the Steam Machine
itself may change. `LOCAL_ONLY_SETTINGS` in `settings/store.py` holds updates,
the parental countdown, Valve ownership policy and guard timing, StripMine and
TW3 SteamRGB integration, and onboarding. These are reported in
`state/settings` but never controllable at any tier, and a store test fails
when a new `updates_`, `stripmine_` or `tw3_` key is missing from the list. A
short deny list in `schema.py` covers the weather location, file paths,
profiles, undo state, legacy and derived fields, and anything private by name;
those keys are neither controllable nor reported. A test fails when a new
settings key is not classified.

From tier 2 the bridge publishes a switch, select or number per control, and
one retained `state/settings` JSON with their values and the local-only ones,
only when it changes. A device without controls in this build publishes nothing
at any tier. The retained display preset note goes out only when controls
appear where none were described: on connect, after a Home Assistant restart,
or when a tier leaves Watch only. Moving between tiers 2 to 5 sends nothing
again. Every retained settings topic is first recorded in `advertised.json`
next to `mqtt.json`. Only topic names are stored, and only topics shaped like
the bridge's own are ever loaded. When a tier goes back to Watch only, or a
start finds recorded topics the current tiers do not want, the bridge clears
only those with empty retained payloads, so Home Assistant deletes the
entities, and forgets each topic once its clear is sent. In that pass the
entity configs go first and the empty state and preset note after them. The
other way round, Home Assistant would render the entities against an empty
state. With nothing recorded it sends nothing, and a clear cut short by a
dropped connection finishes on the next connect.

Commands arrive on `<root>/set/<key>`. Retained ones are ignored. Unknown keys,
local-only keys, keys of a device at Watch only and malformed values are
refused on the client thread, with the reason in `state/bridge` `last_error`
(the Last command error sensor) and one log warning per new reason. Coalescing
is a throttle: a change is applied after about a second, and rapid changes to
one setting collapse to the latest.

The worker then reads the settings, refusing the command if it cannot, and
drops a value equal to the stored one, because the store treats any write of a
display-preset key as an edit and switches to Custom. Otherwise it calls
`main.py`'s `_apply_setting_from_home_assistant`, which runs the UI's own
`set_setting` on Decky's loop and waits at most 2 s. That is shorter than the
bridge's 3 s stop join, which keeps an unload from deadlocking. A timed-out
call that has not run yet is cancelled; one that ran just before the cancel
still counts. The worker reads the value back and reports it when the store
kept something else. When the refused setting itself later applies as sent,
`last_error` clears, and so does the settings page's Last refused change row.
During unload the loop reference is dropped before the bridge stops, and any
Home Assistant change still on its way fails at once. A command still waiting
when the bridge stops or restarts is dropped.

## Home Assistant light and alerts

The light bar's tiers 2 to 5 also have a JSON-schema light, three alert buttons
and the light's retained `state/drive`, all recorded in `advertised.json` and
cleared like the setting entities. Commands arrive on
`<root>/drive/light|frame|alert`, never on `set/`. `drive.py` checks them on
the client thread. Retained commands are ignored and logged; empty ones, which
is how a retained topic is cleared, are ignored silently. A refusal stays in
`last_error` until that same command (`drive/light`, `drive/frame` or
`drive/alert`) later applies, and turning the light off counts for
`drive/light`.

The worker applies the newest light or frame at most every 0.25 s to
`providers/home_assistant.py`, a lock-guarded slot the engine reads while the
`home_assistant` display is routed, and at any display from tier 3. An empty
slot hands the bar back; it never falls through to another display. At tier 2,
turning the light on first selects that display for the current context
through `set_setting` on Decky's loop, only when it is not already selected.
The preset only flips when the display really changes.
Turning it off, or leaving tier 2, puts back the display it replaced wherever
that is still `home_assistant`.

Alerts are the `ha` kind in `EventProvider`, with their own colour and a length
of at most 4.85 s. They share the Steam event queue, the StripMine `event:`
lease and every cancellation path, but keep their own 0.8 s repeat rule across
any two Home Assistant alerts, apart from Steam's. At most three wait in the
bridge. `ha_alerts_enabled` (local only) and Light Events gate them, and each
result is a `light_event` of kind `ha` with `result` shown or dropped. The
engine's `home_assistant_refusal()` and the update phase refuse new content
during thermal protection, with the light bar off, during a preset preview or
while an update installs; off always applies. At tier 5 only the light bar
being off and an update refuse.

The display the light replaced is recorded per key in `routed.json` next to
`mqtt.json` before the write. The record is forgotten if the write fails,
except on a timeout: that write may still have landed, and keeping the record
is harmless because a display is only put back where the store still says
`home_assistant`. A newer route for the same key replaces the record, because
routing records whatever is selected at that moment. A record is cleared only
once its display is dealt with: put back, changed meanwhile, or refused by the
store. A restore cut
short by an unload, or one that failed for another reason, keeps the record.
After a Decky restart, update or reboot, `main.py` puts it back at the next
start, on Decky's loop before the bridge starts, wherever the store still says
`home_assistant`, and leaves a display changed meanwhile alone. If the settings
cannot be read, every record is kept for the next start. A failed put-back logs
one warning and becomes the first Last command error. When the store refused
it, the display stays and the record is cleared; any other failure keeps the
record, so the next start tries again.

Stopping the bridge (MQTT turned off, any reconfigure, an unload) empties the
slot and puts back the displays the light replaced. At unload `main.py` has
already let go of Decky's loop, so that put-back raises RuntimeError and the
record stays for the next start. A worker still running after `stop()` began
never attaches the slot again and applies nothing more, and a detached slot
ignores whatever reaches it.

## Home Assistant tiers

The tier decides who wins the light bar when Home Assistant and GabeCubeAura
both want it. The bridge works out the effective tier on every step and hands
it to `Engine.set_home_assistant_tier()`; Watch only, or stopping the bridge,
hands it 1. A worker that outlived `stop()` hands nothing, so a stopped bridge
always leaves the engine at 1. The engine starts at 1, so without MQTT nothing
changes.

`Arbiter.choose()` keeps its order at tiers 1 and 2, where the Home Assistant
display is one display among GabeCubeAura's and its alerts share the event
queue. From tier 3 `_home_assistant_first()` runs before anything except Light
bar control being off. Steam priority, downloads included, goes first at all
three, so Home Assistant's light waits until Steam's animation ends.
Below tier 5 next come a `controller:low` alert and then Home Assistant's alert
(`event:ha`), unless a countdown is in its last five minutes. Like
GabeCubeAura's own short events, that alert can briefly play over a bar Valve
owns. After that a bar Valve owns stays with Valve, then the critical countdown
shows, then Home Assistant's light or frame. At tier 5 only Steam priority,
the alert and then the light or frame count. At tier 3 a quiet Home Assistant
falls through to the usual order. At 4 and 5 it returns `none`, and the
existing relinquish path gives the bar to Steam.

The engine passes the slot at every display from tier 3. GabeCubeAura's flashes
are skipped at tiers 4 and 5, and at tier 3 while the light or a frame is on or
a Home Assistant alert is playing or queued. Then `trigger_event` refuses the
Steam kinds, and each tick cancels any already playing, and controller alerts
other than low battery. The launch animation is not shown. Recording state
still follows Steam. From tier 4 Screen Sync and Audio Sync stop capturing. At
tier 5 thermal protection still latches and is reported but no longer suspends
the loop, the countdown no longer counts as critical, a controller running low
no longer cuts a Home Assistant alert short, and any other Valve write is
taken back the way the protected ownership modes do it. Steam priority is
kept: while it is set nothing is forced, so a download's animation plays
without GabeCubeAura writing over it every tick.

Routing happens only at tier 2. Above it the light wins by priority, so
`home_display` and `game_display` are never written and the preset never flips.
Leaving tier 2 for a higher one puts the replaced display back first; coming
down to 2 routes on the next light or frame command. Only an effective tier 2
offers the Home Assistant display (`status.home_assistant.offered`).

Tiers 3 to 5 fall back to 2 when `ha_fallback` is on and Home Assistant has
been unreachable for `FALLBACK_AFTER_S` (30 s). Unreachable means no broker
connection, or `<discovery prefix>/status` saying `offline` since the bridge
last connected. That status is not retained, so a new connection starts as
reachable. The chosen tier returns on the first step that finds Home Assistant
again. Falling back writes no settings and routes nothing. At a chosen tier 2
the same outage empties the slot and puts back a routed display through the
light-off path, once per outage. `bridge.status()` reports the effective `tier`
and `falling_back`. While it falls back, the line under the page's dropdown
says GabeCubeAura has taken over, beside "Reconnecting…" when the broker is
down. Choosing tier 5 there asks first and turns `ha_fallback` off in the same
save if it was on.

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
