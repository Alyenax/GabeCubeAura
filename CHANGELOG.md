# Changelog

## 1.5.0 · 2026-10-25

GabeCubeAura 1.5.0 adds the optional JSAUX Faceplate, prepared artwork, Dashboards and Steam Players City, with updated setup, local backups and display controls. See [what's new](https://github.com/Alyenax/GabeCubeAura/wiki/Release-1.5.0).

### Added

- A yellow Artwork / Dashboard Artwork guide in the Decky panel when no current creation is ready, with a direct Create artwork button. Older transfer receipts and removed creations no longer hide the guide.

- Logo size in Adjust image, from 50% to 100% in 5% steps, for separately composed logos. Prepare a new preview and apply it; embedded source logos remain part of the image.
- Preparation, USB transfer and settled-result messages in Decky’s JSAUX panel, using the existing status stream.
- Redacted local diagnostic export and optional five-minute capture details, with no automatic report delivery.
- Local creation ZIP export for active saved artwork, including prepared media and portable metadata.
- Initial calibration with no preloaded Home artwork, mandatory setup and final confirmation. Existing libraries and saved settings are preserved on upgrade.

- Local configuration exports include a complete saved-settings reference, with independent Faceplate, ambience and artwork choices and an explicit coverage list.
- Player Count Only shows the exact number to the unit. Every count layout retains the City smile, including timers, with margins where the content fits.

- Configurable Steam Players City bottom rows: Players + controller in the supplied initial calibration, with Player Count Only available as a separate choice; players with P1 and battery percentage/bar, session time, achievements or total playtime; or Without player count with all eight in-game Dashboard rows. Saved choices are preserved. Battery display appears directly under Players + controller and for Dashboard rows containing controllers. Count Only keeps unit precision; combined rows use k from 1,000. Personal and Steam Families timers temporarily take the right-hand information slot, or the full row without players, before the saved choice returns. Row updates keep the last confirmed City scene and do not change the hourly player-count schedule.

- Low planters and a planted bed in Steam Players City, with garden hedges in smaller settlements. Vegetation follows day/night and weather, with snow on upper surfaces. Architecture, traffic, the player count and the 24-second loop retain their existing behaviour.

- Steam Players City support for Whole image and Bottom edge Faceplate extension, excluding the count rail. A disconnected or powered-off Faceplate falls back to current-game Artwork without changing saved routes; Home yields to Steam. Saved extension choices remain visible in Settings and Decky.

- Daytime snow and thunderstorm Faceplate artwork, retaining original night images and animation timing. Snow day removes the implausible yellow night reflection from the path and limits warmth to window cores. The light bar retains the original white snow and lightning, for both day and night. Weather animation and the Faceplate catalogue provide independent Snow and Thunderstorm day/night choices; old settings/imports preserve the existing selection for both periods.
- Live light-bar previews in Settings and the Decky panel, targeting about 20 frames per second through one shared colour stream that pauses when hidden. Weather keeps a single selected-animation preview and displays its Faceplate image only when the device is connected.
- Independent Rain · day and Rain · night choices in Weather settings and the Faceplate catalogue, retaining the existing rain selection for both on upgrade. Previews use the selected period.
- Automatic day/night colours for both Bluewater and Pearl Rain, with matching saturated light-bar rain palettes. The brighter daytime Bluewater rain uses a petrol head and cyan tail for contrast. Global day/night brightness stays independent.

- Support for the optional JSAUX Pixel Matrix Faceplate, with independent
  display routes for Home and games, a power control and automatic power-off
  on sleep or shutdown.
- Faceplate artwork preparation for static and animated images. Browse
  SteamGridDB with a personal API key, crop and adjust a source, preview the
  prepared result, then explicitly assign it to a game for reuse.
- Artwork Dashboard and weather scenes for the Faceplate. Choose separate
  information rows at Home and in game, including controller batteries,
  session duration, available Steam playtime and achievement progress.
- Steam Players City: an animated city based on the running game's concurrent
  Steam player count, local weather and time of day. The displayed count stays
  fixed throughout each loop; scene updates normally run hourly after the
  initial display, with an additional refresh after screensaver activation. Rain falls in diagonal
  trails, with brief impacts on roads, paths, paved areas and visible roofs.
- Optional presentation integrations with Decky Vocal Assistant (DVA) and
  Decky Animated Screensaver (DAS). DVA owns voice activation, recognition and
  speech; DAS owns its screensaver Studio and collections. GCA retains control
  of its light bar and Faceplate.
- Faceplate playback of prepared DAS collections, including autonomous
  multi-GIF collections installed through the companion plugin.
- A settings-only reset alongside the complete local reset, with distinct
  confirmation text for what each action removes.

### Changed

- Enable automatic update checks by default on fresh installation and settings reset, initially every 24 hours; keep a saved opt-out. Downloading and installation remain manual.
- Settings-only reset forgets Faceplate setup and routes while preserving artwork, access keys and local support evidence. Reconnecting an unconfigured panel offers setup again; saved media does not suppress it.
- Remove the former Hi-Fi Crest tuning panel while retaining the audio pattern and existing rendering choices.
- Initial Faceplate brightness is 70%; the panel retains the USB-power notice above 70%. No Home artwork is preloaded. Users can prepare and assign their own static or animated creations.

- Merge Faceplate troubleshooting details into one Faceplate diagnostics panel, with Connection, Display and Transfers sections. Keep useful data, show repeated errors once and use plain wording.

- Use Economy refresh as the single control for five-point battery steps and five-minute Dashboard clocks; off restores exact percentages and one-minute clock updates. Keep transfer statistics concise. Native clock and animation speed are unchanged.

- Remove Previous screensaver collections from Data and the obsolete Compatibility tab. Existing files stay on disk.
- Keep public update installation manual. Remove the automatic-install choice and drop any inherited consent when this build starts.
- Default public update checks to 24 hours. Remove the five- and fifteen-minute choices and move inherited values at those intervals to 24 hours.
- Keep setup actions visible above Steam’s bottom bar while the content scrolls.
- When upgrading an existing GCA installation, offer Faceplate setup in Decky with a yellow message if an unconfigured Faceplate is detected. Keep the light-bar setup unchanged, recognise existing Faceplate choices and remember an explicit Not now choice after confirmation.

- Show progress, confirmation with the exact local file path, and errors when exporting configuration JSON. Remove the Dashboard-tab reminder and high-brightness advisory from the quick Decky panel; retain them in Settings.

- Bluewater restores its original light-bar rain loop in day and night, removing the later violet contacts. Faceplate day/night images and Pearl Rain palettes are retained.

- Lower the scalloped precipitation umbrella by one native pixel, keeping its shape and colour.

- Next-hour forecast rows use a scalloped umbrella for precipitation probability, separately from the weather-condition icon.
- Steam Players City: Player Count Only uses US thousands separators, for example 48,213. Combined rows keep their compact k notation.

- Faceplate Home and in-game menus share the same background order. Choose Artwork or Weather with or without Dashboard in Display; configure the common information in Dashboard.

- Add six lightning events per 24-second Storm loop in Steam Players City,
  with changing positions behind the skyline and an unchanged count row.

- Reorganise the quick panel and full settings around native Decky controls.
  Keep common light-bar, ambience, game-display and connected-Faceplate
  actions within reach, with detailed controls in their relevant sections.
- Show Faceplate controls while the device is connected and preserve saved
  choices when it is disconnected. Quick selectors and Settings share the
  same supported Home and in-game display choices.
- Keep Faceplate brightness manual and independent from light-bar brightness.
  Changes apply to the current picture without uploading its GIF again.
  A USB-power notice appears above 70%.
- Make Faceplate Off a power action that preserves both saved display routes.
- Start a fresh guided setup from the supplied calibration at 15/255 light-bar brightness, with evening dimming off and an optional 75% night
  level. Preserve resumed setup choices and completed-user preferences.
- Keep setup previews temporary until confirmation, and show a green
  SteamGridDB connection check only after validation succeeds.
- Keep guided setup first and the quick controls unavailable until setup is
  confirmed. Recover unreadable setup progress without trapping the user.

### Fixed

- Restore source exposure for the two daytime cloud-break weather animations and invalidate their prepared caches. Other weather scenes and saved brightness remain unchanged.

- Fix direct Dashboard Weather ↔ Dashboard Artwork switching across provider-local and zoned time representations, including Apply from the weather Dashboard.
- Protect Home/game artwork promotion against concurrent Apply requests. A later status-read failure no longer turns a completed application into a false failure.
- Do not reuse an old transfer receipt to confirm a failed new display choice; describe the failure as an application failure when the choice may already be saved.

- Restore a stable neutral Faceplate scene when the weather city or solar data is unavailable. Defer automatic power-on after host/USB restart until the current scene is confirmed. Preserve saved routes and unknown readings.

- Keep Steam Players City cars rigid as they move, with perspective-based
  changes in size and motion.

- Prevent overlapping settings panes after rapid L1/R1 navigation.
- Use current Dashboard visibility and information choices for preview and
  playback, while preserving independent Home and game preferences.
- Preserve readable controller, session and achievement information at full
  battery and when some Steam statistics are unavailable.
- Improve Screen Sync startup and recovery after an interrupted capture.
- Keep the screensaver visible through a brief interruption in Steam status.
- Keep the previous collection if preparing or installing its replacement fails.
- Distinguish content still being sent from content confirmed by the Faceplate.

### Licensing

- Retain GPL-3.0-only for GCA code, including the Faceplate engine and UI. Identify separately owned original Faceplate images and animations under CC BY-NC-SA 4.0; exclude code, technical metadata, third-party media and user imports from that graphical scope. Preserve third-party terms and valid previous grants. See [Licensing and reuse](https://github.com/Alyenax/GabeCubeAura/wiki/Licensing).

### Documentation

- Shorten the README and move detailed setup, display, integration and
  troubleshooting instructions into a user guide.
- Add separate device illustrations for light-bar-only and Faceplate examples.
- Clarify that GabeCubeAura is an independent project by Alyenax and is not
  affiliated with Valve or JSAUX.

## Previous releases

These summaries describe the features available at the time. Follow each
release link for its original notes and downloads.

## 1.4.0 - 2026-10-05

- Add guided first-time setup with live previews and a final review.
- Introduce one global light-bar brightness setting and optional sunset
  dimming, preserving brightness when changing presets or display routes.
- Return the light bar to Steam during CPU/GPU thermal protection.
- Make Weather the Home display for Atmosphere, with an ambient fallback.
- Preserve existing settings and improve controller and Immersive previews.

[Release 1.4.0](https://github.com/Alyenax/GabeCubeAura/releases/tag/v1.4.0)

## 1.3.2 - 2026-10-04

- Add Audio Sync with ten patterns, built-in and custom palettes, and separate
  Home and in-game looks.
- Add complete lighting presets and a dedicated Blackout display.
- Add Artwork colour intensity and an optional SteamOS weather indicator.
- Improve Screen Sync recovery and handling of Steam downloads.

[Release 1.3.2](https://github.com/Alyenax/GabeCubeAura/releases/tag/v1.3.2)

## 1.2.1 - 2026-10-02

- Add real-time Screen Sync with Panorama and Ambient modes.
- Support Screen Sync during Steam's screensaver and use a fallback while
  Steam Recording needs the capture source.
- Expand battery displays and charging effects to one to four controllers.
- Add eight night-weather animations and expand Customization+ to 65 effects.

[Release 1.2.1](https://github.com/Alyenax/GabeCubeAura/releases/tag/v1.2.1)

## 1.1.3 - 2026-09-30

- Make manual update checks find the current release without requiring a
  channel change.
- Keep automatic update checks lightweight.

[Release 1.1.3](https://github.com/Alyenax/GabeCubeAura/releases/tag/v1.1.3)

## 1.1.2 - 2026-09-30

- Repair update installation and clear a stuck restart state after an update.
- Restore normal update checks and channel selection after Decky restarts.

[Release 1.1.2](https://github.com/Alyenax/GabeCubeAura/releases/tag/v1.1.2)

## 1.1.1 - 2026-09-30

- Add Stable and Beta update channels and selectable automatic check intervals.
- Check at startup and immediately after a channel change.
- Allow an explicit return from Beta to the current stable release.

[Release 1.1.1](https://github.com/Alyenax/GabeCubeAura/releases/tag/v1.1.1)

## 1.1.0 - 2026-09-29

- Add an Updates page with manual checks, daily automatic checks and optional
  new-version notifications.
- Download and verify updates before asking for installation confirmation.
- Keep saved settings and artwork through an update.

[Release 1.1.0](https://github.com/Alyenax/GabeCubeAura/releases/tag/v1.1.0)

## 1.0.0 - 2026-09-27

- Rename SignalBar to GabeCubeAura while preserving existing settings.
- Add Customization+ with exact colours, adjustable effects and live previews.
- Add per-game launch palettes and clearer Artwork and launch-effect controls.
- Keep Steam's native lighting effects available through GabeCubeAura Off.

[Release 1.0.0](https://github.com/Alyenax/GabeCubeAura/releases/tag/v1.0.0)

## 0.7.1 - 2026-09-27

- Rename Light Events only to Signals only and include controller signals
  and countdowns while leaving other permanent effects inactive.
- Detect new Steam Community discussion replies and followed group posts
  without replaying old notifications.

[Release 0.7.1](https://github.com/Alyenax/GabeCubeAura/releases/tag/v0.7.1)

## 0.7.0 - 2026-09-26

- Add Light Events only so temporary Steam cues can run without Artwork or
  Performance.
- Make Slow convergence the fresh-install cloud animation while preserving
  existing weather choices.

[Release 0.7.0](https://github.com/Alyenax/GabeCubeAura/releases/tag/v0.7.0)

## 0.6.1 - 2026-09-24

- Add Cross & gather and Slow convergence cloud animations with full-loop
  previews.
- Clarify country-name search and ZIP installation instructions.

[Release 0.6.1](https://github.com/Alyenax/GabeCubeAura/releases/tag/v0.6.1)

## 0.6.0 - 2026-09-24

- Add city-based weather with sixteen animations and offline previews.
- Add weather brightness and faint-pixel controls for the diffuser.
- Add an optional SteamOS weather indicator in Celsius or Fahrenheit.

[Release 0.6.0](https://github.com/Alyenax/GabeCubeAura/releases/tag/v0.6.0)

## 0.5.1 - 2026-09-23

- Add a clearly named configuration export with its saved file location.
- Simplify the README and refine the controller-battery demonstration.

[Release 0.5.1](https://github.com/Alyenax/GabeCubeAura/releases/tag/v0.5.1)

## 0.5.0 - 2026-09-23

- Add controller battery gauges, connection cues, low-battery alerts and
  charging animations.
- Add per-game Artwork or Performance choices and keep sensor readings fresh
  regardless of the active display.
- Preserve unknown battery information rather than showing invented values.

[Release 0.5.0](https://github.com/Alyenax/GabeCubeAura/releases/tag/v0.5.0)

## 0.4.0 - 2026-09-21

- Add notification, achievement, screenshot and recording effects with previews.
- Improve local and non-Steam artwork support and manual row selection.
- Add Home Performance, response profiles and more readable settings.

[Release 0.4.0](https://github.com/Alyenax/GabeCubeAura/releases/tag/v0.4.0)

## 0.3.1 - 2026-09-20

- Extend dark-pixel diffuser compensation to Performance.
- Add Responsive, Balanced and Smooth meter-response profiles.

[Release 0.3.1](https://github.com/Alyenax/GabeCubeAura/releases/tag/v0.3.1)

## 0.3.0 - 2026-09-20

- Start normal display updates when Decky loads the plugin, without opening
  its settings first.
- Improve Steam Families countdowns, game changes and resume behaviour.
- Add countdown scaling and diffuser compensation.

[Release 0.3.0](https://github.com/Alyenax/GabeCubeAura/releases/tag/v0.3.0)

## 0.2.1 - 2026-09-20

- Add explicit Artwork, Performance and Disabled modes.
- Remember each game's Hero, Header or Capsule choice.
- Add mirrored and left-to-right mixed CPU/GPU layouts.

[Release 0.2.1](https://github.com/Alyenax/GabeCubeAura/releases/tag/v0.2.1)
