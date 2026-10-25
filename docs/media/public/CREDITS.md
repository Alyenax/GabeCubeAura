# Preview credits

GabeCubeAura is created and maintained by **Alyenax**.

Copyright 2026 Alyenax, for identified original owned material only. See [documentation media licensing](https://github.com/Alyenax/GabeCubeAura/blob/main/docs/media/public/LICENSING.md) for the identified original Faceplate CC BY-NC-SA 4.0 graphical scope, original non-Faceplate GPLv3 scope and third-party exclusions; composite GIFs are not licensed as a whole.

The animated Steam Machine enclosure is the project's approved front-view
model, with a gently brighter, slightly thicker light-bar diffuser. The
light-bar-only version uses a solid front panel, without a JSAUX matrix.
The model is a software illustration, not footage of hardware. GIF palettes
are sampled at LED centres to retain the source colours and highlights;
they do not add a saturation or brightness filter to the artwork.

## Artwork

The Stray artwork used in the Faceplate examples is credited to
**LudaX**, [SteamGridDB grid 231089](https://www.steamgriddb.com/grid/231089),
created from a portion of the launch trailer. The prepared 64 × 54 frames
come from the project's existing preview assets. Stray and its artwork
belong to their respective creators and rights holders.

Additional animated game examples reuse the project’s prepared 64 × 54 artwork:

| Game | Contributor and source |
| --- | --- |
| The Witcher 3: Wild Hunt | **TUFKAC**, [SteamGridDB grid 523708](https://www.steamgriddb.com/grid/523708), adapted from a Steam animated background |
| Cyberpunk 2077 | **TUFKAC**, [SteamGridDB grid 170088](https://www.steamgriddb.com/grid/170088), V with the yellow logo; rebuilt by the contributor using a source supplied by Suikale |
| Resident Evil 2 | **Jnill**, [SteamGridDB grid 785014](https://www.steamgriddb.com/grid/785014) |

The Cyberpunk example uses the actual Pixel Studio conversion output: a 64 × 54 matrix, RGB332 colours, and an eight-second animation at 10 frames per second. Its crop keeps V and the yellow logo visible. The model displays the decoded prepared GIF, including its colour reduction.

Dashboard text and the timer are rendered with current GCA components. The Witcher 3 examples show artwork and Dashboard information only. All three games and their artwork belong to their respective rights holders.

The main Artwork presentation image and Ko-fi badge are retained unchanged
from the existing GabeCubeAura documentation. The presentation includes
Deep Rock Galactic artwork, which belongs to its respective rights holders.

The TV + Faceplate presentation uses the existing prepared DAS demo sources:

| Game | Animated TV artwork | Cover and alternate Faceplate artwork |
| --- | --- | --- |
| Elden Ring | [TUFKAC](https://cdn2.steamgriddb.com/hero/2c9f13441c3f36d9422d5de661e57742.webp) | [Morente](https://cdn2.steamgriddb.com/grid/557fa68027943a8b0d3b66c4e72ff23b.png) |
| Cyberpunk 2077 | [fewwan](https://cdn2.steamgriddb.com/hero/a834433907aae376f0fdc19875b6678e.webp) | [jho](https://cdn2.steamgriddb.com/grid/81c4ff81e06c236f16a408089a8cd2ac.png) |

The TV uses the games' transparent Steam library logos:
[Elden Ring](https://cdn.akamai.steamstatic.com/steam/apps/1245620/logo.png)
and [Cyberpunk 2077](https://cdn.akamai.steamstatic.com/steam/apps/1091500/logo.png).
These logos belong to their respective rights holders.

The television shows the DAS player with game logos. The Faceplate uses
separate cover artwork for the same games, cropped to its own display. The
light bar uses GCA's Faceplate extension
with Whole image projection and 100% colour saturation. Scene changes are
coordinated for this illustration; it does not establish exact timing on
physical displays.

The four assistant examples belong to **Decky Vocal Assistant (DVA)**, a separate optional plugin. Gabe Assistant, GabeCube Companion, GLaDOS and Gaby use their shipped DVA character animations. Each silent, scripted exchange has a different scenario; the light-bar mouth uses DVA's renderer with a generated speech envelope. The previews do not record recognition or execute commands. Companion Cube and GLaDOS designs belong to Valve.

Weather and Steam Players City use existing project artwork. The Dashboard,
forecast, timer, player-count and light-bar effects are drawn with production
renderers and fixed example data. No sensor, account, microphone, network
service or physical device is used while generating the animations.

City examples include the approved low planters and planted bed, rendered from the current native animation banks. Smaller settlements use low hedges.

The complete City gallery shows all 72 combinations of weather, day/night
and population range. These use the current City animation frames in the
shared enclosure model, with matching weather light-bar effects. Each GIF
keeps the full 24-second loop; identical consecutive frames may be combined
without changing the timing. Player counts are illustrative.


## README showcase montages

The Witcher 3 showcase retains the existing 24-second, eight-layout montage: plain artwork, a game logo, session and achievement information, controller batteries, weather and a personal timer. Its white logo comes from the game's official Steam assets (AppID 292030) and belongs to its rights holders. The underlying animated Geralt artwork is credited above to TUFKAC.

The 21-second Steam Players City showcase combines seven existing scenes: a village, a town, a large city, night, rain, snow and a thunderstorm. It uses excerpts to introduce the range of appearances; the complete 24-second source loops remain available in the City guide. Both montages use illustrative readings and the shared software enclosure model.


## Light-bar README demonstrations

The Light events montage uses the plugin's native renderers for one Steam notification, an achievement, a screenshot, recording start and recording stop, with short pauses between signals. These are scripted examples rather than recordings of Steam events.

The Screen Sync PiP uses excerpts from the existing animated Elden Ring and Cyberpunk 2077 sources credited above. Each decoded picture is shown in the inset and reduced to the exact 34 × 18 BGRx input supplied to GCA's ScreenSyncProcessor in Panorama mode. The bar colours come from that processor, including its normal temporal smoothing. This local demonstration does not record a live Gamescope session. Its moving source pictures are animated game artwork rather than gameplay footage.

The Audio Sync example uses the current Slow Prism processor with a generated stereo chord, alternating quiet and loud passages, full brightness, Fast reactivity and custom cyan/pink/amber colours. The inset magnifies the same light-bar frame with brighter optical presentation for readability; it is not a Faceplate display or a hardware recording. The GIF is silent. The countdown shows an illustrative 24 minutes out of 30, without accelerating the passage of time. The same remaining-time display can be driven by a personal timer or an available supported Steam Families limit.

## Reading the examples

- Main Artwork and Dashboard examples have no wall clock. The clock is off
  by default; `faceplate-clock.gif` deliberately enables it for a Home example.
- Percentages, temperatures, player counts and playtime are illustrative.
- Timer examples retain their stated remaining time rather than compressing
  a real countdown into a few seconds.
- The apparent brightness and diffusion are presentation choices. The GIFs
  do not establish hardware brightness, optical readability or USB timing.
- The standalone GIF files are documentation media, not installable Faceplate
  firmware or hardware-ready animation packages.

## Independence

GabeCubeAura is an independent community project. It is not affiliated with,
endorsed by or sponsored by **Valve** or **JSAUX**. Steam and Steam Machine
are Valve trademarks. Third-party game images and logos used in these examples belong to their respective creators and rights holders.

Credits identify contributors and sources; they do not grant redistribution
rights. Refer to the original source and rights holders before reusing artwork.

### Weather day/night refresh

The four Bluewater and Pearl Rain day/night examples use the native prepared Weather frames and the matching 17-LED colour sequences. Their 24-second presentation preserves both animation cycles. Values are illustrative; enclosure and diffuser rendering is a software simulation, without calibrated white-spill adjustment or physical colour acceptance.
