from __future__ import annotations

import os
import unittest
from unittest import mock

from signalbar.faceplate import power_events, protocol, service
from signalbar.faceplate.options import DEFAULTS
from test_faceplate_service import FakeLink

LOGIN1 = "/org/freedesktop/login1: org.freedesktop.login1.Manager."


class Parsing(unittest.TestCase):
    def test_lines(self):
        self.assertEqual(power_events.parse_line(LOGIN1 + "PrepareForSleep (true,)\n"), ("sleep", True))
        self.assertEqual(power_events.parse_line(LOGIN1 + "PrepareForSleep (false,)\n"), ("sleep", False))
        self.assertEqual(power_events.parse_line(LOGIN1 + "PrepareForShutdown (true,)\n"), ("shutdown", True))
        self.assertEqual(power_events.parse_line(
            LOGIN1 + "PrepareForShutdownWithMetadata (true, {'type': <'poweroff'>})\n"), ("shutdown", True))
        self.assertIsNone(power_events.parse_line(
            "Monitoring signals on object /org/freedesktop/login1 owned by org.freedesktop.login1\n"))
        self.assertIsNone(power_events.parse_line(LOGIN1 + "SessionNew ('3', objectpath '/x')\n"))


class LockHandOff(unittest.TestCase):
    def test_release_before_sleep_and_retake_after(self):
        calls = []
        events = power_events.PowerEvents(lambda kind, starting: calls.append(("handler", kind, starting)))
        events.take = lambda: calls.append("take")
        events.release = lambda: calls.append("release")
        events.handle("sleep", True)
        events.handle("sleep", False)
        self.assertEqual(calls, [("handler", "sleep", True), "release", ("handler", "sleep", False), "take"])

    def test_handler_crash_still_releases(self):
        calls = []

        def boom(kind, starting):
            raise RuntimeError("bug")

        events = power_events.PowerEvents(boom)
        events.release = lambda: calls.append("release")
        events.handle("shutdown", True)
        self.assertEqual(calls, ["release"])


class Strays(unittest.TestCase):
    def test_finds_only_our_leftover_helpers(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            procs = {
                "10": [power_events.MONITOR_NAME] + power_events.MONITOR,
                "11": ["/usr/bin/systemd-inhibit", "--what=sleep:shutdown", power_events.INHIBIT_WHO, "sleep", "infinity"],
                "12": ["/usr/bin/gdbus"] + power_events.MONITOR,  # someone else's monitor
                "13": ["/usr/bin/systemd-inhibit", "--who=sonyht", "sleep", "infinity"],
            }
            for pid, args in procs.items():
                os.makedirs(os.path.join(root, pid))
                with open(os.path.join(root, pid, "cmdline"), "wb") as handle:
                    handle.write("\0".join(args).encode() + b"\0")
            found = power_events.stray_helpers(root, uid=os.getuid(), own_children=(11,))
            self.assertEqual(found, [10])


@mock.patch.object(service, "find_port", lambda: "/dev/ttyUSB0")
@mock.patch.object(service, "MIN_UPLOAD_GAP", 0)
class PanelActions(unittest.TestCase):
    def setUp(self):
        FakeLink.instances.clear()

    def make(self, **extra):
        svc = service.FaceplateService(dict(DEFAULTS, mode="clock", **extra), link_factory=FakeLink)
        svc.step()
        return svc, FakeLink.instances[0]

    def test_sleep_turns_screen_off_and_wake_turns_it_on(self):
        svc, link = self.make()
        link.commands = []
        original = link.command
        link.command = lambda data, timeout=1.0, retries=3: (link.commands.append(bytes(data)), original(data))[1]
        svc.power_event("sleep", True)
        self.assertEqual(link.commands[-1], protocol.power(False))
        self.assertEqual(svc.step(), 5.0)  # nothing is sent while asleep
        svc.power_event("sleep", False)
        self.assertEqual(link.commands[-1], protocol.power(True))
        self.assertFalse(svc.asleep)

    def test_dim_action(self):
        svc, link = self.make(shutdown_action="dim")
        svc.power_event("shutdown", True)
        self.assertEqual(link.writes[-1], protocol.brightness(service.SLEEP_DIM))

    def test_keep_action_touches_nothing(self):
        svc, link = self.make(sleep_action="keep")
        before = list(link.writes)
        svc.power_event("sleep", True)
        self.assertEqual(link.writes, before)

    def test_off_mode_never_touches_the_panel(self):
        svc = service.FaceplateService(dict(DEFAULTS, mode="off"), link_factory=FakeLink)
        svc.power_event("sleep", True)
        self.assertEqual(FakeLink.instances, [])


if __name__ == "__main__":
    unittest.main()
