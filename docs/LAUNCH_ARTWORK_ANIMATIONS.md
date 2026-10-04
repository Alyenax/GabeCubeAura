# Launch Artwork Animations in GabeCubeAura 1.0.0

## Scope

GabeCubeAura can play an optional one-shot animation when it detects a newly
running Steam AppID. **Game launches is a temporary layer, not an Artwork
display option.** No remote artwork service is required.

Steam's local Library Hero, Header, or Capsule is used. Steam custom-grid files
are already preferred by GabeCubeAura, so artwork installed through SteamGridDB is
compatible without calling the SteamGridDB API.

## Dominant colours at runtime

Image decoding stays in the Decky/Steam browser canvas. GabeCubeAura downsamples
the decoded pixels to at most roughly 5,000 samples, ignores transparent pixels
and suppresses near-black or near-white background noise when enough useful
pixels remain. It then runs deterministic weighted k-means clustering in OKLab
space twice: once for two colours and once for three.

Colour weight favours saturation while retaining less saturated artwork. The
results receive the same bounded contrast correction as Artwork mode. A nearly
monochrome image is completed with lighter/darker values of the detected hue;
GabeCubeAura does not invent an unrelated accent hue.

When the palette source is Artwork, the detected colours also follow the
current game's Artwork colour intensity setting. This is an instant transform
of the cached palette and does not decode or sample the image again. A custom
launch palette is always kept exact and is never changed by this control.

The two launch palettes are stored in a dedicated
`launch-artwork-cache.json`. The permanent Artwork display keeps its own cache,
source and 17-pixel sample row. Consequently, changing the launch colour source
does not change the Artwork display, and vice versa. A `0.7.1` Artwork cache
entry remains usable without being repurposed as a launch palette.

## Display routing and temporary layers

The quick panel and detailed settings now distinguish two concepts:

- **Permanent displays:** separate selectors for **Home** and **In game**, plus
  an optional per-game override. Choices are Steam/default, Artwork (in game),
  Performance, Weather, and Controllers.
- **Temporary layers:** Game launches, Playtime, Light events, and Controller
  alerts. They can interrupt a permanent display and then return to it.

This makes the following configuration possible: Weather on Home, Performance
in game, alerts at all times, and a 20-second artwork-derived launch animation.
The animation runs over Performance at launch; Performance returns when its
visible timer finishes. No permanent Artwork display is required.

## Launch detection

- A real `SteamClient.GameSessions` running notification triggers the effect
  after GabeCubeAura has established its startup baseline.
- The two-second AppID poll can recover a missed `0 → game` transition.
- Starting or reloading GabeCubeAura while a game is already active does not play
  a false launch.
- Suspend/resume stale AppIDs remain suppressed by the existing runtime guard.
- One launch intent is attached to one AppID transition. Title refreshes do not
  replay it.

The intent waits up to 12 seconds for artwork sampling and safe LED ownership.
The configured animation timer starts only when the first frame can actually be
selected. If the bar remains unavailable, the stale launch is discarded.

## Game launches settings

The independent **Game launches** page exposes:

- opt-in toggle, off by default;
- palette size: exactly 2 or 3 dominant colours;
- duration: from 3 to 45 seconds, default 8 seconds;
- ten patterns: Crossed arpeggio, Two hands, Legato, Nocturne, Crescendo,
  Color wipe, Scanner, Theater chase, Twinkle, and Ripple;
- an artwork source independent from the permanent Artwork display;
- an optional two- or three-colour palette saved independently for each AppID;
- a first Preview control and live animated 17-LED strip above the artwork;
- a second Preview control below the artwork, without a duplicate strip, so
  controller focus can reach the full image and page end.

Palette locking permits black and brightness-scaled versions of the selected
colours, but never blends two selected hues into a new one.

## Priority and safety

The effective order relevant to this feature is:

1. GabeCubeAura disabled;
2. short Steam/controller alerts over a stable bar snapshot;
3. Valve/system ownership guard for persistent output;
4. critical playtime countdown (five minutes or less);
5. Game launch animation;
6. regular playtime countdown;
7. the selected permanent Home or In-game display.

A short alert pauses the launch's **visible** timer and the animation resumes
with its remaining time. A critical countdown or a new native LED write cancels
the launch. A regular countdown waits underneath and reappears afterwards.
StripMine has a dedicated **Game launches** ownership preference, independent
from its Artwork preference.

## Verification

- all ten patterns produce deterministic, bounded 17-pixel frames;
- start/end fade, pending timeout, visible-duration pause/resume, duration
  expiry, independent palette caches, display routing, and setting validation
  are unit-tested;
- two- and three-cluster extraction plus monochrome fallback are frontend-tested;
- full backend/frontend suite, TypeScript bundle, and Decky ZIP packaging pass.

The release was also checked on the official Steam Machine for colour output,
diffuser appearance, timing, focus navigation and ownership transitions.
