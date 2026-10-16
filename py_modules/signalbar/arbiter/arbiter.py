"""Policy-only selection of the active provider."""

from __future__ import annotations

from signalbar.models import LED_COUNT, ProviderOutput, normalize_frame
from signalbar.providers.events import RED


BLACKOUT_FRAME = normalize_frame([(0, 0, 0)] * LED_COUNT)


class Arbiter:
    @staticmethod
    def _with_recording_marker(base, enabled, isolation):
        if not enabled or base.frame is None:
            return base
        pixels = list(base.frame)
        if isolation:
            pixels[7] = (0, 0, 0)
            pixels[9] = (0, 0, 0)
        pixels[8] = RED
        return ProviderOutput(base.provider + "+recording", normalize_frame(pixels), base.reason)

    @staticmethod
    def _home_assistant_first(tier, *, guard_allows, signal, event, signal_critical, controller_event,
                              home_assistant_base, steam_priority):
        """Tiers 3-5: Home Assistant's alert, then its light, above all of GabeCubeAura.

        Steam's own animations, such as downloads, come first at every tier.
        Below 5 the other critical signals do too: a controller at low battery
        and a playtime countdown near its end.
        None means tier 3 with Home Assistant quiet, so the usual order follows.
        """
        def showing(output):
            return output is not None and output.frame is not None

        alert = event if showing(event) and event.provider == "event:ha" else None
        if steam_priority:
            return ProviderOutput("valve", None, "Steam system priority")
        if tier < 5:
            if showing(controller_event) and controller_event.provider == "controller:low" and not signal_critical:
                return controller_event
            if alert is not None and not signal_critical:
                return alert
            if not guard_allows:
                return ProviderOutput("valve", None, "Valve/system owns the bar")
            if signal_critical and showing(signal):
                return signal
        elif alert is not None:
            return alert
        if showing(home_assistant_base):
            return home_assistant_base
        if tier == 3:
            return None
        return ProviderOutput("none", None, "Home Assistant has nothing to show")

    def choose(self, *, mode, guard_allows, game, performance, artwork, idle,
               signal=None, event=None, signal_critical=False, recording_marker=False,
               recording_marker_isolation=False, performance_always=False,
               controller_event=None, controller_base=None, weather_base=None,
               customization_base=None, screen_sync_base=None, screen_sync_fallback=None,
               audio_sync_base=None, home_assistant_base=None, home_assistant_tier=1,
               launch_artwork=None, steam_priority=False, companion_hud_active=False):
        if mode == "disabled":
            return ProviderOutput("none", None, "GabeCubeAura disabled")
        if home_assistant_tier >= 3:
            first = self._home_assistant_first(
                home_assistant_tier, guard_allows=guard_allows, signal=signal, event=event,
                signal_critical=signal_critical, controller_event=controller_event,
                home_assistant_base=home_assistant_base, steam_priority=steam_priority,
            )
            if first is not None:
                return first
        if steam_priority:
            return ProviderOutput("valve", None, "Steam system priority")
        # Short, opted-in effects can briefly use an otherwise native-owned bar.
        # The runtime still yields if it detects a new external write mid-effect.
        if controller_event is not None and controller_event.frame is not None and not signal_critical and controller_event.provider == "controller:low":
            return controller_event
        if event is not None and event.frame is not None and not signal_critical:
            return event
        if controller_event is not None and controller_event.frame is not None and not signal_critical:
            return controller_event
        if not guard_allows:
            return ProviderOutput("valve", None, "Valve/system owns the bar")

        if signal_critical and signal is not None and signal.frame is not None:
            return signal

        if launch_artwork is not None and launch_artwork.frame is not None:
            return launch_artwork

        if signal is not None and signal.frame is not None:
            return signal

        if weather_base is not None and weather_base.provider == "weather:preview" and weather_base.frame is not None:
            return self._with_recording_marker(weather_base, recording_marker, recording_marker_isolation)
        if customization_base is not None \
                and (customization_base.provider in {"customization:preview", "customization:calibration"}
                     or customization_base.provider.startswith("customization:brightness-preview:")) \
                and customization_base.frame is not None:
            return self._with_recording_marker(customization_base, recording_marker, recording_marker_isolation)

        # TW3 SteamRGB owns the continuous in-game HUD only. GabeCubeAura's
        # opted-in alerts, previews, launch animation and countdowns above
        # retain priority, while every permanent base display yields here.
        if companion_hud_active:
            return ProviderOutput("none", None, "TW3 SteamRGB owns the permanent game HUD")

        # Screen Sync requested by Steam's screensaver temporarily replaces the
        # selected permanent Home display. Brief events and explicit previews
        # above still retain their normal priority.
        if mode == "screen_sync":
            if screen_sync_base is not None and screen_sync_base.frame:
                base = screen_sync_base
            elif screen_sync_fallback is not None and screen_sync_fallback.frame:
                base = ProviderOutput(
                    screen_sync_fallback.provider,
                    screen_sync_fallback.frame,
                    "Screen Sync capture fallback",
                )
            else:
                base = ProviderOutput("none", None, "Screen Sync unavailable")
            return self._with_recording_marker(
                base,
                recording_marker and base.provider.startswith(("screen-sync", "customization")),
                recording_marker_isolation,
            )

        if mode == "audio_sync":
            base = (
                audio_sync_base
                if audio_sync_base is not None and audio_sync_base.frame is not None
                else ProviderOutput("none", None, "Audio Sync unavailable")
            )
            return self._with_recording_marker(
                base,
                recording_marker and base.provider.startswith("audio-sync"),
                recording_marker_isolation,
            )

        # An empty Home Assistant slot gives the bar back instead of falling
        # through to performance or artwork: that is what "off" means there.
        if mode == "home_assistant":
            base = (
                home_assistant_base
                if home_assistant_base is not None and home_assistant_base.frame is not None
                else ProviderOutput("none", None, "Home Assistant has nothing to show")
            )
            return self._with_recording_marker(
                base,
                recording_marker and base.provider.startswith("home-assistant"),
                recording_marker_isolation,
            )

        if controller_base is not None and controller_base.frame is not None:
            return self._with_recording_marker(controller_base, recording_marker, recording_marker_isolation)
        if weather_base is not None and weather_base.frame is not None:
            return self._with_recording_marker(weather_base, recording_marker, recording_marker_isolation)

        if mode == "blackout":
            return ProviderOutput(
                "blackout", BLACKOUT_FRAME,
                "LEDs held off while GabeCubeAura retains ownership",
            )

        if mode == "events":
            return ProviderOutput("none", None, "No permanent GabeCubeAura display selected here")

        if mode == "performance":
            base = performance if (game.running or performance_always) and performance.frame else ProviderOutput("none", None, "performance unavailable")
        elif mode == "artwork":
            base = artwork if game.running and artwork.frame else ProviderOutput("none", None, "artwork unavailable")
        elif mode == "customization":
            base = customization_base if customization_base is not None and customization_base.frame \
                else ProviderOutput("none", None, "Customization+ unavailable")
        elif game.running and performance.frame:
            base = performance
        elif game.running and artwork.frame:
            base = artwork
        else:
            base = idle

        return self._with_recording_marker(
            base, recording_marker and base.provider.startswith(("performance", "artwork", "customization", "screen-sync", "audio-sync")),
            recording_marker_isolation,
        )
