GabeCubeAura 1.4.0 makes the first configuration easier, gives brightness one
clear place in the interface and replaces the fixed-red restriction with real
CPU and GPU thermal protection.

## New features

### Guided first-time setup

- Choose Moderate, Atmosphere, Signals or Immersive in a full-screen Decky
  setup.
- Preview each choice on the physical 17-LED bar before applying it.
- Set Day brightness, optional sunset dimming and the exact city used for
  sunrise and sunset times.
- Review the complete setup before saving it. Existing users keep their saved
  routing and visual settings without seeing onboarding again.

### One global Day/Night brightness control

- Day brightness now applies to every Home and in-game display. Presets and
  routes never overwrite it.
- Optional Night brightness is calculated as a percentage of Day brightness
  and changes automatically at local sunset and sunrise.
- Weather does not need to be selected for automatic night dimming to work.
- Values below 8/255 show a clear warning because they can strongly affect the
  lighting experience.

### Real thermal protection

- At 94°C or higher on either the CPU or GPU, GabeCubeAura stops every
  animation and hardware write, then returns complete light-bar control to
  Valve immediately.
- GabeCubeAura stays disabled until both coherent readings remain below 90°C
  for 30 continuous seconds.
- Missing or incoherent sensor data during an active thermal alert keeps the
  plugin disabled.
- Fixed red is available again for ordinary effects. The protection is based
  on temperature, not colour.

### Weather-first Atmosphere

- Atmosphere now uses Weather as its Home display.
- If no current weather frame is available, it falls back to Slow Prism with
  Screen Sync colours and returns to Weather automatically when data recovers.

## Major fixes

- Remove Follow Steam Brightness, which could not follow Steam's slider while
  GabeCubeAura owned the bar. GabeCubeAura now controls its own brightness and
  restores Steam's exact saved value during a Valve handoff.
- Make brightness transitions and interrupted-write recovery safe without
  overwriting a newer Steam value.
- Keep thermal protection above every preview, permanent display and temporary
  layer.
- Make Signals and Immersive onboarding previews visible without requiring a
  paired controller, live audio, artwork or Gamescope capture.
- Restore Stable updates every 24 hours after first setup and remove any saved
  Private Lab authorization.

## Minor fixes

- Reorder presets so Lights out, Essential and Focus appear first.
- Clarify that Lights out excludes even Valve's download animation while
  Essential still allows confirmed downloads.
- Move Light bar brightness to the end of Display Routing.
- Hide TW3-SteamRGB and StripMine ownership controls behind one optional
  compatibility toggle.
- Report RGB attenuation clearly when the driver does not expose
  `brightness_scale`.

## Installation

Download `GabeCubeAura-v1.4.0.zip` and install it through Decky Loader without
extracting it. `GabeCubeAura.zip` is the identical fixed-name archive used by
the updater and recovery flow. SHA256 values are provided in `SHA256SUMS`.
