# Smart lighting (prototype)

This puts the game on the lights around your room, not just the bar on the
Steam Machine. It's a proof of concept, and two halves of it are in very
different states:

- **Govee: works.** This is the flow I built for my own setup and have been
  running on my lights for weeks, moved into GabeCubeAura and tested on my
  hardware from the plugin.
- **Everything else is a skeleton.** The driver interface, the Hue stub and
  the notes on other brands are me taking that code and building out what
  should work for other lights. I just don't have the hardware to test them.

## How it works

Every light you add gets one role:

- **Key art.** A slow ambient ring. The game's artwork palette (the same one
  the Artwork display uses) is spread around all the key-art lights and turns
  one lap every three minutes. It gives the room some movement without pulling
  your eye away from the TV.
- **Screen.** Real time, like an HDMI sync box. Each screen light gets a
  little picture of the screen with cells around the edges (4 across the top
  and bottom, 3 down each side) and the whole picture in the middle. Tap the
  cells that light should show, corners included. A light with several cells, like a strip under
  the TV, gets one colour per cell in order and stretches them along its
  length, starting from the lowest end (where Govee puts segment one). If the
  colours run the wrong way, flip "Reverse direction". It uses
  the frames Screen Sync already captures, so nothing new is recorded and
  nothing leaves your network.

Brands mix too. The "Which smart lights do you have?" toggles aren't a pick
one: every light lands in the same list with its own role, whatever made it.
Once Hue is finished, Govee lamps on key art and a Hue Entertainment area on
the screen zones can run side by side.

One caveat for the fast stuff: try to keep the screen lights on one brand.
Govee gets a UDP packet straight from the Steam Machine, while Hue goes
through its bridge with its own pacing, so the two will land at slightly
different times. On key art nobody will notice; on lights flanking the TV
reacting to an explosion, you might.

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

Settings > Smart lighting: turn it on, tick the brands you have, set up the
lights, then pick how bright they run and what they do when no game is running.
In the code it's `room_lights`.

Settings live in `room-lights.json` next to GabeCubeAura's other settings,
kept separate on purpose so the feature is easy to pull out or rework.

## Govee

Zero setup beyond one toggle: turn on **LAN Control** for each light in the
Govee app. Then tick Govee under "Which smart lights do you have?" and scan. Saved
lights are always listed; opening the page also rescans quietly for new ones.
Each light has an Identify button that blinks it (and puts it back how it
was), since nobody knows which IP is which lamp. GabeCubeAura asks on the
standard Govee multicast address (239.255.255.250:4001) and lights answer on
port 4002. No account, no cloud, no API key.

Lights are saved by their Govee device ID, not their IP. GabeCubeAura rescans
quietly at startup, when Smart lighting is switched on, and every time a game
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

Lamps and strips with several colour zones don't need setting up per model:
each picked cell is one colour, and the light's own firmware spreads them
across however many zones it has. A plain bulb looks best with one cell.

## Other Wi-Fi bulbs

There's no common protocol for "Wi-Fi RGB bulb". Each family has its own, so
the code is split into drivers: a driver is a module with `scan()`,
`identify(ip)` and a `Light(ip)` class (power, brightness, colour, white,
start_stream, frame, stop_stream). `govee.py` is the reference, and
`DRIVERS` in `room.py` lists what's available. Brands that would fit easily
because they have open, local LAN APIs and no account:

- **WiZ** (Philips' cheaper line, sold at a lot of big box stores): JSON over
  UDP port 38899, found with a broadcast.
- **LIFX**: a documented binary LAN protocol on UDP 56700.
- **Yeelight**: a "LAN Control" toggle like Govee's, SSDP discovery, JSON over
  TCP 55443.

Most no-name "Smart Life" bulbs are Tuya inside. They can be run locally, but
only with a per-device key you have to pull from Tuya's cloud first, so they
don't fit the zero-setup idea.

## Matter

Not covered. Govee lights that only do Matter (no LAN Control) would need a
Matter controller and commissioning, which is a bigger job than this prototype.

## Hue

`py_modules/signalbar/room_lights/hue.py` is a stub written from Philips'
docs. **It is untested** (I don't have a Hue bridge anymore), nothing calls it,
and the Hue toggle in the UI is greyed out. It has the same methods as the
Govee light class, so it should slot into the same room logic.

The short version of what I learned: pairing is a link-button press on the
bridge, and the Entertainment areas people already set up in the Hue app can
be read over the local API with every light's position. So Hue users wouldn't
even need the zone picker. Streaming is DTLS to the bridge, which Python can't
do out of the box, so that's where the stub stops. Every spot I'd expect to
need fixing on a real bridge is marked CHECK or TRY in the file.

## Home Assistant

Not in this prototype on purpose. HA service calls are too slow for the
real-time screen zones, but they'd be fine for the slow key-art ring, and the
Home Assistant over MQTT work (#6) already gives GabeCubeAura a connection to
build on. That would let any light HA knows about join in.
