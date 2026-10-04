# Weather in GabeCubeAura 1.3.0

Choose a city in Settings, Weather, then select Weather as the permanent Home
or in-game display. Location is never detected automatically. Current
conditions come from Open-Meteo, refresh about every 15 minutes and expire
after one hour without a successful refresh. No API key is required. Previews
work without a city or network but do not test live weather.

## Animations

Weather offers 22 loops:

- 2 clear-day scenes
- 2 clear-night scenes
- 2 rain scenes
- 4 daytime-cloud scenes
- 4 night-cloud scenes
- 2 partly-cloudy day scenes
- 2 partly-cloudy night scenes
- 2 snow scenes
- 2 storm scenes

The 8 night transpositions in this release preserve the approved daytime motion
while changing the palette and light source:

- Sun glints becomes Breathing moon, with a 6-second loop.
- Solar bloom becomes Lunar bloom.
- The four cloud choreographies gain night versions.
- Sun through clouds becomes Moon through clouds.
- Sun, fading clouds becomes Moon, fading clouds.

Night scenes use the deep-blue field `[0, 8, 38]`, neutral cloud grey
`[35, 35, 35]` and stepped moon whites at 128, 192 and 255. Cloudy live weather
now selects the day or night cloud family from Open-Meteo's day flag. Existing
daytime selections remain unchanged. Night cloud defaults to Night cross &
gather on a fresh install.

Cross & gather lasts 20 seconds and Slow convergence lasts 48 seconds, during
both live playback and preview. Other loops last 8 seconds except Breathing
moon. Weather brightness and faint-pixel cutoff still apply.

## SteamOS top bar

The optional experimental icon and temperature are inserted before the clock
when GabeCubeAura recognizes Steam's current top bar. Celsius and Fahrenheit
affect only that number. No temperature colours are mapped to the LEDs. If the
Steam UI structure is not recognized, GabeCubeAura shows nothing instead of
placing a floating overlay.

This is not a documented Decky top-bar slot and a Steam update may change its
placement.

## Testing

Preview each animation and compare the 17-colour logical bar with the physical
diffuser. Pay particular attention to the deep-blue background at the chosen
brightness, stepped moon whites, black cutoff and the long cloud loops.
Automated tests verify the palette, timing, persistence and frame bounds.
Physical colour and timing still require the official Steam Machine.
