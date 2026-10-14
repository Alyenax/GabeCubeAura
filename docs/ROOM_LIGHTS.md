# Room lights (prototype)

This puts the game on the lights around your room, not just the bar on the
Steam Machine. It's a proof of concept: it works on my Govee lights, but it
hasn't been tried on many setups yet.

## How it works

Every light you add gets one role:

- **Key art.** A slow ambient ring. The game's artwork palette (the same one
  the Artwork display uses) is spread around all the key-art lights and turns
  one lap every three minutes. It gives the room some movement without pulling
  your eye away from the TV.
- **Screen.** Real time, like an HDMI sync box. Each screen light gets a
  little picture of the screen with cells around the edges (4 across the top
  and bottom, 3 down each side) and the whole picture in the middle. Tap the
  cells that light should show. A light with several cells, like a strip under
  the TV, gets one colour per cell in order and stretches them along its
  length, starting from the lowest end (where Govee puts segment one). If the
  colours run the wrong way, flip "Reverse direction". It uses
  the frames Screen Sync already captures, so nothing new is recorded and
  nothing leaves your network.

Roles mix. What I run at home: two lamps behind the TV on the left and right
edges, a strip under it on the bottom cells, and everything else in the room on
key art.

When no game is running, the lights do what "When no game is running" says:
leave them alone, warm white (colour temperature and brightness are
adjustable, 3000K at 40% to start), or off.

Screen lights keep capture running while a game is open, even if the bar itself
is showing something else (the same way Audio Sync borrows the picture). When
frames stop for 1.5 seconds (game closed, Steam Machine asleep), the lights are
handed back.

Settings live in `room-lights.json` next to GabeCubeAura's other settings,
kept separate on purpose so the feature is easy to pull out or rework.

## Govee

Zero setup beyond one toggle: turn on **LAN Control** for each light in the
Govee app. Then Settings > Room lights > Scan. GabeCubeAura asks on the
standard Govee multicast address (239.255.255.250:4001) and lights answer on
port 4002. No account, no cloud, no API key.

Lights are saved by their Govee device ID, not their IP. GabeCubeAura rescans
quietly at startup, when Room lights is switched on, and every time a game
starts, and follows any light the router has moved. Lights typed in by IP can't
be tracked that way.

Real-time colour uses Govee's "razer" LAN command, the one their HDMI sync box
uses. I tried the per-segment command the Govee app uses first, but it writes
settings the light keeps, and after a few hours at 10+ updates a second my strip
dropped off LAN Control twice. Razer frames aren't stored. Key-art lights only
change about once a second, so they use the plain colour command.

If your lights are on a different network or VLAN than the Steam Machine, the
multicast scan won't reach them. Type a light's IP into the box on that page
and it's added directly.

Tested on: H1630 lantern, from the plugin on a Steam Machine (discovery, screen
zones, key art, idle). The same razer stream runs
my H6022 floor lamps and H61F2 strip at home through a different app.

Only one app can capture the screen at a time. If another plugin is already
capturing Gamescope, Screen Sync (and so the screen lights) waits until it
stops.

## Hue

`py_modules/signalbar/room_lights/hue.py` is a sketch written from Philips'
docs. **It is untested** (I don't have a Hue bridge anymore) and nothing calls
it yet. The short version: pairing is a link-button press on the bridge, the
Entertainment areas people already set up in the Hue app can be read over the
local API with each light's position, and streaming is DTLS to the bridge. That
last part needs a DTLS library Python doesn't ship with, which is where the
sketch stops. Details are in the file.
