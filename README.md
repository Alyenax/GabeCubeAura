# GabeCubeAura

GabeCubeAura is a Decky Loader plugin for the Steam Machine's light bar and
optional JSAUX Pixel Matrix Faceplate. Configure game artwork colours,
controller battery indicators, CPU/GPU meters, weather, custom effects and
audio or screen synchronisation.

Created and maintained by **Alyenax**.

If GabeCubeAura makes your Steam Machine a little better, you can support its
development on Ko-fi. Thank you! ❤️

[![Support GabeCubeAura on Ko-fi](docs/media/public/support-kofi.svg)](https://ko-fi.com/alyenax)

**New in 1.6.0:** [Nine clock faces](#faceplate-clocks) · [Per-game artwork](#artwork-from-a-games-menu)

[Download GabeCubeAura](https://github.com/Alyenax/GabeCubeAura/releases/latest)
· [User guide](https://github.com/Alyenax/GabeCubeAura/wiki)
· [Changelog](https://github.com/Alyenax/GabeCubeAura/blob/main/CHANGELOG.md)
· [What’s new in 1.6.0](https://github.com/Alyenax/GabeCubeAura/wiki/Release-1.6.0)

## Artwork

![Artwork mode with Deep Rock Galactic artwork and a matching light-bar palette](docs/media/public/artwork-mode-steam-machine.png)

Sample your current game's artwork to set the 17 light-bar colours. Choose its Hero,
Header or Capsule image, then let GabeCubeAura find a suitable row or select
one yourself. Your choice is remembered for each game.

Local Steam artwork comes first, including your custom images and non-Steam
shortcuts. With a Faceplate, you can also prepare static or animated artwork
for its 64 × 54 matrix and reuse it when the game starts.

## Light bar, without a Faceplate

The light bar works on its own. Light events combine Steam notifications, achievements, screenshots and recording signals.

| Performance | Controllers | Weather | Light events |
| :---: | :---: | :---: | :---: |
| <img src="docs/media/public/strip-performance.gif" width="160" alt="CPU and GPU load and temperature signals on the light bar"> | <img src="docs/media/public/strip-controllers.gif" width="160" alt="Controller battery levels and charging on the light bar"> | <img src="docs/media/public/strip-weather.gif" width="160" alt="Animated weather for the selected city"> | <img src="docs/media/public/strip-light-events.gif" width="160" alt="Steam notifications, achievements, screenshots and recording signals"> |
| CPU/GPU load<br>and temperatures. | Battery levels<br>and charging. | Animated weather<br>for your city. | Steam alerts<br>Captures · recording. |

For a more personal setup, match the light bar to the picture or audio, choose your own effects, or keep track of remaining time. The countdown works with a personal timer or a supported Steam Families limit when available.

| Screen Sync | Audio Sync | Customization+ | Countdown |
| :---: | :---: | :---: | :---: |
| <img src="docs/media/public/strip-screen-sync-pip.gif" width="160" alt="Video source shown in PiP with matching light-bar colours"> | <img src="docs/media/public/strip-audio-sync-prism.gif" width="160" alt="Slow Prism with a magnified light-bar detail; silent generated playback"> | <img src="docs/media/public/strip-customization-gallery.gif" width="160" alt="Custom colour and animation examples on the light bar"> | <img src="docs/media/public/strip-countdown.gif" width="160" alt="Remaining time for a personal timer or supported Steam Families limit"> |
| Picture-in-picture<br>colour matching. | Slow Prism<br>reacts to playback. | Your colours<br>and effects. | Personal timer<br>or Steam Families. |

Choose different displays for Home, games and individual titles. One global
light-bar brightness setting applies across those choices, with optional
sunset dimming for a city you select.

## With a JSAUX Pixel Matrix Faceplate

The optional Faceplate adds a second display. Its content and brightness can
be set separately from the light bar.

<table>
<tr>
<th align="center" width="33%">Animated artwork</th>
<th align="center" width="33%">Dashboard · The Witcher 3</th>
<th align="center" width="33%">Steam Players City</th>
</tr>
<tr>
<td align="center" valign="top"><img src="docs/media/public/faceplate-artwork.gif" width="240" alt="Animated game artwork on the Faceplate"></td>
<td align="center" valign="top"><img src="docs/media/public/faceplate-dashboard-witcher-showcase.gif" width="240" alt="Geralt artwork cycling through eight Dashboard layouts"></td>
<td align="center" valign="top"><img src="docs/media/public/faceplate-city-showcase.gif" width="240" alt="Steam Players City growing through day, night and changing weather"></td>
</tr>
<tr>
<td align="center" valign="top">Static or animated artwork<br>saved for each game.</td>
<td align="center" valign="top">Eight layouts: game data,<br>weather and countdown.</td>
<td align="center" valign="top">From village to city,<br>with day, night and weather.</td>
</tr>
<tr>
<th align="center" width="33%">Weather</th>
<th align="center" width="33%">Personal timer</th>
<th align="center" width="33%">TV + Faceplate · <a href="https://github.com/Alyenax/Decky-Animated-Screensaver">Decky Animated Screensaver</a></th>
</tr>
<tr>
<td align="center" valign="top"><img src="docs/media/public/faceplate-weather-pearl-rain-day.gif" width="240" alt="Pearl Rain on the Faceplate and coordinated light bar"></td>
<td align="center" valign="top"><img src="docs/media/public/faceplate-countdown-resident-evil.gif" width="240" alt="Resident Evil 2 artwork and a personal countdown"></td>
<td align="center" valign="top"><img src="docs/media/public/das-tv-faceplate.gif" width="240" alt="Different game artwork on the television and Faceplate"></td>
</tr>
<tr>
<td align="center" valign="top">Your city’s weather<br>on both displays.</td>
<td align="center" valign="top">A visible countdown<br>over game artwork.</td>
<td align="center" valign="top">Different artwork on each display.<br>Requires the separate <a href="https://github.com/Alyenax/Decky-Animated-Screensaver">Decky Animated Screensaver</a>.</td>
</tr>
</table>

Choose a weather scene, Artwork Dashboard or other supported display for
Home and games. Dashboard rows can show controller batteries,
session time, recorded playtime or achievement progress when data is available.
Steam Players City turns the running game's player count into an animated city.

**Decky Vocal Assistant** can add optional voice-assistant visuals through
GCA, while **[Decky Animated Screensaver](https://github.com/Alyenax/Decky-Animated-Screensaver)** can share prepared screensaver
collections with the Faceplate. Both are separate plugins; see the
[integration guide](https://github.com/Alyenax/GabeCubeAura/wiki/Integrations).

*The animated device previews are software illustrations with example readings.*

## Faceplate clocks

Choose from **nine clock faces**: five analog designs and four digital or calendar layouts. Use a different clock at Home and in games, with independent colours and time formats.

![Nine Faceplate clock faces cycling through Amber, Glacier blue, Dusty rose, Sage green, Lavender and Ivory](docs/media/public/v1.6.0/clocks-overview.gif)

*Native 64 × 54 clock renders, enlarged for readability. Analog faces are shown at 12:12 and digital faces at 12:15; the GIF compares six colour palettes.*

**Amber · Glacier blue · Dusty rose · Sage green · Lavender · Ivory**

Choose 24-hour time or AM/PM; dates follow the GCA language. These clocks run locally without an artwork key. Open **Settings → Faceplate Jsaux → Display**, select **Clock** for Home or games, then **Choose a clock**.

[See every clock and its settings](https://github.com/Alyenax/GabeCubeAura/wiki/Clocks) · [Static overview](docs/media/public/v1.6.0/clocks-overview.png)

## Artwork from a game’s menu

With a Faceplate connected, open a game’s Steam library menu and choose **JSAUX Faceplate artwork…**. Select an image, adjust it and prepare a preview for that game. **Settings → Faceplate Jsaux → Artwork** lists your customized games, with actions to edit them or return to the default without deleting prepared copies.

At Home, **GIF library slideshow** rotates already prepared artwork in order or randomly, every 5, 15 or 30 minutes, or every hour. Playback reuses local media.

[Per-game artwork guide](https://github.com/Alyenax/GabeCubeAura/wiki/Faceplate-Artwork) · [Home library](https://github.com/Alyenax/GabeCubeAura/wiki/Home-Library)

## Compatibility

- Designed for the official Steam Machine's **17-pixel light bar** and
  **Decky Loader on SteamOS**.
- Faceplate features require the **JSAUX Pixel Matrix Faceplate**. It is optional.
- CPU/GPU sensors and controller batteries depend on the hardware and data
  exposed by SteamOS. Missing readings stay unknown.
- Screen Sync requires a working Gamescope PipeWire capture source and its
  system tools. GabeCubeAura reports missing components.
- Steam callbacks may change between Steam updates. Compatibility with every
  controller and connection type has not been verified.

## Install and get started

Keep the downloaded ZIP zipped for Decky installation.

1. Install [Decky Loader](https://decky.xyz/) on your Steam Machine.
2. Download the plugin ZIP without extracting it.
3. Open **Decky → Settings → Developer → Install Plugin from ZIP File** and
   choose the downloaded file. Enable Developer mode if that section is hidden.
4. Open GabeCubeAura. Use the optional guided setup for a starting configuration,
   or go straight to the controls and settings. You can reopen the guide later.

Guided setup stays optional. If an earlier attempt was interrupted, **Restart setup** starts the guide again while keeping your active settings, keys and prepared media.

## Guides and support

Start with the [user guide](https://github.com/Alyenax/GabeCubeAura/wiki) for installation, first setup,
light-bar displays, Faceplate artwork, dashboards and optional integrations.
It also covers update choices, backups, reset, privacy and troubleshooting.

Report a problem through [GitHub Issues](https://github.com/Alyenax/GabeCubeAura/issues).
Include your plugin version, SteamOS version, connected hardware and the steps
that reproduce it. Never post API keys or access tokens.

For what has changed, read the [changelog](https://github.com/Alyenax/GabeCubeAura/blob/main/CHANGELOG.md). If you would like to
support the next steps, [buy me a coffee on Ko-fi](https://ko-fi.com/alyenax).

## Privacy and independence

Artwork sampling and screen processing run locally. Optional weather uses
Open-Meteo and a city you select; online Faceplate artwork uses your own
SteamGridDB API key. See the guide for optional integrations and network requests.

GabeCubeAura is an independent community project by Alyenax. It is **not
affiliated with, endorsed by or sponsored by Valve or JSAUX**. Steam and Steam
Machine are Valve trademarks; JSAUX and the associated product names belong
to their respective owners. Game artwork belongs to its creators and rights
holders; see the [preview credits](https://github.com/Alyenax/GabeCubeAura/blob/main/docs/media/public/CREDITS.md).

The GCA code, including the Faceplate engine and UI, uses GPL-3.0-only. Separately identified original Faceplate images and animations owned by Alyenax use CC BY-NC-SA 4.0; third-party elements and user imports retain their own rights. Composite demonstration GIFs are not licensed as a whole by that notice. See [Licensing and reuse](https://github.com/Alyenax/GabeCubeAura/wiki/Licensing) and the [media notice](https://github.com/Alyenax/GabeCubeAura/blob/main/docs/media/public/LICENSING.md).

[Faceplate artwork inventory](https://github.com/Alyenax/GabeCubeAura/wiki/Faceplate-Artwork-Inventory) · [Complete file list and hashes](https://github.com/Alyenax/GabeCubeAura/blob/main/docs/media/public/faceplate-assets.json).
