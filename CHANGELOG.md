# Changelog

## Unreleased

### NEW FEATURE: Home Assistant

- Publish the running game, key art, light bar state, events, controllers,
  countdowns, performance and weather to Home Assistant over MQTT with
  discovery. MQTT is off by default and starts as report only.
- Throttle updates so Home Assistant's database stays small without any
  recorder configuration. Turbo mode sends every change, up to once a second.
- Let Home Assistant change light bar settings once "Home Assistant controls
  settings" is selected. Display settings changed from Home Assistant switch to
  the Custom preset, as they do on the Steam Machine.
- Add "Home Assistant drives it": a light for the light bar, with colour,
  brightness and 17-LED frames on a new Home Assistant display, and flash,
  pulse and sweep alerts in any colour under the usual priorities.
- Restore the display the light replaced when the light or MQTT is turned off,
  and at the next start after a restart. Refuse new colours, frames and alerts
  during thermal protection, a display preset preview or an update install, or
  while GabeCubeAura is switched off.
- Show each MQTT connection step on the Home Assistant page, with a plain
  reason and a retry countdown after a failure.
- Add Header, Cover and Logo images of the running game beside Key art, with
  Steam's addresses for all four.
- Send every status field that is not private, capped at 400 values with short
  lists and text cut at 256 characters, at most once a minute (every second in
  Turbo mode). Remove file paths from error text and never send Private Lab
  release notes.

## 1.4.0 - 2026-10-05

Stable release. Changes since 1.3.2:

### NEW FEATURE: Guided first-time setup

- Add a three-step, full-screen Decky setup for choosing an experience,
  configuring brightness and reviewing the result before it is saved.
- Offer Moderate, Atmosphere, Signals and Immersive with representative
  previews on the physical 17-LED bar. Immersive uses a deterministic Slow
  Prism and Screen Sync demonstration that does not require live capture.
- Keep the final controls above Steam's `Menu / A Select / B Back` footer and
  show a clear scroll cue until the user starts moving down the page.
- Keep existing users out of onboarding. Skipping a new installation applies
  the recommended Immersive preset and Day brightness `9/255`.

### NEW FEATURE: One global Day/Night brightness control

- Add one Day brightness from 1 to 255 for every Home and in-game route.
  Presets and display routes never overwrite it.
- Add optional Night brightness as a percentage of Day brightness, switched at
  the exact sunset and sunrise times for a manually selected city. Weather does
  not need to be the active display.
- Preview both values immediately on the physical bar and show the effective
  `/255` output, active period, next sunrise, location and hardware support.
- Warn in red whenever Day or effective Night output is below `8/255`.
  Important alerts temporarily return to Day brightness.

### NEW FEATURE: Real thermal protection

- Stop every GabeCubeAura animation and hardware write when either CPU or GPU
  reaches 94°C, then return complete light-bar control to Valve immediately.
- Stay disabled until both coherent readings remain strictly below 90°C for 30
  continuous seconds. Missing, stale, non-finite or implausible data during an
  active alert keeps the plugin disabled.
- Show `Désactivé temporairement : protection thermique` while the interlock is
  active. Fixed red is once again an ordinary usable colour.

### NEW FEATURE: Weather-first Atmosphere

- Make Weather the Home display for Atmosphere. If no current weather frame is
  available, fall back automatically to Slow Prism with Screen Sync colours.
- Return Weather to priority as soon as a valid frame is available, without
  changing the selected preset or brightness.

### Major fixes

- Remove the misleading Follow Steam Brightness mode. GabeCubeAura now owns the
  selected gain while it owns the bar and restores Steam's exact saved value on
  every verified Valve handoff.
- Make Day/Night gain transitions crash-safe. Recovery accepts either side of
  an interrupted hardware change without overwriting a newer Steam value.
- Keep thermal protection above every preview and temporary layer. Playtime
  and low-controller alerts continue to use Day brightness.
- Make Signals preview its real two-controller animation before a controller is
  paired, and make Immersive preview independent from Audio Sync, artwork and
  Gamescope availability.
- Preserve every existing user's routing and visual settings during migration.
  Completed setup restores Stable updates every 24 hours and removes saved
  Private Lab authorization.

### Minor fixes

- Reorder presets as Lights out, Essential, Focus, Moderate, Atmosphere,
  Signals, Immersive, Immersive+, Festive and Custom.
- Clarify that Lights out excludes even Valve's download animation, while
  Essential still hands confirmed downloads to Valve.
- Move Light bar brightness to the end of Display Routing, after the optional
  current-game override.
- Hide TW3-SteamRGB, StripMine ownership and per-display StripMine priorities
  behind one collapsed compatibility toggle in Advanced settings.
- Report the RGB attenuation fallback clearly when the hardware driver does not
  expose `brightness_scale`.

## 1.3.3-lab.9 - 2026-10-05

### Display Routing brightness warnings

- Show the same red low-output warning from onboarding below Day brightness in
  Display Routing whenever it is below `8/255`.
- Show it below Night brightness whenever the computed effective night output
  is below `8/255`, including when the day value itself remains higher.

## 1.3.3-lab.8 - 2026-10-05

### Skip setup correction

- Make `Skip guided setup · Keep recommended defaults` apply the actual
  recommended configuration before closing: Immersive and Day brightness
  `9/255`.
- Keep Valve handoffs unchanged. Whenever GabeCubeAura intentionally yields
  the bar, the exact saved Steam brightness is still restored.

## 1.3.3-lab.7 - 2026-10-05

### Immersive onboarding preview

- Replace Immersive's source-dependent preview with a deterministic ten-second
  sequence on the real light bar: a breathing synthetic Slow Prism in Sapphire,
  followed by a moving synthetic Screen Sync panorama.
- Keep Steam, thermal and companion-plugin ownership priorities above the demo.
  The demo does not start PipeWire or Gamescope capture and does not alter the
  real Immersive routes saved after setup.
- Mirror the exact synthetic 17-pixel frame and current Audio Sync or Screen
  Sync phase in the onboarding interface.

## 1.3.3-lab.6 - 2026-10-05

### Onboarding clarity

- Apply the same `9/255` recommended starting value to the effective Night
  brightness. Show its computed `/255` output and a red warning whenever it
  falls below `8/255`.
- Add a floating `Scroll down for the buttons` cue above Steam's footer on all
  three setup steps. It disappears as soon as the user starts scrolling.

## 1.3.3-lab.5 - 2026-10-05

### Advanced settings cleanup

- Hide TW3-SteamRGB compatibility, StripMine ownership coordination and every
  `Priority while StripMine is active` choice behind one collapsed toggle.
- Keep every compatibility setting and live status unchanged when the controls
  are expanded. The new toggle only reduces clutter and is not persisted.

## 1.3.3-lab.4 - 2026-10-05

### NEW FEATURE: Weather-first Atmosphere

- Make Weather the Home display for Atmosphere. If no city, network result or
  fresh weather frame is available, the same preset automatically falls back
  to its previous Slow Prism with Screen Sync colours.
- Keep the real Audio Sync fallback warm only while Weather is unavailable;
  a valid Weather frame resumes priority automatically.

### Onboarding improvements

- Replace Essential and Immersive+ in the visual first-run selection with the
  more demonstrative Moderate and Signals presets. The four choices are now
  Moderate, Atmosphere, Signals and Immersive.
- Keep Signals visually useful before pairing a controller by replaying its
  real two-controller animation through the same backend and physical bar.
- Add a red warning below `8/255` explaining that such a low Day brightness can
  strongly affect the lighting experience.

### Display routing cleanup

- Put presets in the requested order: Lights out, Essential, Focus, Moderate,
  Atmosphere, Signals, Immersive, Immersive+, Festive, then Custom.
- State clearly and in bold that Lights out excludes even Valve's download
  animation, while Essential continues to hand confirmed downloads to Valve.
- Move Light bar brightness to the final settings section of Display routing,
  after the optional current-game override.

## 1.3.3-lab.3 - 2026-10-05

### NEW FEATURE: One brightness control for the whole light bar

- Add a global **Day brightness** from 1 to 255, independent of Home and
  in-game routes. The shipped and migrated Consistent output remains exactly
  `9/255`.
- Apply **Night brightness** as a percentage of the chosen day value. At the
  default 35%, `9/255` becomes `3/255` after sunset.
- Show the active output, next sunrise, selected city, hardware support and
  exact Steam brightness saved for the next handoff in Display routing.
- Remove the misleading Follow Steam Brightness choice. Steam's value is now
  only the exact value restored whenever Valve regains the bar.

### NEW FEATURE: Real hardware previews during first setup

- Turn preset selection into a ten-second preview of the real Home recipe on
  the physical 17-LED bar. Audio Sync uses the live audio engine; the Decky
  preview mirrors the engine's 17 pixels instead of inventing another
  animation.
- Preview Day and Night slider changes immediately on the physical bar with a
  bounded three-second calibration frame.
- Rework the guided setup into Experience, Brightness and Review. The review
  includes the day gain and the computed night gain.

### Major fixes

- Move all sunset dimming from per-frame RGB multiplication to the single
  hardware gain layer. Changing a display preset or route can no longer alter
  the chosen global brightness.
- Make dynamic day/night gain changes crash-safe. Recovery records accept both
  sides of an in-progress transition and always restore the original Steam
  value after a verified handoff or interrupted session.
- Keep playtime and low-controller alerts at day brightness. Thermal
  protection still bypasses every preview and immediately returns complete
  control to Valve.
- Put the full-screen setup inside Decky's native scrolling panel and reserve
  156 pixels below its final controls for Steam's Menu / A Select / B Back
  footer.

### Minor fixes

- Use the previous RGB attenuation path only when the driver does not expose
  `brightness_scale`, and identify that fallback clearly in the interface.
- Move city and automatic night controls into the global Light bar brightness
  section while Weather keeps the same shared location and solar data.
- Keep existing users out of onboarding and preserve Stable updates every 24
  hours with no stored Private Lab authorization on a completed first setup.

## 1.3.3-lab.2 - 2026-10-05

### Full-screen first-run setup

- Move the complete three-step onboarding flow out of Decky's narrow quick
  panel and into the dedicated full-screen SteamUI route
  `/gabecubeaura/setup`.
- Add a controller-friendly two-column lighting preset selector, live 17-LED
  previews, a clear three-step progress indicator and a compact final review.
- Keep the quick panel focused on a single `Open guided setup` action until
  onboarding is complete. Navigate before closing Decky's side menu to avoid
  the Big Picture route race documented by Decky.
- Return to the previous Steam page after applying or skipping setup. Directly
  reopening the route after completion cannot overwrite the saved choices.

### Update privacy safeguard

- Explicitly restore Stable updates with automatic checks every 24 hours when
  first-run setup finishes or is skipped.
- Remove any saved Private Lab authorization before onboarding is marked
  complete, so a new installation never retains personal private-channel
  credentials.

## 1.3.3-lab.1 - 2026-10-05

### Thermal safety correction

- Replace the fixed-red colour heuristic with a real CPU/GPU thermal
  interlock. Either processor reaching 94°C immediately stops GabeCubeAura
  output and returns complete light-bar control to Valve.
- Keep GabeCubeAura disabled until both coherent sensor readings remain
  strictly below 90°C for 30 continuous seconds. A missing, stale, non-finite
  or implausible reading during an active alert resets recovery and keeps Valve
  in control.
- Restore fixed red as an ordinary usable colour. LED colour is no longer
  treated as evidence of a thermal alert.
- Display `Désactivé temporairement : protection thermique` in the quick panel
  while the thermal interlock is active.

### New features

- Add a three-step first-run setup that lets a fresh installation choose
  Essential, Atmosphere, Immersive or Immersive+ before presenting the normal
  quick panel. Existing installations are marked complete during migration and
  are never interrupted by the new flow.
- Make Immersive+ the explicit named preset for a fresh installation instead
  of showing Custom for the same shipped routing.
- Add an optional automatic night mode driven by sunrise and sunset for the
  exact Weather location selected by the user. No IP-based location is used.
- Add a 10% to 100% night brightness control. Ordinary GabeCubeAura frames are
  reduced after sunset and restored after sunrise, while playtime warnings
  remain fully visible and thermal protection stays active.

### Lab fixes and safeguards

- Request two days of Open-Meteo solar times and schedule a refresh at the next
  sunrise or sunset instead of waiting for the normal fifteen-minute interval.
- Disable automatic night mode if its saved Weather location is removed.
- Keep legacy configurations on Custom and skip onboarding so an upgrade never
  changes an existing user's routing or opens a first-run screen.

## 1.3.2 - 2026-10-04

Stable release. Changes since 1.2.1:

### Highlights

- **Audio Sync:** turn game and system audio into real-time light with ten
  patterns, including Hi-Fi Crest, Slow Prism, Spectrum and Stereo Field.
- **Separate Home and in-game looks:** choose a different Audio Sync pattern,
  palette and custom colours for each context.
- **Nine display presets:** switch the complete light-bar setup in one action
  with Lights out, Focus, Essential, Moderate, Atmosphere, Signals, Immersive,
  Immersive+ or Festive.
- **Artwork colour intensity:** adjust game artwork from greyscale to vivid
  colour without changing its brightness or reloading the image.
- **SteamOS weather in the top bar:** show the current weather icon and
  temperature beside the clock with three locally bundled icon styles.
- **Light-bar calibration:** optionally keep GabeCubeAura output consistent,
  preview colour separation and safely restore Steam's brightness afterward.
- **More control over Steam effects:** use Blackout and the new Compatible,
  Downloads + safety and Safety only ownership policies.

### New features

- Add Audio Sync as a permanent Home, in-game and per-AppID display. Mixed
  PipeWire output is analysed locally and kept in memory; stale samples are
  never rendered or written to disk.
- Add ten selectable Audio Sync patterns. Hi-Fi Crest maps adaptive bass, mid,
  high-frequency texture and stereo direction to broad physical-bar zones.
  Spectrum, Stereo Field, Bass Pulse and Audio Pulse remain available beside
  five new diffuser-aware patterns: Velvet Relay, Negative Bloom, Stereo
  Lanterns, Constellation and Slow Prism.
- Apply one bounded 10.2-second programme reference to every Audio Sync
  pattern, so quiet, loud and compressed sources retain motion without a
  separate level trim. Spectrum preserves the relative energy of its 17
  logarithmic frequency bands.
- Make Audio Sync patterns independent from palettes. Built-in colour families,
  custom colours, the running game's Artwork and live Screen Sync samples can
  be combined with any pattern. Live samples are harmonised into bounded
  centre, shoulder and edge roles for the Steam Machine diffuser.
- Save independent Home and in-game Audio Sync patterns, palettes and custom
  colours. Existing settings migrate to both contexts, while brightness and
  reactivity remain shared. Add Calm, Balanced, Fast and Punchy response
  profiles plus one-button recommended tuning for each pattern.
- Add nine one-step routing presets: Lights out, Focus, Essential, Moderate,
  Atmosphere, Signals, Immersive, Immersive+ and Festive. Returning to Custom
  restores the setup saved before the first preset was applied, and editing a
  recipe converts it into a custom setup.
- Add Blackout as a true permanent display and three Steam ownership policies:
  Compatible, Downloads + safety and Safety only. The protected policies use
  capability-detected, reversible Steam LED manager requests while always
  yielding to the conservative critical-red hardware safeguard.
- Add an opt-in Consistent output calibration policy. It temporarily applies
  the tested 9 / 255 Valve hardware brightness reference only while
  GabeCubeAura owns the bar, restores the saved value on handoff and includes
  atomic recovery plus a ten-second colour and motion preview. Version 1.3.2
  ships with Consistent output selected; Follow Steam remains available.
- Add Artwork colour intensity from 0% greyscale to a protected 200% maximum.
  Perceptual OKLab adjustment preserves lightness, avoids clipped channels and
  updates Artwork displays, Audio Sync Artwork palettes and artwork-derived
  launch colours without re-downloading the image.
- Add the optional SteamOS top-bar weather indicator with three locally bundled
  icon families and previews for all nine weather conditions. Fresh installs
  enable it with Phosphor Duotone; it stays hidden until a city is selected.
- Add a read-only Private Lab update channel for Alyenax's target-hardware
  builds. GitHub device authorization, owner-only token storage, semantic Lab
  tags, checksums, explicit installation confirmation and the existing rollback
  path are required for every private package.
- Ship fresh installations on the Stable update channel with one automatic
  check every 24 hours. No private authorization or token is preconfigured.

### Major fixes

- Preserve partial PipeWire reads and process every complete 60 ms analysis
  block in chronological order. The bounded queue now reports dropped blocks,
  uses real sample timestamps and no longer loses residual audio at the 50 ms
  capture cadence.
- Keep the last valid Audio Sync frame and palette across Home/game transitions,
  launch animations and capture restarts. A fresh Gamescope palette is accepted
  only when ready, preventing a blue Steam frame or fallback-colour flash while
  retaining the priority of downloads, alerts, launch effects and critical
  hardware warnings.
- Correct Steam download detection. Detailed download-item state now identifies
  active, incomplete and non-deferred transfers; queued work such as Proton
  Hotfix cannot suspend GabeCubeAura. The broad overview remains a fallback for
  SteamOS versions without a usable detailed replay.
- Recover Steam LED manager state after Decky restarts, detect transfers already
  in progress, restore native hardware controls before yielding and acquire or
  release Download/Customize modes only after the backend ownership handoff.
  Service rejection and shutdown during an in-flight request now restore the
  previous manager state instead of reporting false success.
- Recover Screen Sync cleanly across plugin replacement, AppID changes and
  Desktop/Gaming Mode transitions. Stale GabeCubeAura GStreamer clients are
  released, each new capture gets its own process group and failed or PAUSED
  pipelines are closed before rediscovery.
- Pass Artwork colour intensity through the real Decky RPC allowlist. The value
  is now stored and returned instead of snapping back to 100% after the UI call.

### Minor fixes

- Give Hi-Fi Crest a 120 ms centre-to-edge crest, bounded retrigger and lifetime
  timing, and expose measured block cadence, FFT window, buffer, queue, sample
  age, LED interval and envelope timing in the optional diagnostics.
- Add Sapphire and Coastline palettes. Screen Sync and Artwork use Sapphire as
  their cold fallback, hold the last stable contextual colours and fade into a
  new live source instead of flashing Aurora.
- Make every routing recipe explicit about Audio Sync context, Steam Families,
  controller alerts, charging and Light Events. Immersive uses Slow Prism with
  Sapphire at Home and Screen Sync in games; Immersive+ uses Slow Prism with
  Screen Sync in both contexts; Festive uses Screen Sync at Home and Aurora in
  games.
- Reduce only the Clear sky night moon-white steps from 128/192/255 to
  112/168/224. Other night palettes, backgrounds, timing and choreography are
  unchanged.
- Sort Audio Sync patterns and palettes, remove obsolete Lab prefixes from
  pattern names and make Slow Prism recommend Fast response.
- Replace large inline RGB sliders with a compact colour control that keeps hue,
  saturation, lightness and exact Hex entry together.
- Hide detailed Audio Sync and Screen Sync telemetry until Show live diagnostics
  is enabled. Keep the temporary Hi-Fi Crest calibration controls behind their
  own Advanced / debug switch in both Audio Sync views.
- Simplify the quick Decky panel by removing redundant preset, ownership,
  temporary-layer and output explanations. Rename the master switch to
  `Enable GabeCubeAura`, keep actionable status visible and place Updates just
  before Advanced / debug.
- Remove the Experimental label from top-bar weather, drop the Meteocons family
  and its packaged license, and keep Material Rounded and Phosphor license texts
  in the installable archive.

## 1.2.1 - 2026-10-02

Stable release. Changes since 1.1.3:

### Screen Sync

- Add local real-time Gamescope colour capture with Panorama mapping across 17
  horizontal zones and a calmer single-colour Ambient mode.
- Keep captured frames in memory, reject stale frames, reduce bright HUD
  influence, detect stable cinematic black bars and expose brightness,
  reactivity, colour-intensity and black-threshold controls.
- Allow Screen Sync as the default in-game display, as a per-AppID override, as
  a 15-second preview and as an independent Steam screensaver display.
- Detect the Steam screensaver through read-only service capabilities and let
  it replace permanent Home displays without covering Steam system activity,
  temporary alerts, Game launches or playtime countdowns.
- Stop Screen Sync during Steam Game Recording or another Gamescope capture,
  then use the saved Customization+ display as the safe fallback.
- Preserve the lifetime-confirmed running AppID across transient Steam menu,
  overlay and resume gaps so the selected game route does not require
  controller input to return.
- Close failed or PAUSED GStreamer pipelines before retry, clean only stale
  clients carrying GabeCubeAura's exact capture marker and isolate each capture
  in its own process group.
- Keep the read-only capture warm while Steam temporarily owns the LEDs. When
  Gamescope or PipeWire actually disappears, close the old capture, wait for
  the session to settle and rate-limit rediscovery.

### Controllers

- Add fixed battery seats, previews and targeted charging animations for one
  to four controllers.
- Mirror two- and four-controller layouts, use three left-to-right zones for
  three controllers and keep charging effects inside the affected seat.
- Add an Automatic colour preset that uses battery colours for one controller
  and distinct P1 to P4 colours from two controllers onward.
- Retain a Manual preset for choosing Battery level or Player seats at every
  controller count, with four editable player colours.
- Extend multiplayer connection patterns to the third and fourth controller
  without inventing percentages for unknown or coarse battery readings.

### Weather and Customization+

- Add eight night Weather transpositions: two moon scenes, four night-cloud
  scenes and two moon-through-cloud scenes. Weather now offers 22 selectable
  loops while keeping existing selections.
- Route cloudy live Weather to separate day and night families and use a deep
  blue night field, neutral clouds and stepped moon whites.
- Expand Customization+ to 65 effects by making the four night-cloud patterns
  available without renaming existing effects.

### Ownership, recovery and compatibility

- Add hard Steam ownership for startup, downloads, repeated native LED writes
  and native thermal warnings. GabeCubeAura previews and events do not write
  through those leases.
- Claim manual LED mode only for an active GabeCubeAura lease and restore the
  previous Valve effect and enabled state only while GabeCubeAura still owns
  the verified frame.
- Recover after isolated provider, capture or hardware faults instead of
  leaving a frozen frame on the bar.
- Avoid displaying the saved Customization+ fallback during the native
  Game-launch handoff.
- Add optional compatibility with the standalone TW3 SteamRGB companion. A
  fresh companion claim can replace the permanent display, while Steam system
  activity, previews, alerts, Game launches and playtime countdowns retain
  priority. The Compatibility page can disable this handoff.
- Keep the experimental Witcher HUD and telemetry mod out of GabeCubeAura. They
  are distributed separately through TW3 SteamRGB.

### Diagnostics

- Expand runtime diagnostics with Gamescope discovery, PipeWire session,
  capture identity, selector, frame freshness, ownership and recovery details.

## 1.1.3 - 2026-09-30

This maintenance release makes the latest updater correction available under a
new version, so existing 1.1.2 installations can receive it normally. It does
**not** include Screen Sync, the new Weather animations, 4-controller support,
or any of the other changes currently in the 1.2.0 beta.

- Make **Check now** bypass the stored GitHub ETag and request the complete
  current release. A manual check can no longer miss a newly published version
  because GitHub returned `304 Not Modified` for stale local update state.
- Keep conditional ETag requests for automatic checks, preserving the lighter
  background polling behaviour.
- Remove the need to change between Stable and Beta merely to reveal an update.
  Channel changes continue to trigger an immediate check as intended.
- Retain the independent helper launch, restart-state recovery, package
  verification, Stable and Beta channels, selectable intervals and rollback
  safeguards from 1.1.2.
- Validate the correction on the Steam Machine with a local 1.1.0 test package:
  **Check now** detected the public 1.1.2 release directly on Stable without a
  channel change.

## 1.1.2 - 2026-09-30

This focused recovery release fixes the final launch step of the direct updater.
It does **not** include Screen Sync, the new Weather animations, 4-controller
support, or any of the other changes currently in the 1.2.0 beta.

- Remove Decky Loader's bundled library and Python runtime overrides before
  starting the SteamOS `systemd-run` command.
- Keep the original helper launch failure detail in the Decky backend log while
  retaining a short error in the interface.
- Synchronize the running backend with the terminal transaction state written by
  the independent helper after Decky restarts.
- Recover a healthy replacement backend if persisted state remains at
  `restart_pending`, then allow update checks and channel selection again.
- Close an older `restart_pending` transaction when a newer manual installation
  has already replaced its target version.
- Make `Check now` bypass the stored GitHub ETag so a manual check always reads
  the current release, while automatic checks retain conditional requests.
- Add coverage that launches the helper from a deliberately contaminated Decky
  environment and verifies that system commands receive a clean environment.
- Require one manual installation of 1.1.2 for versions 1.0.0, 1.1.0 and 1.1.1.
  Future releases can then use the repaired in-plugin update flow.
- Validate the corrected launcher on the Steam Machine by updating a local
  1.1.0 test build to the unmodified public 1.1.1 release.

## 1.1.1 - 2026-09-30

This maintenance release exists to validate GabeCubeAura's direct updater on
the public stable path before distributing the larger 1.2.0 beta. It is built
from 1.1.0 and does **not** include Screen Sync, the new Weather animations,
4-controller support, or any of the other changes currently in the 1.2.0 beta.

- Add automatic update intervals of 15 minutes, 1, 3, 6, 12 or 24 hours.
- Add Stable and Beta update channels. Stable remains the default. Beta can
  offer a newer published prerelease through the same notification, verified
  download and confirmation flow.
- Run one automatic update check when Steam loads the plugin, when automatic
  checks are enabled, without waiting for the periodic deadline.
- Check immediately when the selected update channel changes.
- Allow an installed beta to return explicitly to the current stable release,
  even when that stable version has a lower version number. Keep transactional
  recovery to the previously working build if the target does not start.

### Coming very soon on the Beta channel

- Support for up to four controllers.
- Responsive real-time Screen Sync inspired by Hue Ambilight.
- Improved night Weather patterns built around a proper night-blue background.
- The Witcher 3 Lab, an experimental mod for visualising HUD elements on the
  light bar in real time.

These features are not included in 1.1.1. This release provides the opt-in Beta
channel that will make them available for testing before their stable release.

## 1.1.0 - 2026-09-29

- Add a dedicated Updates page with manual checks, daily background checks and
  one optional Decky notification for each new stable version.
- Download only fixed assets from the official `Alyenax/GabeCubeAura` GitHub
  releases. Keep certificate and hostname verification enabled and reject
  unexpected redirects.
- Verify release metadata, compressed and extracted size limits, SHA256,
  archive paths, required files, plugin identity and target version before any
  installed file is changed.
- Require explicit confirmation before installation. Decky restarts briefly
  only after the complete package has been staged and verified.
- Preserve settings and artwork caches outside the replaced plugin directory.
  Restore the previous version automatically if the new backend does not
  acknowledge a healthy startup within 45 seconds.
- Add an isolated Update lab to local test builds for valid-package, checksum
  rejection and rollback rehearsals. The lab is hidden from stable builds and
  never touches the real plugin directory or Decky service.
- Produce a lean versioned archive, an identical fixed-name recovery archive
  and `SHA256SUMS`.
- Move public repository, issue, image and installation links to
  `Alyenax/GabeCubeAura`.

## Decky Store submission preparation - 2026-09-27

- Set the public package and plugin author to Alyenax and add the canonical repository, issue tracker and homepage metadata.
- Add a Store description and a public GabeCubeAura product image to the Decky publish metadata.
- Retain the original Steam Deck Homebrew template copyright notice beside the GabeCubeAura copyright.
- Adopt a pnpm 9 lockfile and package-manager pin for reproducible Store review builds.
- Move documentation media out of Decky's reserved root `assets` directory and remove obsolete SignalBar interface captures.
- Keep the installable archive focused on runtime files, the license and third-party notices.
- Add a Store submission record with the proposed listing text, permission explanation, backend answers and remaining third-party test requirements.
- Keep version 1.0.0 because these changes prepare the first Store submission and do not change runtime behaviour.

## 1.0.0 - 2026-09-27

- Rebrand the former SignalBar product as **GabeCubeAura** across the Decky product, UI, logs, package, configuration export, documentation, GitHub repository and public concept pages. Internal setting keys and the StripMine protocol identity remain unchanged. A fresh GabeCubeAura settings directory copies an existing SignalBar configuration and artwork caches once.
- Restore Decky's standard `SidebarNavigation` for detailed settings, with one simple left-hand tab per feature. Rename the untouched route **GabeCubeAura Off**; this route leaves permanent output to Steam while temporary layers remain available, while the master switch still disables every GabeCubeAura output.
- Add **Customization+** as a permanent Home and In-game display with exact opaque Hex/RGB colours, one/two/three-colour palettes, raw 34 to 255 brightness, functional 1 to 100 speed, direction, live preview, and 61 unchanged effect names grouped by dynamism as Calm & ambient, Flowing, and Energetic.
- Remove the misleading Alpha control from GabeCubeAura colour pickers: the LED backend stores three opaque RGB channels and never consumed transparency.
- Keep Steam's Patrol, Breathe, Rainbow, and Solid presets in Steam rather than shipping lookalike animations without a public timing contract or preset API. Select GabeCubeAura Off to use the native Steam customization.
- Add per-AppID Game Launch palettes, preserving both two- and three-colour versions, and include them in configuration export/import.
- Make all ten Game Launch patterns palette-locked: fades may dim a selected hue toward black, but overlaps and Legato no longer create unselected intermediate hues.
- Remove the inert dominant-palette strip that looked like an animation above Game Launch Preview. Keep the real 17-LED animated bar with the first Preview control and refresh it every 100 ms while the page is open.
- Replace Replay with a second **Preview** control below the artwork, without another LED bar beneath it. The image remains focusable and the final button gives Steam gamepad navigation a natural target for scrolling through the complete image.
- Add three reproducible README animations for Customization+, per-AppID artwork palette extraction, and representative Game Launch patterns. They are generated from the Concept Lab with `npm run media:release` and remain explicitly labelled as browser simulations.
- Restructure the README draft so Artwork and Game launch animations are separate concepts, with dedicated visual explanations for two- and three-colour palettes, speed, and launch patterns.
- Add a repository, package, documentation, GitHub Pages, annex-site, compatibility, publication, and rollback roadmap for completing the GabeCubeAura rebrand without breaking SignalBar-era settings or links.
- Publish the manually verified `GabeCubeAura-v1.0.0.zip` with `SHA256SUMS`.

## 0.8.0 - LOCAL BETA - 2026-09-27

- Split permanent displays from temporary layers. Home and In-game displays are now routed independently, with optional per-game overrides; Game launches, Playtime, Light events, and Controller alerts can run over them without forcing Artwork mode.
- Add optional Game launch animations using a newly detected Steam AppID; loading SignalBar while a game is already running does not replay the launch.
- Extract deterministic two- and three-colour dominant palettes locally in Steam's canvas with bounded OKLab clustering. Nothing is uploaded and SteamGridDB replacements already present in Steam's custom-grid folder are supported by the existing artwork discovery.
- Add ten selectable 17-LED patterns: Crossed arpeggio, Two hands, Legato, Nocturne, Crescendo, Color wipe, Scanner, Theater chase, Twinkle, and Ripple.
- Add an independent Hero/Header/Capsule colour source, a duration control from 3 to 45 seconds, an exact palette-size choice, the detected-palette preview, and a manual launch preview.
- Pause the visible launch timer for short alerts and resume afterwards. Critical countdowns and native writes cancel it; regular countdowns wait underneath it. Pending launches expire after 12 seconds.
- Keep launch palettes in a dedicated cache, separate from the permanent Artwork display, and give Game launches its own StripMine ownership preference.
- This build is packaged locally only. It has no tag or public GitHub release, and physical colour/timing quality still needs Steam Machine validation.

## 0.7.1 - 2026-09-27

- Rename the user-facing **Light Events only** display to **Signals only** and keep controller battery gauges, continuous charging, brief controller alerts, and playtime countdowns active there. Artwork, Performance, and Weather stay dormant; when no useful signal is active, the bar is released.
- Detect new replies in subscribed Steam Community discussions and followed group posts from Steam's server notification centre without replaying the existing inbox or duplicating native comment toasts.
- Restore the dedicated **Compatibility** page and the complete StripMine ownership protocol that were omitted from the first v0.7.1 package. Choose SignalBar or StripMine priority independently for Artwork, Performance, Weather, Controller displays and Light Events.
- Extend acknowledged handoffs to permanent SignalBar providers. Playtime countdowns remain fixed SignalBar priorities, while an empty Signals only display yields to StripMine.
- Complete SignalBar's final restore before acknowledging StripMine priority, preventing the physical 17-LED write sequence from being mistaken for an unrelated application.

## 0.7.0 - 2026-09-26

Official release. Changes since 0.6.1:

### Light Events only and StripMine coordination

- Add **Light Events only** as a fourth display mode. It leaves the bar untouched between Steam notifications, achievements, screenshots, and recording animations. Saved Artwork and Performance profiles remain dormant until another display mode is selected.
- Answer [issue #1](https://github.com/Alyenax/SignalBar/issues/1): Light Events can now run without enabling Artwork or Performance.
- Add coordinated Light-event handoff for StripMine, which is developed by the same author. SignalBar publishes a short renewable lease, waits briefly for StripMine to yield, plays the event, restores the exact pre-event frame, then releases the lease so StripMine can resume automatically.
- Keep the handoff fail-safe. The lease expires after a crash, and StripMine verifies the restored LED signature before reclaiming the bar. Local arbitration and lifecycle tests pass; the physical transition still requires Steam Machine validation.

### Reliability

- Make **Slow convergence** the default Cloud Weather animation on fresh installs. Existing saved Cloud selections remain unchanged.
- Restore Python 3.9 compatibility for the Decky backend entry point.
- Preserve existing settings when upgrading and keep all higher-priority countdown, alert, and native ownership rules intact.

## 0.7.0-alpha.5 - LOCAL ONLY - 2026-09-26

- Add **Light Events only** as a fourth display mode. It leaves the bar untouched between Steam notification, achievement, screenshot, and recording animations; saved Artwork and Performance profiles remain dormant until another display mode is selected.
- Add coordinated Light-event handoff for StripMine, which is developed by the same author. SignalBar publishes a short renewable lease and waits for StripMine's acknowledgement before its first event frame, restores the exact pre-event frame, then releases the lease so StripMine can resume automatically. When StripMine is not installed, the event proceeds after a brief timeout.
- Keep the handoff fail-safe: the lease expires after a crash, and StripMine must still verify the restored LED signature before reclaiming the bar. Local arbitration and lifecycle tests pass; the physical transition still requires Steam Machine validation.

## 0.6.1 - 2026-09-24

- Add **Cross & gather** and **Slow convergence** to Cloud Weather. The first
  crosses two pairs before a drifting three-LED cloud gathers smaller ones at
  a relaxed pace; the second grows into an eight-LED cloud, drifts left,
  returns right, then exits the bar. Both use neutral white at varied
  brightness, without coloured tails.
- Keep **Passing shadow** and **Passing shadows** unchanged and selectable.
  Cross & gather is the default on fresh installs; existing Cloud choices
  remain selected after updating from 0.6.0.
- Play the entire 20- or 48-second loop when previewing a new Cloud pattern.
  Other Weather loops remain eight seconds.
- Clarify Weather's optional Country field: enter the full country name, not a
  two-letter code. Update the no-results hint to match.
- Correct the ZIP installation instructions: enable Developer mode under
  **Decky > Settings > General** only when the **Developer** section is not
  already visible, then use **Developer > Install Plugin from ZIP**.

## 0.6.0 - 2026-09-24

Official release. Changes since 0.5.1:

### Weather

- Add optional local-weather lighting for clear day, clear night, rain, cloud,
  partly cloudy day and night, snow, and thunderstorm. Each of the eight sky
  conditions has two selectable eight-second LED loops (16 total), including
  **Snow takes hold** as the fresh-install snow choice. Preview every loop
  without a city or network connection.
- Let Weather run on Home, in game, or everywhere. A permanent Weather scene
  and the permanent controller gauge are mutually exclusive; the controller
  gauge remains the fresh-install default until a user chooses a city and
  enables Weather. Countdowns, brief alerts, Valve's ownership guard, and the
  recording marker retain their priorities.
- Search for a city or postal code with an optional country, then request
  current conditions from Open-Meteo about every fifteen minutes. There is no
  automatic location detection or API key. A stale reading yields the LED bar
  instead of remaining on display. SteamOS HTTPS certificate verification
  remains enabled, with the system CA bundle used when Decky's embedded Python
  cannot find the issuer.
- Tune Weather-only brightness and the faint-LED cutoff for the physical
  diffuser. Final scenes avoid low-brightness brown, blue-grey and violet LED
  tails that looked unexpectedly red, cyan or pink on hardware. Temperature
  is deliberately not represented by LED colours.
- Add an independent, opt-in **experimental SteamOS top-bar** weather icon and
  temperature, selectable in Celsius or Fahrenheit. It hides unavailable or
  stale readings and removes itself when disabled. It has worked on one Steam
  Machine, but relies on a private Steam UI layout that may change.

### Settings and presentation

- Use the supplied configuration's global choices as fresh-install defaults,
  except that Snow takes hold is selected for snow. Existing saved settings
  remain unchanged. Personal per-game profiles from the supplied configuration
  are not distributed to other users.
- Add **Import configuration JSON** in Advanced / debug, with a file picker,
  validation, and confirmation before replacing global settings and per-game
  profiles. Invalid files leave the current settings untouched.
- Add a separate confirmed **Reset to defaults** action. Import and reset stop
  a running personal timer and temporary previews, but do not delete exported
  JSON or cached artwork.
- Add a Weather GIF captured from the interactive concept simulator, a real
  SteamOS top-bar photo, and an updated online simulator with all 16 weather
  loops. Artwork, Performance, Playtime, Light events and Controllers retain
  their existing behaviour.


## 0.6.0-beta.10 - LOCAL ONLY - 2026-09-23

- Keep fifteen Weather loops: two sun, two moon, two rain, two cloud, two partly cloudy day, two partly cloudy night, one snow and two storm. The original Sun/Moon through clouds loops remain, with a separate fade-out variant for each. Those new variants dim neutral-white cloud LEDs to black while the light appears, without dark brown or blue fringe colours. Rain gains the dimmer Pearl field and another blue accent per impact; snow uses paired and single melt-and-refill gaps; Pulse and echoes gains a second lightning phrase.
- Remove Weather temperature LEDs, thermometer, Celsius/Fahrenheit and threshold controls, Soft weather halos and Fixed colour test. Old saved values for removed settings are discarded on the next save. Retained Moon, Rain and Storm variant selections migrate when possible. Weather brightness and faint-LED cutoff remain available.
- Add an opt-in experimental SteamOS top-bar weather icon with the current temperature in °C. It works independently of the LED/weather or controller display, hides stale/unavailable readings, and removes itself when disabled or unloaded. Placement before the clock (or fallback icon row) uses an undocumented Steam UI structure and needs physical SteamOS testing. Temperature is fetched solely for this text indicator, never mapped onto LEDs.
- Tests and package validation are local only. No GitHub push or release.

## 0.6.0-beta.9 - LOCAL ONLY - 2026-09-23

- Replace the weather animation set with the latest approved mockup: two sun, five moon, four rain, two cloud, two snowy, five storm, and separate two-variant partly cloudy day/night loops. Use yellow/lemon sun rays, neutral silver/cloud/snow, blue rain, and white lightning instead of dim brown, blue-grey, or violet tails.
- Add separate night-time partly cloudy rendering for Open-Meteo code 2, including an ivory moon and two alternating clearings.
- Add temperature placement choices: one or two LEDs at both ends, one LED at either end, Off, or a brief thermometer after each uninterrupted eight-second weather loop. The thermometer fills across the 17 LEDs using the saved Cold-to-Hot range, then fades over 1.6 seconds.
- Keep existing temperature thresholds, colours, Celsius/Fahrenheit choice, brightness, faint-pixel cutoff, weather/controller exclusivity, and higher-priority signals. Migrate saved endpoint width to the equivalent new choice. Old out-of-range animation selections fall back to the first current variant.
- Update the Decky labels and saved-configuration summary. Local automated tests pass; physical colour and timing still require Steam Machine validation. No GitHub publication.

## 0.6.0-beta.8 - LOCAL ONLY - 2026-09-23

- Add Soft weather halos to all 35 animations, enabled by default and reversible for comparison with beta.7.
- Reduce colour casts in dim halos by subtracting excess RGB components, not adding white. Remove very faint tails wherever the animation moves instead of masking fixed LEDs at the ends of the bar.
- Never increase any RGB channel. Preserve bright accents exactly before brightness scaling, plus the independent temperature signature, fixed colour diagnostics and all other SignalBar modes. Weak details may dim or disappear; physical colour fidelity remains unverified.
- Show the selected halo treatment in Weather settings and the saved configuration summary. Retain existing brightness, cutoff, colours and temperature thresholds.
- Add all-variant/full-cycle checks for subtractive-only output and unchanged bright accents/temperature tips, plus persistence and raw-test isolation checks. No GitHub publication.

## 0.6.0-beta.7 - LOCAL ONLY - 2026-09-23

- Remove Weather's extra gamma curve for all 35 animations. At brightness 100% and cutoff 0, final RGB processing is now exactly neutral.
- Replace shadow remapping with an explicit faint-LED cutoff: pixels at or below the cutoff turn off; surviving pixels are not dimmed further. Existing brightness/cutoff values are preserved, but their effect changes and the bar may appear brighter than in beta.6. Higher cutoffs can make transitions more abrupt.
- Add fixed Light Events gold/white tests at 5%, 10%, 20%, 35%, 50%, 75% and 100%, on three centre LEDs or the full bar. Each lasts 12 seconds, shows the exact RGB requested and supports manual stop. Tests bypass weather brightness, cutoff and temperature tips without changing saved settings.
- Preserve countdown, alert and Steam ownership priorities. Steam's master brightness and the recording marker still apply; stop recording before comparing colours.
- Retain current animation geometry pending hardware observations. This build enables a controlled low-intensity/diffusion comparison; it does not claim a measured colour calibration or a confirmed physical fix.
- Include previous weather, temperature-unit and HTTPS fixes. No GitHub publication.

## 0.6.0-beta.6 - LOCAL ONLY - 2026-09-23

- Add adjustable Cold, Mild and Hot weather temperature anchors, with ordered bounds and persistent settings. Preserve the previous −10°C / 15°C / 40°C defaults.
- Add Celsius/Fahrenheit selection for weather readings, threshold controls, the quick panel and saved configuration summary. Store thresholds in Celsius internally so switching units never changes the LED colours.
- Keep colour blending between anchors and clamp to the Cold/Hot colour outside them. Performance temperature units are unchanged.
- Include the beta.5 colour fixes and beta.4 HTTPS fix. No GitHub publication.

## 0.6.0-beta.5 - LOCAL ONLY - 2026-09-23

- Rework sun and moon colours using the Light Events gold, champagne and white palette and its bounded RGB blending. Remove the brown sun background and saturated blue moon layers rather than merely dimming them. Keep the animation motion and breathing.
- Golden Swell now uses gold across its breathing halo; Silver Hush uses the same near-neutral white throughout its centre and outer halo. Blue Hour uses pale ice-white instead of deep blue.
- Add Off to the temperature endpoint selector so the animation can be viewed without the independent temperature colours. Existing one- or two-LED selections are preserved.
- Clarify that Weather brightness/shadow controls are not a measured hardware colour calibration. Light Events and the shared hardware writer are unchanged.
- Add full-cycle RGB regression checks, Light Events blend parity, and temperature-marker isolation/persistence tests. Physical colour fidelity still requires Steam Machine testing.
- Include beta.4's verified-system-CA fix for weather requests. No GitHub publication.

## 0.6.0-beta.4 - LOCAL ONLY - 2026-09-23

- Fix the weather city-search and forecast failure reported on SteamOS as `SSL: CERTIFICATE_VERIFY_FAILED` by retrying with the operating system's trusted CA bundle when Decky's embedded Python cannot find the issuer.
- Keep HTTPS certificate and hostname verification enabled; never fall back to an unverified connection.
- Add regression tests for a simulated missing-issuer failure and verify both city search and current weather through that recovery path locally. Real Steam Machine confirmation remains pending.

## 0.6.0-beta.3 - LOCAL ONLY - 2026-09-23

- Calibrate Weather RGB for the physical Steam Machine diffuser: dim midtones and fade dark brown/blue backgrounds toward black while keeping brighter animation accents.
- Add Weather-only LED brightness and shadow cutoff controls, plus direct night/daylight previews beside them. Other modes and Steam's master brightness are untouched.
- Keep the RGB preview aligned with the values actually written to the bar. The exact physical appearance still needs device testing.

## 0.6.0-beta.2 - LOCAL ONLY - 2026-09-23

- Add an optional country field to city search. Use the full country name after
  the city name; two-letter codes do not return results in this search.
- Return a clear backend diagnostic when city search fails, so a Decky/network error is distinguishable from an empty result.
- Exercise the real asynchronous Decky search entry point in automated tests and verify live city plus weather responses locally. Steam Machine networking still needs device validation.

## 0.6.0-beta.1 - LOCAL ONLY - 2026-09-23

- Add opt-in local weather using manual city search and Open-Meteo current conditions, with no automatic location detection or API key.
- Add five selectable LED loops each for clear day, moon and stars, rain, cloud, sunny intervals, snow, and storm, plus a one-cycle preview.
- Add a steady one- or two-LED temperature signature at both ends of the bar, with customizable cold, mild, and hot colours.
- Let weather appear on Home, in game, or everywhere. Permanent weather and the permanent controller battery gauge automatically turn one another off; the controller gauge remains the fresh-install default.
- Keep countdowns, brief alerts, Steam's LED ownership guard, and the recording marker above a permanent weather signal. Suspend stale weather instead of displaying it as current.
- Keep this beta local for device testing; stable v0.5.1 and GitHub are unchanged.

## 0.5.1 - 2026-09-23

Patch release focused on clearer documentation and a configuration export that
can be retrieved directly in SteamOS Desktop Mode.

- Streamline the README opening so the short product description and v0.5.1
  download lead directly into the main display modes.
- Rename the Advanced / debug summary to **Saved configuration** and add an
  explicit **Export configuration JSON** action.
- Write the export atomically to
  `/home/deck/Documents/SignalBar-configuration.json` on a standard SteamOS
  installation, show the exact resolved path in the panel, and keep the file
  owned by the desktop user even though Decky runs the backend as root.
- Group global settings, every saved per-game Display and Artwork profile, and
  the current game's resolved choices in the exported document. Controller
  device identifiers and runtime hardware diagnostics are not included.
- Refine the controller-battery README animation for a smaller download and a
  softer LED glow.

## 0.5.0 - 2026-09-23

Official release. Changes since 0.4.0:

### Controller battery signals

- Detect already-connected controllers from SteamUI's SteamInputManager service,
  listen for live connection and battery notifications, and recover with a
  background two-second poll. Disconnects clear stale device state.
- Keep live battery updates ahead of older controller-list snapshots, including
  after a list reorder or a late query. Unknown readings are not shown as zero
  or an invented exact percentage.
- Add an optional persistent battery gauge: Off, On Home, or Everywhere. Two
  controllers use mirrored eight-LED gauges, an unlit centre LED, and fixed
  white endpoints once the introductory animation has finished.
- Add brief connection and low-battery alerts, with independent Home/in-game
  visibility and a configurable low-battery threshold. Alerts are event-driven,
  not replayed on every poll; a controller present at startup does not create
  a false connection animation.
- Add one exclusive charging choice: Off, Brief, Continuous on Home, or
  Continuous everywhere. Continuous movement stops when charging stops or
  reaches 100%, with a short completion cue at full charge. Charging requires
  Steam to report both a usable battery level and a charging state.
- Offer three visual variants for connection, a single gauge, low battery,
  charging, and the two-controller introduction. Keep the charging half blue
  and its moving/endpoint highlights white in the two-controller display.
- Add four controller colour pickers and controller-only brightness. Previews
  show sample data and do not claim that a physical controller was detected.

### Display, sensors and interface

- Add a per-game Artwork or Performance display choice with Use default to
  remove the override. The global Disabled setting still overrides profiles.
- Collect CPU/GPU data independently of the active display, so Performance
  settings show fresh data without first switching to Performance. Clear
  failed or expired readings instead of leaving misleading stale values.
- Add a compact configuration snapshot in Advanced / debug for photographing
  saved choices across every tab, including global versus per-game Artwork.
  Keep device paths and controller identifiers out of this snapshot.
- Remove the duplicate live LED preview at the top of Light events; the
  previews beside individual animation controls remain.

### New-install defaults and documentation

- Set fresh installations to the approved configuration: Performance with
  mirrored CPU + GPU, Balanced response and Home display; classic temperature
  colours with 45°C/78°C thresholds; Library Hero/Auto Artwork; a white
  Steam Families countdown and 60-minute personal timer.
- Enable Light events with Return beacon notifications, Chromatic rebound
  achievements, Expanding echoes screenshots, and an isolated recording LED.
- Set the controller gauge and continuous charging to Home, brief alerts to
  Home + in game, Bright tip for a single gauge, Tidal fill for charging,
  Mirror greeting for two controllers, and 65% controller brightness.
- Existing stored preferences remain intact on upgrade. Refresh the README
  and capture a new controller GIF from the visual mockup.

Known limit: controller reporting uses private Steam interfaces and depends on
the controller and connection type; a full hardware compatibility list is not
yet available. Automated tests cover the integration paths, but cannot prove
every Steam Machine/controller combination.

## 0.5.0-beta.10 - LOCAL ONLY - 2026-09-23

Not published. Remove the duplicate live LED preview at the top of Light
events. Category-specific previews remain beside their animation controls.

## 0.5.0-beta.9 - LOCAL ONLY - 2026-09-23

Not published. Adds a photo-friendly configuration snapshot to Advanced / debug.

- Show the saved choices from Display, Artwork, Performance, Playtime, Light
  events, Controllers, and Advanced in one grouped, read-only summary.
- Distinguish global Artwork defaults from the current game's saved profile.
  Include inactive options so the summary can help choose future defaults.
- Keep device paths and controller identifiers out of this new summary; technical
  telemetry remains below it in the existing debug details.
- Add frontend coverage for the summary and backend coverage for the exposed
  global Artwork defaults.

## 0.5.0-beta.8 - LOCAL ONLY - 2026-09-23

Not published. Clarifies and separates controller charging behavior.

- Replace the overlapping charging switches with one exclusive choice: Off,
  Brief (about 3 seconds), Continuous on Home, or Continuous everywhere.
- Brief charging follows the brief-alert master switch and location. Continuous
  charging remains independent and stops if Steam stops reporting charge or
  reports 100%, when its short completion cue plays.
- Migrate previous beta settings to the closest new choice. Keep the legacy
  fields derived for compatibility with older local builds.
- Require a usable battery level before starting a brief charging cue.
- Audit the Controllers copy to distinguish measured battery data from sample
  previews, explain priority and startup limits, and show charging in the quick
  panel with its actual colours.
- Add tests for migration, exclusive behavior, duration and return to the base
  display. No GitHub push or release.

## 0.5.0-beta.7 - LOCAL ONLY - 2026-09-23

Not published. Fixes two-controller charging colours.

- Tint the charging controller's half of the mirrored gauge with the selected
  charging blue, while preserving white motion and endpoint cues. The other
  controller keeps its normal battery colour, and the centre LED stays off.
- Apply the same rule during the second-controller connection introduction, not
  just the continuous charging display. If both controllers charge, both halves
  use their own blue-and-white motion.
- Add regression tests for left, right, both, and all three charging styles.

## 0.5.0-beta.6 - LOCAL ONLY - 2026-09-23

Not published. Fixes the two-controller preview feedback from beta.5.

- Use white moving points, rather than blue and yellow, in Two signatures and
  Mirror greeting. Keep the fixed white battery endpoints for the completed
  introduction, with the centre LED off throughout.
- Extend the two-controller preview to six seconds so the settled white tips
  remain visible long enough to inspect. The persistent two-controller gauge
  keeps them visible after the preview when enabled.
- Add a regression test for left and right white motion, endpoint timing and
  the final hold.

## 0.5.0-beta.5 - LOCAL ONLY - 2026-09-23

Not published. Controller motion update based on the latest visual prototype.

- Add independent Off / On Home / Everywhere choices for a continuous charging
  animation. It stops at 100%, plays a brief completion cue, then restores the
  prior display. Charging can work without enabling the permanent gauge.
- Rework the three connection, low-battery, charging and two-controller visual
  styles to follow the motion prototype. Existing saved style IDs are retained.
- Make the two-controller gauge consistently mirrored. Keep the centre LED off;
  add white tips at the actual battery endpoints only after the intro finishes.
- Show charging movement on its own half when two controllers are connected.
- Add regression tests for intro timing, 96%/41% mirrored levels, continuous
  charging, 100% completion, and Home versus in-game visibility.
- No GitHub push or release for this local beta.

## 0.5.0-beta.4 - LOCAL ONLY - 2026-09-22

Not published. Includes fixes for the user's beta.3 hardware feedback.

- Fix a live controller battery reading being replaced one or two seconds later
  by an older controller-list snapshot. Live battery events are retained for
  the device connection, across polling and list order/index changes. Disconnect
  clears them, so a replacement controller does not inherit another's battery.
- Seed already-connected controllers from SteamUI's read-only controller state,
  matching by device identity. Once a live battery event arrives, it takes
  precedence over both list and UI snapshots.
- Add per-device diagnostics: list percentage, SteamUI percentage, latest battery
  event, chosen percentage, source and event age. No raw device serial is shown.
- Add colour pickers for healthy, medium, low and charging/connection colours.
  Add controller-only brightness from 10 to 100%, default 65%, with saturated defaults
  to reduce the diffuser's pale white-green glow. Single/two-player gauges,
  controller animations and their previews share these settings.
- Collect CPU/GPU metrics every 0.5 seconds independently of Display and LED
  hardware availability. Artwork and Disabled no longer freeze sensor readings.
  Sensor failures clear old values; expired readings are not presented as live.
- Add per-game Display profiles: Use default, Artwork or Performance. Launching
  another game or returning Home resolves its own choice; global Disabled still
  overrides everything. Existing per-game artwork sampling is unchanged.
- Extend regression tests for the exact 96%/41% versus 96%/100% case, SteamUI
  startup readings, profile persistence/arbitration, colours and sensor lifecycle.

## 0.5.0-beta.3 - LOCAL ONLY - 2026-09-22

Not published. Real Steam Machine / Steam Controller validation is still required.

- Replace the obsolete SteamClient.Input controller-list/battery listeners with
  SteamUI's current SteamInputManager service. Discover it by its named service
  descriptor, not a hard-coded webpack module number.
- Query already-connected controllers at plugin startup, listen for roster,
  battery and disconnection notifications, and read the list every two seconds
  as a recovery mechanism. Resume requests a fresh reading.
- Read the actual controller_index, battery_level, is_charging and charging
  fields. Battery values 0 to 100 are percentages; missing/sentinel data stays
  unknown. No input/calibration feed or direct HID access is used.
- Preserve device identity when the index changes; do not carry battery values
  to another controller that reuses an index. Reject obsolete in-flight roster
  responses and retain newer battery events.
- Expose service connection state, hook count, query/event counters, response
  latency and error details. Distinguish an empty response from a failed read.
- Expire stale live data after ten seconds. Retry service discovery, missing
  hooks and backend delivery without opening the settings panel.
- Warn once if the initial reading is already low, and do not consume warnings
  while disabled, in the wrong context or blocked by a critical countdown.
- Fix the Tip gauge crash at zero/unknown charge. Update active animations from
  the latest reading and recognise unknown-to-charging transitions.
- Add lifecycle/race tests and an optional contract test loading the installed
  Steam generated service wrapper with a simulated transport. This validates
  the interface, not physical hardware compatibility.

## 0.5.0-beta.2 - withdrawn, unsuccessful - 2026-09-22

The attempted fix below did not restore detection on the user's Steam Machine.
Its release and remote tag were removed. These notes describe the attempt, not
a verified fix; beta.3 replaces this outdated callback path.

- Attempt to fix live controller telemetry on older SteamUI. Its battery callback sends
  levels as an ordered array matching the latest controller-list callback;
  beta.1 incorrectly expected an index/value pair and discarded the update.
- Read SteamUI's `ucBatteryLevel` percentage field when it is already present
  on a controller-list item.
- Preserve battery snapshots that arrive before the initial controller list and
  apply them as soon as that list establishes the correct ordering.
- Forward unchanged battery callbacks to Advanced / debug so the callback
  source and age can confirm that Steam is delivering telemetry.
- Stop registering the high-frequency controller-state callback. It is intended
  for live input/calibration data and is unnecessary for battery monitoring.

## 0.5.0-beta.1 - 2026-09-22

- Add experimental Steam controller battery signals: connection, low battery,
  charging, a permanent single-controller gauge, and a split two-controller
  gauge with the centre LED off.
- Offer three selectable visual styles for each of the five situations and
  immediate preview buttons that do not require a connected controller.
- Separate the permanent gauge (Off, On Home, Everywhere) from brief-alert
  locations (Off, On Home, In game, Home + in game). Alerts work even while the
  permanent gauge is off. Both categories preserve the selected base display
  after their signal ends.
- Detect controller-list, battery, and controller-state changes from Steam's
  frontend callbacks; serialize state updates to avoid stale asynchronous
  snapshots replacing newer readings.
- Warn once when a known battery crosses a configurable threshold from 5 to 30%, or
  reaches Steam's lowest coarse level, and re-arm after charging. Never present
  a coarse battery level as a fabricated exact percentage.
- Keep Steam Families' final five minutes protected. Low-battery alerts have
  priority over ordinary short events, while native LED writes interrupt active
  animations. A permanent gauge never overrides a countdown or Disabled mode.
- Add a Controllers settings page, live logical preview, controller readout,
  callback-source diagnostic, new README section, and a captured
  controller-battery GIF.
- This is an opt-in beta for the permanent gauge. Steam's private controller
  callback payloads and controller-model compatibility still need physical
  Steam Machine testing.

## 0.4.0 - 2026-09-21

- Add opt-in Light events for Steam notifications, achievements, screenshots,
  and recording start/stop, with 14 selectable notification, achievement, and
  screenshot animations plus local previews beside every control.
- Detect every valid Steam notification type, use the achievement notification
  for unlock celebrations, watch for newly written screenshots, and track
  recording state through SteamClient callbacks.
- Let short event animations run outside games, interrupt them on a new native
  LED write, and restore the verified live display afterward.
- Protect the final five countdown minutes from transient events and preserve
  the existing Steam Families, personal timer, and selected base-display
  priority rules.
- Keep a pure red centre LED visible while recording over Artwork or
  Performance. Neighbour isolation is enabled by default to prevent diffuser
  bleed, and the marker never modifies a countdown or another event animation.
- Reorganize settings into dedicated Artwork, Performance, Playtime, Light
  events, and Advanced pages with a compact quick-access status panel.
- Remove duplicate Performance previews from the quick panel. Show CPU/GPU
  load and temperature with one logical preview, and only show the game image
  when Artwork is selected.
- Place the Artwork image and source label directly above its logical preview.
  Preserve the full Hero, Header, or Capsule aspect ratio without cropping.
- Draw a red horizontal guide over the Artwork image while adjusting a manual
  sample row.
- Prefer locally installed Steam custom-grid artwork, including SteamGridDB
  replacements, and support Hero, Header, or Capsule artwork for non-Steam
  shortcuts without requiring an API key or network request.
- Add an optional always-on Performance mode for the Steam home screen while
  retaining native LED ownership protection.
- Add Responsive, Balanced, and Smooth meter filtering, CPU/GPU/mixed layouts,
  selectable mixed fill direction, and shared physical diffuser compensation.
- Add custom Cool, Middle, and Hot performance colours through Decky's native
  colour picker alongside the three built-in temperature palettes.
- Show active Steam Families and personal countdown time with a live 17-LED
  preview at the top of the Playtime page.
- Change the default Extra dark LEDs calibration from three to two and replace
  the quick-access Wi-Fi-like icon with the stock Tabler `TbCubeSpark` icon.
- Replace the README with the new visual presentation and animated examples for
  Performance, Countdown, Notifications, Screenshots, Achievements, and
  Recording.

## 0.4.0-beta.4 - 2026-09-21

- Restore live CPU/GPU load and temperature readings in the quick Decky panel
  whenever Performance is the selected base display.
- Move an active Steam Families or personal countdown to a prominent live
  preview at the top of the Playtime page, including its remaining time.
- Put a local live LED preview beside every Light events preview control so
  animations remain visible even at the bottom of the settings page.
- Keep the recording marker as a pure red centre LED over Artwork or
  Performance, never over countdowns or transient event animations.
- Add an optional recording-marker isolation setting that turns the two
  neighbouring LEDs black to reduce optical colour bleed.

## 0.4.0-beta.3 - 2026-09-21

- Show the running game's artwork in the quick Decky panel, regardless of the
  selected LED display mode.
- Preserve the full image in Artwork settings and the quick panel, including
  wide headers and vertical capsules; neither preview crops the source image.
- Ignore late artwork responses from a previous game or image-source selection.
- Build and automated tests pass; the revised layout still needs a Steam
  Machine/Decky visual check.

## 0.4.0-beta.2 - 2026-09-21

- Add all 14 notification, achievement and screenshot variants from the two
  animation mockups, while retaining the three beta.1 patterns as choices.
- Save one animation selection per event category and keep queued events on
  the variant that was selected when they arrived.
- Make previews play immediately without enabling live events or changing the
  saved selection; recording previews do not change recording state.
- Split the Decky UI into a quick mode/status panel and dedicated Artwork,
  Performance, Playtime, Light events and Advanced settings pages.
- Keep the existing event priority, protected final five countdown minutes,
  native-write interruption and physical LED ownership safeguards.
- Automated tests cover each 17-LED variant and settings persistence; hardware
  behaviour still needs verification on an official Steam Machine.

## 0.4.0-beta.1 - 2026-09-21

- Signal every valid Steam notification type, including Community comments and
  types added later. Do not suppress later notifications because Steam reused a
  list index, and do not ignore real events during plugin startup.
- Add short, exclusive light signals for Steam notifications, unlocked
  achievements, newly written screenshots, and recording start/stop events.
- Make cyan notifications traverse all 17 LEDs; make achievements celebrate with
  three amber beats, a white-gold burst, an outward sweep and a full-bar glow.
- Temporarily suspend the base Artwork, Performance or playtime display while
  an animation plays, then restore its current frame without pausing its timer.
- Keep the final five minutes of every countdown protected: transient events
  are skipped instead of hiding the red warning or last-eight-second flashes.
- Keep the centre LED red while recording over Artwork or Performance, never
  over a countdown. Add an opt-in master switch, per-category switches and
  local preview buttons.
- Play light events outside games and let them briefly take over a stable
  Valve/system LED frame. Restore that exact frame afterward if still owned;
  cancel the animation if a new native write occurs. Disabled still wins.
- Sample active animations at 60 ms intervals (normal providers remain at
  100 ms) so the cyan crossing can reach the full 17-pixel span.
- Add animation, Steam-event mapping, priority and recording-state tests.
- Beta limitation: SteamClient event callbacks still need verification on the
  official Steam Machine; this build is not a stable release.

## 0.3.2-beta.1 - 2026-09-21

- Prefer artwork installed locally through Steam's custom grid (including
  SteamGridDB) over the unmodified Store image for the same game.
- Support custom Hero, Header and Capsule images for non-Steam shortcuts, with
  an available custom image as fallback when the selected role is missing.
- Read the active Steam account's custom grid when known, without showing
  another account's images; accept signed 32-bit shortcut AppIDs from SteamUI.
- Keep artwork discovery local and read-only; no SteamGridDB API key or network
  request is required.

## 0.3.1 - 2026-09-20

- Extend the existing **Extra dark LEDs** optical calibration to Performance
  as well as Playtime Countdown, retaining the default value of three.
- Keep Decky's Performance preview logical while writing the compensated LED
  count to hardware; e.g. 12 cells in the preview become 9 physical LEDs with
  compensation 3.
- Share one compensation across the two halves of the mixed CPU/GPU meter
  instead of subtracting it independently from each half. Each active half
  retains at least one physical LED. Artwork remains unchanged.
- Show the live logical-to-physical Performance mapping in Debug.
- Add Responsive, Balanced and Smooth meter-response profiles for CPU and GPU,
  with Balanced as the default.
- Filter the displayed percentage and LED length from the same value. Balanced
  limits movement over time, accepts sustained rises progressively, requires
  two lower samples before falling and then decays more slowly to prevent
  one-sample spikes from making the bar oscillate.

## 0.3.0 - 2026-09-20

- Start game detection, Artwork sampling, Performance activation, Steam
  Families observation, download ownership and suspend/resume handling as soon
  as Decky loads the plugin; opening SignalBar's settings is no longer required.

- Re-register Steam Families remaining-time observation when a game launches,
  keep parental time above personal timers and both base display modes, and
  hide parental time while no game is running.
- Cancel parental state immediately when its setting is disabled, the game is
  closed or another game starts, including during the final flash sequence.
- Clear stale running-game state on termination and resume from suspend instead
  of restoring Artwork from the last game.
- Move Playtime countdown below Performance in the Decky panel.
- Use constant pure red during the final five minutes and keep only the
  right-to-left circulation, avoiding two simultaneous animations.
- Repeat three brief full-white flashes during the final eight seconds of a
  countdown, then return immediately to the selected base provider at zero.
- Add optical dark-edge compensation for the Steam Machine's diffused light
  guide while retaining all 17 pixels at a full countdown.
- Make that physical compensation persistent and adjustable from 0 to 6 under
  Debug. The Decky preview retains the logical count: 12 shown with a value of
  3 writes 9 lit LEDs to the hardware. It applies only to countdown frames,
  never Artwork or Performance.
- Add a selectable countdown scale: start full, or map the full 17-pixel bar to
  1, 2, 3 or 4 hours. Longer remaining times stay full until that window.
- Move Debug to the bottom and replace raw monotonic values with useful ages,
  separate cooldown/stability timers, game detection source, backend sync time
  and Steam Families callback waiting/received latency.

- Added a temporary playtime countdown that automatically returns to the
  selected Artwork or Performance display when it ends.
- Added Steam Families remaining-time support through SteamUI's parental
  playtime callback, with an independent enable/disable setting.
- Added a free personal timer from 5 to 240 minutes that continues while the Decky
  panel is closed, plus a non-destructive 15-second preview.
- Added five starting colours, a shrinking right edge and a right-to-left
  travelling highlight. The signal turns amber below 15 minutes, then pure red
  below five minutes while circulation continues at constant brightness.
- Added deterministic provider, priority, direction, colour and persistence
  tests for the countdown feature.

## 0.2.1 - 2026-09-20

- Replaced Automatic with explicit Artwork, Performance and Disabled modes;
  existing Automatic settings migrate without losing their former priority.
- Added per-game Library Hero, Header or Capsule selection and replaced the
  technical cache filename in the panel with the running game's title.
- Added two mixed CPU/GPU fill layouts: both halves left-to-right, or mirrored
  from the outside edges toward the black centre separator.

## 0.2.0 - 2026-09-20

- Persisted Artwork row mode and manual position independently for every AppID;
  untouched games continue to use the global default.
- Corrected the official Steam Machine's physical LED direction while keeping
  software previews left-to-right, with a Debug override.
- Added CPU, GPU and mixed performance displays. Mixed is CPU 8 + black centre
  separator + GPU 8, with both halves growing inward.
- Added three temperature colour palettes and renamed the ambiguous Cool/Hot
  colour controls to Cool/Hot temperature with inline explanations.
- Made Automatic's Performance-over-Artwork priority explicit in the UI.
- Replaced the inaccessible native Debug details element with a focusable
  SteamOS toggle in the top Status section.

## 0.1.0 - 2026-09-20

- Added Valve-first Vanilla Guard with external-change detection, cooldown and
  stable-window recovery.
- Added the Providers → Arbiter → Renderer backend architecture.
- Added local Library Hero discovery, automatic/manual band selection,
  17-colour preview and persistent artwork cache.
- Added a GPU load/temperature meter using local DRM and AMDGPU hwmon data.
- Added compact Decky status, mode, artwork, performance and debug sections.
- Added fail-closed hardware handling, settings persistence, targeted tests and
  reproducible Decky ZIP packaging.
