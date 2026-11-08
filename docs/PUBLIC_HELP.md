# GabeCubeAura

Steam Machine light bar and optional JSAUX PIXEL Faceplate. Configure lighting from Decky's quick panel or Settings. With no Faceplate connected, only general and light-bar controls are shown. Your choices survive disconnection.

Decky Vocal Assistant provides optional voice functions;
[Decky Animated Screensaver](https://github.com/Alyenax/Decky-Animated-Screensaver)
provides animated TV screensavers. Each plugin is configured separately.
GabeCubeAura works without either plugin.

Diagnostics: Settings > Advanced > Diagnostics > Export a local diagnostic. The report is redacted and saved privately under Documents. Nothing is uploaded. For capture failures, enable the optional five-minute capture diagnostic before reproducing the problem, then export the report. Detailed capture traces expire automatically.

Configuration export/import is separate from support diagnostics. It preserves calibration references and profiles and may contain your selected city. Creation export saves the prepared artwork locally. Share those files only deliberately.

Brightness is global and immediate. Off remains non-destructive. Experimental integrations keep their opt-in status and fallbacks. A USB acknowledgement is not an optical or endurance measurement.

Automatic update checks are enabled by default, every 24 hours. Downloading and installation remain manual. A saved opt-out is preserved; resetting settings restores automatic checks.

New updater limits: 1 GiB ZIP, 4 GiB extracted, 32768 entries. Streaming, disk reserve, checksums, staging and recovery are preserved.

First start and Settings Reset require guided setup and final confirmation. Keep initial settings retains the lighting calibration. Setup starts Home on Dashboard Weather without a Home selector. No starter artwork, city or personal API key is supplied. Create and apply your own Home artwork in Settings → Faceplate JSAUX → Artwork.

When no weather city is configured or weather data cannot be used, weather-backed Faceplate displays use a neutral background and unknown weather readings. Saved display choices are preserved. After a host or USB restart, automatic power-on waits for a confirmed current display; this prevents replaying an old autonomous screensaver.

Artwork: in Adjust image, layouts with a separate logo offer Logo size from 50% to 100%, in 5% steps. 100% keeps the normal rendering. The size belongs to the prepared creation; prepare a new preview and apply it. Moving the slider does not send an image to the panel. A logo already embedded in the original source cannot be resized independently.

Follow GabeCubeAura automatically defaults to On on a fresh installation and after resetting settings. Settings-only reset forgets the Faceplate setup and its saved routing choices. After general setup, plugging in an unconfigured Faceplate offers its own setup again in Decky, including after restarting GCA. Saved creations remain in the library; their existence does not mark the connected device as configured.

Decky's quick panel shows Preparing image… and Transferring to Faceplate… with Please wait. beneath the JSAUX selector. A confirmed transfer, a missing final confirmation, a failure or a protection delay replaces the active message. Confirmation describes the USB response, not visible playback. The existing status refresh introduces no additional USB polling. During a pending display recovery, a complete transfer lacking only its final confirmation schedules one full retry after 30 seconds. A second missing confirmation stops automatic attempts; use Power on for an explicit new attempt. The display is relit only after a confirmed replacement.

Artwork Apply ignores a second activation while the first is in progress. Overlapping matching backend requests share one operation, and Home/game promotion is serialized with routing. A full status refresh failure after a completed application no longer reports that the artwork failed to activate.

Version 1.5.0 fixes direct switching between Dashboard Weather and Dashboard Artwork in both directions; no intermediate Artwork selection is needed. After a failed new choice, the panel no longer presents the previous transfer receipt as confirmation of that choice.

The initial setup uses 15/255 light-bar brightness, 70% Faceplate brightness and Economy refresh enabled. No starter artwork is bundled or seeded. Home uses Dashboard Weather in setup; there is no Home selector in the guide. For Home artwork, create and apply your own in Settings → Faceplate JSAUX → Artwork. Existing creations stay intact. Setup remains mandatory and waits for the selected transfer confirmation before closing; a failed or timed-out transfer leaves the guide open to retry. A USB receipt does not prove visible playback.

Confirming setup for a connected Faceplate activates the saved display through the normal power and transfer loop. Not now, an unplugged panel, system sleep and global display Off retain their protections.

Setup waits for the selected display’s USB-confirmed scene and content key before closing. A pending power request or an old confirmed image is insufficient. If confirmation is missing, the guide stays open with an explicit retry message. USB confirmation still does not verify visible playback. The setup confirmation wait is bounded to 90 seconds and stops if the guide is left.

Faceplate Priority is configured only in Settings → Faceplate JSAUX → Priority. Automatic keeps the existing behaviour without reserving the serial port between transfers. GCA Priority retains the USB connection and lets you allow DAS screensavers and DVA temporary faces through GCA. Other app cancels GCA Faceplate work and releases USB after active traffic closes, preserving saved displays, brightness and the light bar. The stored image may continue playing. Sleep and Power off remain separate. An already-open or privileged application may still interfere with terminal exclusion. Companion voice and TV functions remain independent.

## Faceplate clocks

Choose **Clock** for the Faceplate at Home or in game, then **Choose a clock**. Standard models: Meridian, Halo, Almanac, Quadrant, Cardinal markers, Horizon, Column, Week and Date card. Clock colours offers Amber, Glacier blue, Dusty rose, Sage green, Lavender and Ivory. Digital clocks offer 24 hours or 12 hours (AM/PM). Analog clocks use a twelve-hour dial with an optional AM/PM indicator. Dates follow the GCA language. Home and in-game selections, colours and formats are independent.

Clock animations are finite and prepared ahead of their scheduled transfer, roughly every four minutes. Small differences in visible timing can remain. Other app priority, screen-off and suspend rules still apply. Colour changes replace pending clock preparation; an older preparation cannot restore the preceding palette.

Home image extension also follows prepared Home library images without a Steam game. It uses the original image pack, not dashboard text or counters. Missing or changed source files remain ineligible; choosing another source replaces the palette without relaunching GCA.

Standalone clocks support Faceplate image extension. Bottom edge follows the bottom eight rows, which may be black; Whole image includes the dial, time and date. Prepared clock colours are independent of USB confirmation. Confirmed same-session clock renewals avoid an unnecessary Power On command; physical playback continuity still needs checking.

Clock transfer mode is saved separately for Home and games: Fixed minute (default, about 60 transfers/hour) or Conservative (about 15/hour). Existing saved choices are kept. Fixed minute keeps one time/date inside each GIF while animations continue. These rates are nominal; transfer timing and animation continuity require a physical check.

Analog clocks use thin hour and minute hands sharing one native pivot. The five dial styles retain their existing lengths, colours, dates and transfer modes.
