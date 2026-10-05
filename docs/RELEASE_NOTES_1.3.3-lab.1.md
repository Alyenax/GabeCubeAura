This Lab build replaces the fixed-red safeguard with real CPU/GPU thermal protection.

### Thermal protection

- CPU or GPU at **94°C or above** immediately stops GabeCubeAura animations and LED output, restores Valve's saved hardware state and leaves the light bar under Valve control.
- GabeCubeAura stays disabled until **both coherent readings remain below 90°C for 30 continuous seconds**.
- Missing, stale, non-finite or implausible sensor data during an active alert resets recovery and keeps Valve in control.
- The Decky interface clearly reports: `Désactivé temporairement : protection thermique`.
- Fixed red is now available for ordinary lighting; LED colour is no longer treated as proof of a thermal alert.

### Other Lab features

- Add a guided first start with Essential, Atmosphere, Immersive and Immersive+ choices. Existing installations skip the guide and keep their routing.
- Make Immersive+ the explicit fresh-install preset.
- Add optional automatic night brightness from sunrise and sunset at the exact Weather location selected by the user, with no IP geolocation.
- Refresh solar timing at the next sunrise or sunset and disable the option if the saved Weather location is removed.

This is a private Lab prerelease for target-hardware validation. The stable public channel remains unchanged.
