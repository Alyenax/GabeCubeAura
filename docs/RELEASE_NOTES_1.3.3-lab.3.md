This Lab build gives GabeCubeAura one coherent brightness control, independent
from everything displayed on the light bar.

### New: global light bar brightness

- Set one direct Day brightness from 1 to 255 for every Home and in-game route.
- Optionally dim that value after sunset using the selected city's exact solar
  times. The default `9/255` at 35% produces `3/255` at night.
- See the current Day, Night, alert or Valve output directly in Display
  routing.
- Changing a preset or display route never changes brightness.

### New: physical setup previews

- Preset selection runs the real Home recipe for ten seconds on the physical
  17-LED bar. Audio Sync uses live audio, and the on-screen strip mirrors the
  same engine frames.
- Day and Night sliders preview their hardware result immediately.
- The three setup pages now scroll above Steam's Menu / A Select / B Back
  footer.

### Safety and compatibility

- Important alerts temporarily use Day brightness.
- Thermal protection still returns complete control to Valve immediately.
- Every normal Valve or download handoff restores Steam's exact saved
  brightness, including after an interrupted day/night transition.
- Drivers without `brightness_scale` use the existing RGB fallback and report
  it clearly.
- Follow Steam Brightness has been removed because Steam's slider cannot track
  the bar while GabeCubeAura owns it.

Existing installations keep their visual output and do not see onboarding
again. This is a private Lab prerelease for target-hardware validation; the
public Stable channel remains unchanged.
