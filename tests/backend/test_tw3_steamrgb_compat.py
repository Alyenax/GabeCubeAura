from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from signalbar.arbiter import Arbiter
from signalbar.backend import Engine
from signalbar.integration import Tw3SteamRgbClaimReader
from signalbar.models import GameState, ProviderOutput, normalize_frame
from signalbar.settings import SettingsStore


FRAME = normalize_frame([(20, 30, 40)] * 17)
EMPTY = ProviderOutput("none", None, "empty")


class Clock:
    def __init__(self, value=100.0): self.value = value
    def __call__(self): return self.value


class CompatibilityTests(unittest.TestCase):
    def test_claim_reader_accepts_only_fresh_exact_protocol(self):
        clock = Clock()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "claim.json"
            reader = Tw3SteamRgbClaimReader(path=path, clock=clock)
            path.write_text(json.dumps({
                "protocol": 1, "owner": "TW3-SteamRGB",
                "purpose": "continuous-game-hud", "token": "test",
                "expires_at": 100.75,
            }), encoding="utf-8")
            self.assertTrue(reader.active())
            clock.value = 101
            self.assertFalse(reader.active())

    def test_claim_yields_permanent_display_but_not_temporary_layers(self):
        arbiter = Arbiter()
        game = GameState(292030, "The Witcher 3")
        base = ProviderOutput("customization", FRAME, "base")
        common = dict(
            mode="customization", guard_allows=True, game=game,
            performance=EMPTY, artwork=EMPTY, idle=EMPTY,
            customization_base=base, companion_hud_active=True,
        )
        yielded = arbiter.choose(**common)
        self.assertIsNone(yielded.frame)
        self.assertIn("TW3 SteamRGB", yielded.reason)

        event = ProviderOutput("event:notification", FRAME, "temporary")
        self.assertEqual(arbiter.choose(**common, event=event).provider, event.provider)
        countdown = ProviderOutput("countdown", FRAME, "temporary")
        self.assertEqual(arbiter.choose(**common, signal=countdown).provider, "countdown")
        launch = ProviderOutput("launch-artwork:wipe", FRAME, "temporary")
        self.assertEqual(arbiter.choose(**common, launch_artwork=launch).provider, launch.provider)

    def test_steam_priority_stays_above_companion_claim(self):
        decision = Arbiter().choose(
            mode="customization", guard_allows=True,
            game=GameState(292030, "The Witcher 3"),
            performance=EMPTY, artwork=EMPTY, idle=EMPTY,
            companion_hud_active=True, steam_priority=True,
        )
        self.assertEqual(decision.provider, "valve")

    def test_compatibility_toggle_ignores_a_live_claim_without_hiding_it(self):
        class LiveClaim:
            def active(self): return True

        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            settings.update({'faceplate_lab_enabled':False})
            engine = Engine(
                settings, str(Path(folder) / "artwork.json"),
                tw3_steamrgb_claim=LiveClaim(),
            )
            engine.set_game(292030, "The Witcher 3")
            status = engine.status()
            self.assertTrue(status["tw3_steamrgb_integration_enabled"])
            self.assertTrue(status["tw3_steamrgb_detected"])
            self.assertTrue(status["tw3_steamrgb_active"])

            engine.update_settings({"tw3_steamrgb_integration_enabled": False})
            status = engine.status()
            self.assertFalse(status["tw3_steamrgb_integration_enabled"])
            self.assertTrue(status["tw3_steamrgb_detected"])
            self.assertFalse(status["tw3_steamrgb_active"])

            engine.set_game(0, "")
            status = engine.status()
            self.assertFalse(status["tw3_steamrgb_detected"])
            self.assertFalse(status["tw3_steamrgb_active"])


if __name__ == "__main__":
    unittest.main()
