# Home Assistant

GabeCubeAura publishes the Steam Machine to an MQTT broker, and Home
Assistant's MQTT integration picks it up through discovery. The short setup is
in the [README](../README.md#home-assistant). This page covers the other
broker setups, every **Status** message, what Home Assistant receives, what
each tier allows, automations and privacy. None of it is needed to use
GabeCubeAura; MQTT stays off until you turn it on.

## The Mosquitto broker app

The app needs Home Assistant OS or Supervised. On Container or Core,
**Settings > Apps** shows "What is an app?" instead of **Install app**; see
[Your own broker](#your-own-broker). After **Start**, also turn on
**Watchdog** on the app's **Info** tab so the broker restarts if it stops;
**Start on boot** is on already.

Every client of the app needs a username and password; it has no anonymous
logins. A Home Assistant user works as a broker login straight away, with no
restart. If GabeCubeAura tried to connect before the user existed, the app may
refuse it for about five minutes; restarting the app clears that.

The app listens on port 1883. It offers TLS on 8883 only once certificates are
set up in its configuration.

## A broker you already use

GabeCubeAura must use the same broker as Home Assistant, or its device never
appears. To see which broker that is, open **Settings > Connectivity > MQTT**
and select **Connection**, or open **Settings > Devices & services > MQTT**
and choose **Reconfigure** from the entry's menu. **Broker** and **Port** are
shown; the password is always hidden. Close the dialog without selecting
**Submit** to leave everything unchanged.

- `core-mosquitto` is the Mosquitto broker app. Use Home Assistant's IP
  address and a Home Assistant user, as in the README.
- `mosquitto`, `localhost` or another name that only your server knows will
  not work from the Steam Machine. Use the IP address of the machine the
  broker runs on.
- Zigbee2MQTT keeps the same details under `mqtt` in its **Configuration**
  tab (or `configuration.yaml`) as `server`, `user` and `password`.

Give GabeCubeAura a login of its own rather than sharing Zigbee2MQTT's or Home
Assistant's. On your own Mosquitto, add it with `mosquitto_passwd` and restart
the broker. If the broker allows anonymous connections, leave **Username** and
**Password** empty; **Status** then reads "Connected as anonymous". If it uses
an ACL file, let the login read and write `gabecubeaura/#` and
`homeassistant/#` (or your discovery prefix).

## Your own broker

Home Assistant Container and Core have no apps, so the broker runs separately:

1. Install Mosquitto on a machine that stays on, for example with the
   `eclipse-mosquitto` Docker image and port 1883 published.
2. Mosquitto 2 accepts only local connections until its configuration has a
   `listener 1883` line. Add that line and a `password_file`.
3. Create a login for GabeCubeAura, and one for Home Assistant, with
   [`mosquitto_passwd`](https://mosquitto.org/man/mosquitto_passwd-1.html),
   then restart Mosquitto.
4. In Home Assistant, go to **Settings > Devices & services**, select **Add
   integration**, choose **MQTT** and enter the broker's address, port and
   Home Assistant's login.
5. On the Steam Machine, follow the README steps with the IP address of the
   machine running Mosquitto and GabeCubeAura's login.

## Broker host and network

Type an IP address in **Broker host**, with no `http://` or `mqtt://` and no
port; the port goes in **Port**. Port 8123 is Home Assistant's web page, and
MQTT uses 1883. `homeassistant.local` often works too, but it depends on
your network passing that name around, and an IP address does not. A DHCP
reservation on your router keeps that address from changing.

The Steam Machine connects straight to the broker, so it must be able to reach
it. Guest Wi-Fi, a separate VLAN or a firewall on the broker's machine can
block port 1883. Home Assistant Cloud does not carry MQTT. A broker on another
network, such as one reached over Tailscale, works with the address it has
there.

## TLS

**Use TLS** saves as soon as it is switched. It checks the broker's
certificate against the Steam Machine's system certificates and the name in
**Broker host**, and never skips that check. It therefore works only with a
certificate from a public authority, such as Let's Encrypt, for the name you
type, usually on port 8883. Self-signed certificates and those from your own
certificate authority fail, and so does an IP address when the certificate
names a host. On a home network, leave it off.

## If it does not connect

**Status** shows "Connecting to" the host and port, then "Connected as" the
user and "publishing under" the topic root, with a count of messages sent.
After a failure it shows the reason and counts down to the next attempt.

- "Off": **Connect to Home Assistant** is off, or no broker host was saved.
  Press **Save connection**, then turn it on. Changes to the fields also need
  **Save connection**; the switch alone keeps the saved values.
- "Not authorised (check the username and password)" or "Wrong username or
  password": retype both and press **Save connection**. With the Mosquitto
  broker app, check the user under **Settings > People > Users** and see
  [the app's notes](#the-mosquitto-broker-app).
- "Nothing listening at" the host and port: the machine answered but no broker
  is on that port. Check that the broker is started and the port is 1883.
- "Broker not reachable (timed out)": a wrong IP address, or a network that
  cannot reach the broker (see
  [Broker host and network](#broker-host-and-network)).
- "Broker name not found": the Steam Machine cannot resolve that name. Use an
  IP address.
- "TLS mismatch: check the port and the TLS switch": **Use TLS** is on against
  a plain MQTT port. Turn it off, or use the broker's TLS port.
- "TLS failed:" followed by a reason, or "Broker did not finish the TLS
  handshake (timed out)": see [TLS](#tls).
- "Broker closed the connection", "Broker did not answer (timed out)" or
  "Broker stopped answering": often **Use TLS** off against a TLS port.
  Otherwise check the broker's log.
- "Broker sent something that is not MQTT": the port belongs to something
  else, such as Home Assistant's web page on 8123.
- "Bad protocol version", "Broker rejected the client ID", "Broker
  unavailable" or "Network error": check the broker's log.

A bad value is refused when you press **Save connection**, and the **Error**
row says why, for example "host must be a hostname or IP address (IPv6 without
brackets)" for a URL.

Connected but no device in Home Assistant? GabeCubeAura and Home Assistant are
on different brokers, or the discovery prefix differs. Compare **Broker host**
with the broker in Home Assistant's **Connection** screen, and **Discovery
prefix** with **MQTT options** under **Settings > Connectivity > MQTT**, where
**Enable discovery** must also be on.

## What Home Assistant receives

The device shows the current game, whether a game is running and the session
length; the light bar's owner, display and brightness; night mode, recording,
the screensaver and Steam downloads; controllers and their batteries; the
playtime remaining; CPU and GPU load and temperature; thermal protection;
weather; updates; and diagnostics (Decky frontend, Last command error and
Status).

Current game reads "Not playing" when no game runs. A game that stops is
reported 30 seconds later, because waking from sleep and some mod launchers
stop a game for a moment. If the same game comes back within those 30
seconds, nothing is sent: the session, its start time and its length carry
on. A different game replaces it at once.

Session length counts only the time the Steam Machine is awake: sleep pauses
a session, so a game left running overnight and played again in the morning
shows the minutes actually played, while its start time stays when the
session began. If Decky restarts while the same game is still running, the
session carries on from where it was.

Key art is the game's Library Hero, including custom artwork set for a game or
non-Steam shortcut. A shortcut with no hero uses its custom header or cover
instead. Header art, Cover art and Logo images come from Steam's local library
cache or your custom grid art. Each image is JPEG, PNG or WebP up to 2 MB and
is sent once per game. Header art, Cover art and Logo stay empty when the game
has none of that kind. While no game runs the four images are unavailable, and
the same game coming back sends nothing again. For Steam games, the game's
attributes also carry Steam's own addresses for all four.

A value that does not apply makes its entity unavailable instead of showing
something made up: Playtime remaining while no countdown runs, Light bar
brightness while Steam has the light bar, Weather until weather is set up and
has a reading, and Update until the updater reports. Last command error reads
"No error" when there is none. Weather, Update and Light bar display read as
words, such as "Partly cloudy", "Up to date" and "Home Assistant". Their
codes, such as `breaks` and `up_to_date`, stay in the entities' attributes for
automations.

Home Assistant records every state change, so GabeCubeAura limits what it
sends and `configuration.yaml` never needs editing:

- CPU and GPU load and temperature when they move by 5 points or 2°C, at most
  every 30 seconds, each on its own, so one moving reading does not resend
  the other three;
- countdowns in whole minutes, at most once a minute;
- session length in 5-minute steps;
- game start, thermal protection and the start and end of a countdown at
  once, and a game stop after 30 seconds;
- everything else as it changes, at most once a second.

After a lost connection or a Home Assistant restart, GabeCubeAura sends fresh
values before the device shows as available again, and events after it, so
Home Assistant does not show the values from before for a moment. Right after
GabeCubeAura itself starts, CPU load needs a few seconds for its first
reading, so the four performance sensors can follow up to 10 seconds later.

Some changes only say something once they last:

- a new light bar owner is an `owner_changed` event after 10 seconds, so a
  notification shown over Steam's bar for a moment is not;
- a newly connected controller shows no battery reading until Steam reports
  one, instead of the 100% Steam lists first, for up to a minute;
- while the Decky frontend restarts, Controllers keeps its last value and a
  controller it already knew is not reported as connected again.

**Turbo mode**, at the bottom of **What Home Assistant can do**, sends every
change, up to once a second. Only turn it on if you need it and have set up
Home Assistant's recorder for these sensors.

The rest of GabeCubeAura's status, debug details included, goes to an MQTT
topic that no entity records, at most once a minute (every second in Turbo
mode). It is capped at 400 keys and text of 256 characters. Lists longer
than eight items are left out, and so are fast-changing values such as
timers, counters and live audio and colour meters.

## What Home Assistant can do

**What Home Assistant can do** appears once GabeCubeAura has connected with the
saved connection settings, and hides while a new connection is being made. The
line under its **Light bar** dropdown says what the choice does. Each tier
adds to the one before it.

- **Watch only**: Home Assistant sees everything and changes nothing. It has no
  controls, and a broker that never had them hears nothing about them.
- **Help out** (default): Home Assistant can change settings and has a **Light
  bar** light and three alert buttons. GabeCubeAura's own events and signals
  still win.
- **Take the lead**: Home Assistant's light and alerts beat everything except
  urgent warnings. GabeCubeAura's displays come back whenever Home Assistant
  is quiet. While Home Assistant shows something, GabeCubeAura skips
  notifications, achievements, screenshots, recording cues, controller alerts
  other than low battery and the game launch animation.
- **In control**: only Home Assistant and urgent warnings use the bar, and
  those one-off flashes are always skipped. Screen Sync and Audio Sync stop
  capturing. When Home Assistant is quiet, Steam has the bar.
- **Full control**: Home Assistant also takes the urgent warnings, and
  GabeCubeAura asks before switching to it. It already receives the
  temperatures, thermal protection, countdowns and controller batteries to
  script its own warnings. The Steam Machine still throttles itself when it
  runs hot, but the bar no longer warns you.

Steam's own animations, such as downloads, come first at every tier, and Home
Assistant's colour comes back as soon as they end. Below Full control, urgent
warnings come first too: Steam's other light bar indicators, thermal
protection handing the bar to Steam's overheating warning, a controller at or
below the low battery threshold and the last five minutes of a playtime
countdown. A Home Assistant alert can briefly play over a bar Steam has taken,
as GabeCubeAura's own short events can, but never over those indicators.

### When Home Assistant is unreachable

Unreachable means no connection to the broker, or Home Assistant saying it went
offline, for 30 seconds in a row, so a short restart does not change the bar.

From Take the lead up, **When Home Assistant is unreachable, let GabeCubeAura
take over** decides what happens then. With it on, the default, the bar works
as it does at Help out until Home Assistant is back, and the line under the
dropdown says GabeCubeAura has taken over, beside "Reconnecting…" if the
broker is down. With it off, the bar keeps whatever Home Assistant last sent.
If Home Assistant sent nothing, Take the lead carries on with GabeCubeAura's
displays and the tiers above it leave the bar with Steam. Choosing Full
control turns the switch off in the same save; you can turn it back on.

At Help out, the same 30 seconds turn Home Assistant's light off and bring
your display back. Once Home Assistant is back, it can turn the light on again.

### Settings

From Help out up, the device has a switch, list or number for each setting
GabeCubeAura can fully check: the display preset, Home and in-game displays,
brightness, Audio Sync, Screen Sync, Customization+, artwork, Light Events,
controller alerts, countdown and weather looks. A change goes through the same
checks as the settings page and applies after about a second. Rapid changes,
such as a dragged slider, collapse to the latest value, and a value that is
already set changes nothing. As on the Steam Machine, changing a setting that a
display preset controls switches GabeCubeAura to the Custom preset.

Only the Steam Machine can change updates, the playtime countdown, Valve
ownership, StripMine and TW3 SteamRGB integration, guided setup and **Home
Assistant alerts**, although their values are still published. The tiers and
the connection are set only on the Steam Machine too. The weather city is
never sent or controllable.

When Home Assistant asks for something GabeCubeAura cannot do, such as a
Weather display without a city, the Last command error sensor says why, and
the Steam Machine page shows the same text as **Last refused change**. Both
clear when that change next succeeds from Home Assistant.

### The light

At Help out, turning the **Light bar** light on selects the **Home Assistant**
display for whatever is on screen, Home or in-game, and shows the colour and
brightness Home Assistant sends. This switches GabeCubeAura to the Custom
preset once. Turning the light off, choosing Watch only or turning off
**Connect to Home Assistant** gives the bar back and restores your previous
display, and choosing a higher tier restores it too. If GabeCubeAura restarts
while the light is on, your previous display is restored at the next start.
A game with its own display keeps it unless you choose Home Assistant for that
game.

From Take the lead up, the light shows over whatever display is selected and
never changes a setting. Night brightness dims Home Assistant colours like
everything else.

### Alerts

The three buttons, Alert: flash, Alert: pulse and Alert: sweep, play a short
white alert. At Help out, Home Assistant alerts take their turn in the same
queue as Steam notifications. From Take the lead up they go ahead of
GabeCubeAura's own events. They need Light Events and the **Home Assistant
alerts** switch, which is on by default. An alert less than 0.8 seconds
after the previous one is dropped.

New colours, frames and alerts are refused during thermal protection, a
display preset preview or an update install, or while GabeCubeAura is switched
off. At Full control only an update install or GabeCubeAura being switched off
refuses them. Turning the light off always works.

## Automations

Each area has an event entity, and these events arrive as they happen:

- Game events: `started`, `stopped` (30 seconds after the game stops, as
  above)
- Light events: `notification`, `achievement`, `screenshot`, `record-start`,
  `record-stop`, `ha` (a Home Assistant alert)
- Controllers events: `connected`, `disconnected`, `charging`
- Steam events: `download_started`, `download_finished`
- Thermal events: `tripped`, `recovered`
- Light bar events: `owner_changed`
- Countdown events: `started`, `ended`

Only the kind of event is sent, never the text of a notification or
achievement. Events queued for more than 60 seconds, while the broker was
unreachable or the Steam Machine slept, are dropped rather than replayed.

From Help out up, automations can also publish to two topics under the topic
root shown on the **Status** line:

- `<topic root>/drive/frame`: a JSON list of 17 `[r, g, b]` values, each
  0-255, left to right.
- `<topic root>/drive/alert`: for example
  `{"variant": "pulse", "color": {"r": 255, "g": 80, "b": 0}, "duration": 2}`.
  The variant is `flash`, `pulse` or `sweep`. The colour defaults to white and
  the duration, 0.5 to 4.85 seconds, to the variant's own length.

Retained and empty messages on these topics are ignored, and colours and frames
apply at most four times a second.

## Privacy

MQTT is off until you turn on **Connect to Home Assistant**, and GabeCubeAura
connects only to the broker you enter. The password is kept in its own file,
is never shown and is never included in a configuration export. Your weather
location, update tokens, the Private Lab account and its release notes, and
private fields are never sent. File paths are removed from known path fields
and error text.
