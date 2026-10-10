import json
import tempfile
import unittest
from pathlib import Path

from signalbar.voice import Assistant, VoiceOff, build
from signalbar.voice import config


class FakeMic:
    def __init__(self):
        self.closed = 0

    def open(self):
        pass

    def read_frame(self):
        return b"\0\0" * 1280

    def close(self):
        self.closed += 1


class FakeEars:
    def __init__(self, text="what time is it", on_listen=None):
        self.text = text
        self.on_listen = on_listen
        self.unloaded = 0

    def listen(self, mic, cancel):
        if self.on_listen:
            self.on_listen()
        return self.text

    def unload(self):
        self.unloaded += 1


class FakeBrain:
    def __init__(self):
        self.calls = []

    def warm_up(self):
        self.calls.append("warm")

    def ask(self, text, cancel):
        self.calls.append("ask " + text)
        return "about half past"

    def unload(self):
        self.calls.append("unload")


class FakeVoice:
    def __init__(self):
        self.said = []

    def say(self, text, cancel):
        self.said.append(text)


class FakeFace:
    def __init__(self):
        self.moods = []

    def show(self, mood):
        self.moods.append(mood)


def assistant(ears=None, warm="on_wake"):
    parts = dict(mic=FakeMic(), wake=None, ears=ears or FakeEars(), brain=FakeBrain(),
                 voice=FakeVoice(), face=FakeFace())
    return Assistant(warm=warm, **parts), parts


class VoiceAssistantTests(unittest.TestCase):
    def test_wake_shows_curious_and_warms_before_listening(self):
        seen = []
        bot, parts = assistant()
        parts["ears"].on_listen = lambda: seen.append(
            (list(parts["face"].moods), list(parts["brain"].calls))
        )
        self.assertEqual(bot.turn(), "idle")
        self.assertEqual(seen, [(["curious"], ["warm"])])
        self.assertEqual(parts["face"].moods, ["curious", "thinking", "talking", "idle"])
        self.assertEqual(parts["brain"].calls, ["warm", "ask what time is it"])
        self.assertEqual(parts["voice"].said, ["about half past"])

    def test_resident_mode_does_not_warm_on_wake(self):
        bot, parts = assistant(warm="resident")
        bot.turn()
        self.assertEqual(parts["brain"].calls, ["ask what time is it"])

    def test_nothing_heard_goes_back_to_idle_quietly(self):
        bot, parts = assistant(ears=FakeEars(text=""))
        self.assertEqual(bot.turn(), "idle")
        self.assertEqual(parts["voice"].said, [])

    def test_game_start_mid_turn_cancels_and_unloads(self):
        bot, parts = assistant()
        parts["ears"].on_listen = lambda: bot.set_game(1091500, "Cyberpunk 2077")
        self.assertEqual(bot.turn(), "paused")
        self.assertEqual(parts["brain"].calls, ["warm", "unload"])
        self.assertEqual(parts["ears"].unloaded, 1)
        self.assertEqual(parts["mic"].closed, 1)
        self.assertEqual(parts["voice"].said, [])

    def test_game_end_resumes_with_a_fresh_cancel(self):
        bot, parts = assistant(warm="resident")
        bot.set_game(1091500)
        old_cancel = bot._cancel
        bot.set_game(0)
        self.assertTrue(old_cancel.is_set())
        self.assertFalse(bot._cancel.is_set())
        self.assertEqual(bot.state, "idle")
        self.assertEqual(parts["brain"].calls, ["unload", "warm"])


class VoiceBuildTests(unittest.TestCase):
    def write_config(self, folder, values):
        Path(folder, config.FILENAME).write_text(json.dumps(values), encoding="utf-8")

    def test_off_without_a_config_file(self):
        with tempfile.TemporaryDirectory() as folder:
            result = build(folder)
        self.assertIsInstance(result, VoiceOff)
        self.assertEqual(result.reason, "off in voice.json")

    def test_missing_dependency_keeps_it_off_with_one_log_line(self):
        class Log:
            lines = []

            def warning(self, message):
                self.lines.append(message)

        log = Log()
        with tempfile.TemporaryDirectory() as folder:
            self.write_config(folder, {"enabled": True})
            result = build(folder, logger=log, find_missing=lambda values: ["openwakeword"])
        self.assertIsInstance(result, VoiceOff)
        self.assertEqual(log.lines, ["[GabeCubeAura] voice assistant off: missing openwakeword"])
        result.start()
        result.set_game(10)
        result.stop()

    def test_missing_check_without_optional_packages(self):
        gaps = config.missing(
            dict(config.DEFAULTS), find_spec=lambda name: None,
            which=lambda name: None, exists=lambda path: False,
        )
        self.assertIn("openwakeword", gaps)
        self.assertIn("pw-record", gaps)
        self.assertTrue(any(gap.startswith("llm_model ") for gap in gaps))
