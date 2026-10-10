import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from signalbar.voice import Supervisor, VoiceOff, build
from signalbar.voice import config
from signalbar.voice.__main__ import main as voice_main
from signalbar.voice.assistant import Assistant


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

    def record(self, mic, cancel):
        self.listen(mic, cancel)
        return b"\x01\x00" * 1280

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

    play = say


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

    def test_cloud_mode_sends_the_recording_and_plays_the_reply(self):
        sent = []
        cloud = type("Cloud", (), {"answer": lambda self, wav: sent.append(wav) or b"RIFF reply"})()
        bot = Assistant(FakeMic(), None, FakeEars(), None, FakeVoice(), FakeFace(), cloud=cloud)
        self.assertEqual(bot.turn(), "idle")
        self.assertTrue(sent[0].startswith(b"RIFF"))
        self.assertEqual(bot.voice.said, [b"RIFF reply"])
        bot.set_game(570)  # no brain to unload in cloud mode, and that's fine
        self.assertEqual(bot.state, "paused")

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


class Log:
    def __init__(self):
        self.lines = []

    def info(self, message):
        self.lines.append(message)

    warning = info


class FakeChild:
    def __init__(self, lines=()):
        self.stdin = io.StringIO()
        self.stdout = iter(lines)

    def wait(self, timeout=None):
        return 0


class VoiceSupervisorTests(unittest.TestCase):
    def test_game_start_sends_pause_and_moods_reach_the_face(self):
        face = FakeFace()
        supervisor = Supervisor("/tmp", "python3", face)
        supervisor._child = FakeChild()
        supervisor.set_game(1091500, "Cyberpunk 2077")
        self.assertEqual(supervisor._child.stdin.getvalue(), '{"game": true}\n')
        supervisor.handle_line('{"state": "curious", "mood": "curious"}\n')
        self.assertEqual(face.moods, ["curious"])
        self.assertEqual(supervisor.state, "curious")

    def test_off_line_logs_once_and_is_not_restarted(self):
        log, spawned = Log(), []

        def popen(command, **kwargs):
            spawned.append(command)
            return FakeChild(['{"off": "missing openwakeword"}\n'])

        with tempfile.TemporaryDirectory() as folder:
            supervisor = Supervisor(folder, "venv-python", logger=log, popen=popen,
                                    command_for=lambda command: (command, {}))
            supervisor._run()
        self.assertEqual(spawned, [["venv-python", "-m", "signalbar.voice", folder]])
        self.assertEqual(log.lines, ["[GabeCubeAura] voice: assistant off: missing openwakeword"])


class VoiceStartupTests(unittest.TestCase):
    def test_off_without_a_config_file(self):
        with tempfile.TemporaryDirectory() as folder:
            result = build(folder)
        self.assertIsInstance(result, VoiceOff)
        self.assertEqual(result.reason, "off in voice.json")

    def test_no_venv_python_or_no_cloud_key_keeps_it_off_with_one_log_line(self):
        for values, reason in (
            ({"python": "/nope/python"}, "no Python"),
            ({"python": sys.executable, "mode": "cloud"}, "cloud mode needs a voice-key"),
        ):
            log = Log()
            with tempfile.TemporaryDirectory() as folder:
                Path(folder, config.FILENAME).write_text(
                    json.dumps(dict(values, enabled=True)), encoding="utf-8")
                result = build(folder, logger=log)
            self.assertIsInstance(result, VoiceOff)
            self.assertEqual(len(log.lines), 1)
            self.assertTrue(result.reason.startswith(reason), result.reason)

    def test_voice_process_reports_missing_pieces_and_exits(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(voice_main([folder], io.StringIO(), out), 0)
        self.assertTrue(json.loads(out.getvalue())["off"].startswith("missing "))
