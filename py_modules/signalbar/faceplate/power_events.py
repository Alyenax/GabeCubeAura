# SPDX-License-Identifier: GPL-3.0-only AND BSD-3-Clause
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""SteamOS sleep/shutdown events for the optional faceplate.

The Steam Machine can keep USB powered while sleeping.  logind exposes the
transition early enough to send the panel's volatile power-off command.  A
delay inhibitor makes that small operation reliable without adding a Python
D-Bus dependency to Decky's bundled runtime.

This module is independently adapted from hodapp/pixel-faceplate's BSD-3-Clause
power-events implementation; the corresponding notice is shipped with
GabeCubeAura.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading

from .artwork import clean_environment


MONITOR_ARGUMENTS = [
    "monitor", "--system", "--dest", "org.freedesktop.login1",
    "--object-path", "/org/freedesktop/login1",
]
MONITOR_NAME = "gabecubeaura-faceplate-login1"
INHIBIT_WHO = "--who=GabeCubeAura Faceplate"


def die_with_parent():
    """Ask Linux to terminate a helper when Decky's backend disappears."""
    try:
        import ctypes
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)
    except (OSError, AttributeError):
        pass


def parse_line(line):
    """Return ``(sleep|shutdown, starting)`` for a logind monitor line."""
    if "PrepareForSleep" in line:
        kind = "sleep"
    elif "PrepareForShutdown" in line:
        kind = "shutdown"
    else:
        return None
    arguments = line.split("(", 1)[1] if "(" in line else ""
    if arguments.lstrip().startswith("true"):
        return kind, True
    if arguments.lstrip().startswith("false"):
        return kind, False
    return None


def stray_helpers(proc_root="/proc", uid=None, own_children=()):
    """Find only GabeCubeAura helpers orphaned by an earlier Decky restart."""
    uid = os.getuid() if uid is None else uid
    found = []
    try:
        entries = os.listdir(proc_root)
    except OSError:
        return found
    for entry in entries:
        if not entry.isdigit() or int(entry) in own_children:
            continue
        base = os.path.join(proc_root, entry)
        try:
            if os.stat(base).st_uid != uid:
                continue
            with open(os.path.join(base, "cmdline"), "rb") as handle:
                arguments = handle.read(4096).decode("utf-8", "replace").split("\0")
        except OSError:
            continue
        if arguments and (arguments[0] == MONITOR_NAME or INHIBIT_WHO in arguments):
            found.append(int(entry))
    return found


class PowerEvents:
    """Listen for logind power transitions and bound helper lifetimes."""

    def __init__(self, handler, logger=None, popen=subprocess.Popen, which=shutil.which):
        self.handler = handler
        self.logger = logger
        self._popen = popen
        self._which = which
        self.inhibitor = None
        self.monitor = None
        self.thread = None
        self.stopping = threading.Event()
        self.lock = threading.Lock()

    def _log(self, level, message):
        callback = getattr(self.logger, level, None)
        if callable(callback):
            callback("[GabeCubeAura Faceplate Power] " + message)

    def running(self):
        return bool(self.thread and self.thread.is_alive() and not self.stopping.is_set())

    def take(self):
        with self.lock:
            if self.inhibitor and self.inhibitor.poll() is None:
                return
            tool = self._which("systemd-inhibit")
            if not tool:
                self._log("warning", "systemd-inhibit is unavailable; power-off is best effort")
                return
            try:
                self.inhibitor = self._popen(
                    [tool, "--what=sleep:shutdown", "--mode=delay", INHIBIT_WHO,
                     "--why=Turn the faceplate off before sleep or shutdown",
                     "sleep", "infinity"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, env=clean_environment(),
                    start_new_session=True, preexec_fn=die_with_parent,
                )
            except OSError as error:
                self.inhibitor = None
                self._log("warning", f"could not take delay inhibitor: {error}")

    def release(self):
        with self.lock:
            process, self.inhibitor = self.inhibitor, None
        if process and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except OSError:
                process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()

    def start(self):
        if self.running():
            return
        own = tuple(
            process.pid for process in (self.inhibitor, self.monitor)
            if process is not None
        )
        for pid in stray_helpers(own_children=own):
            try:
                os.kill(pid, signal.SIGTERM)
                self._log("info", f"stopped stale helper {pid}")
            except OSError:
                pass
        self.stopping.clear()
        self.take()
        self.thread = threading.Thread(
            target=self._run, name="gabecubeaura-faceplate-power", daemon=True,
        )
        self.thread.start()

    def stop(self, timeout=3):
        self.stopping.set()
        monitor, self.monitor = self.monitor, None
        if monitor and monitor.poll() is None:
            try:
                os.killpg(monitor.pid, signal.SIGTERM)
            except OSError:
                monitor.terminate()
        self.release()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=max(0.0, float(timeout)))
        self.thread = None

    def handle(self, kind, starting):
        try:
            self.handler(kind, starting)
        except Exception as error:  # do not make the machine wait on our bug
            self._log("error", f"{kind} handler failed: {error}")
        if starting:
            self.release()
        else:
            self.take()

    def _run(self):
        gdbus = self._which("gdbus")
        if not gdbus:
            self._log("warning", "gdbus is unavailable; automatic power-off is inactive")
            self.release()
            return
        while not self.stopping.is_set():
            try:
                self.monitor = self._popen(
                    [MONITOR_NAME] + MONITOR_ARGUMENTS, executable=gdbus,
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, env=clean_environment(),
                    start_new_session=True, preexec_fn=die_with_parent,
                    text=True, bufsize=1,
                )
            except OSError as error:
                self._log("warning", f"could not start gdbus monitor: {error}")
                self.stopping.wait(30)
                continue
            for line in self.monitor.stdout:
                event = parse_line(line)
                if event:
                    self._log("info", f"{event[0]} {'starting' if event[1] else 'over'}")
                    self.handle(*event)
                if self.stopping.is_set():
                    break
            if not self.stopping.is_set():
                self._log("warning", "gdbus monitor exited; restarting in 1 second")
                self.stopping.wait(1)
