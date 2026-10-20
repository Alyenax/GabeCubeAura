"""The Steam Machine keeps USB powered while it sleeps, so without this the
panel goes on showing its last picture all night.

logind announces PrepareForSleep and PrepareForShutdown on the system bus
before either happens. This listens with `gdbus monitor` and holds a delay lock
with `systemd-inhibit`, so logind waits for the plugin (up to InhibitDelayMaxSec)
before going down. Both tools ship with SteamOS; Decky's bundled Python has
no dbus module.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading

from .render import clean_environment

MONITOR = ["monitor", "--system", "--dest", "org.freedesktop.login1", "--object-path", "/org/freedesktop/login1"]
# The helpers carry these so a fresh start can find strays left by an old
# plugin process (Decky's restart kills the backend without calling _unload).
MONITOR_NAME = "gabecubeaura-faceplate-login1"
INHIBIT_WHO = "--who=GabeCubeAura faceplate"


# Looked up once here: the child of a multithreaded fork must not import or
# dlopen anything, or it can deadlock on a lock another thread held.
try:
    import ctypes
    _PRCTL = ctypes.CDLL("libc.so.6", use_errno=True).prctl
except (OSError, AttributeError):
    _PRCTL = None


def die_with_parent():
    """preexec_fn: have the kernel SIGTERM this child if the plugin process goes away.

    The signal follows the thread that started the child. Both spawners here
    (Decky's event loop thread and the listener thread) live as long as the
    plugin, and start() also clears strays in case one slips through.
    """
    if _PRCTL is not None:
        _PRCTL(1, signal.SIGTERM)  # PR_SET_PDEATHSIG


def stray_helpers(proc_root="/proc", uid=None, own_children=()):
    """PIDs of this plugin's helpers that outlived the process that started them."""
    uid = os.getuid() if uid is None else uid
    found = []
    for entry in os.listdir(proc_root):
        if not entry.isdigit() or int(entry) in own_children:
            continue
        base = os.path.join(proc_root, entry)
        try:
            if os.stat(base).st_uid != uid:
                continue
            with open(os.path.join(base, "cmdline"), "rb") as handle:
                args = handle.read(4096).decode("utf-8", "replace").split("\0")
        except OSError:
            continue
        if args and (args[0] == MONITOR_NAME or INHIBIT_WHO in args):
            found.append(int(entry))
    return found


def parse_line(line):
    """('sleep'|'shutdown', starting: bool) from a gdbus monitor line, or None."""
    if "PrepareForSleep" in line:
        kind = "sleep"
    elif "PrepareForShutdown" in line:  # also PrepareForShutdownWithMetadata
        kind = "shutdown"
    else:
        return None
    args = line.split("(", 1)[1] if "(" in line else ""
    if args.lstrip().startswith("true"):
        return kind, True
    if args.lstrip().startswith("false"):
        return kind, False
    return None


class PowerEvents:
    def __init__(self, handler, logger=None, popen=subprocess.Popen, which=shutil.which):
        self.handler = handler  # handler(kind, starting) -> None; must finish quickly
        self.logger = logger
        self._popen = popen
        self._which = which
        self.inhibitor = None
        self.monitor = None
        self.thread = None
        self.stopping = threading.Event()
        self.lock = threading.Lock()

    def _log(self, level, message):
        if self.logger:
            getattr(self.logger, level)("[GabeCubeAura] faceplate: " + message)

    # ---- delay lock ----------------------------------------------------
    def take(self):
        with self.lock:
            if self.inhibitor and self.inhibitor.poll() is None:
                return
            tool = self._which("systemd-inhibit")
            if not tool:
                self._log("warning", "systemd-inhibit not found; sleep handling is best effort")
                return
            try:
                self.inhibitor = self._popen(
                    [tool, "--what=sleep:shutdown", "--mode=delay", INHIBIT_WHO,
                     "--why=Turn the faceplate off before sleep or power off", "sleep", "infinity"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    env=clean_environment(), start_new_session=True, preexec_fn=die_with_parent,
                )
            except OSError as error:
                self._log("warning", "could not take the delay lock: %s" % error)
                self.inhibitor = None

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

    # ---- signal listener -----------------------------------------------
    def start(self):
        for pid in stray_helpers():
            try:
                os.kill(pid, signal.SIGTERM)
                self._log("info", "stopped a stray helper (pid %d) from an earlier run" % pid)
            except OSError:
                pass
        self.stopping.clear()
        self.take()
        self.thread = threading.Thread(target=self._run, name="gabecubeaura-faceplate-power", daemon=True)
        self.thread.start()

    def stop(self):
        self.stopping.set()
        monitor, self.monitor = self.monitor, None
        if monitor and monitor.poll() is None:
            try:
                os.killpg(monitor.pid, signal.SIGTERM)
            except OSError:
                monitor.terminate()
        self.release()
        if self.thread:
            self.thread.join(timeout=3)

    def handle(self, kind, starting):
        try:
            self.handler(kind, starting)
        except Exception as error:  # never keep the system waiting on a bug here
            self._log("error", "%s handler failed: %s" % (kind, error))
        if starting:
            self.release()  # let the system go to sleep / power off now
        else:
            self.take()  # awake again (or the shutdown was cancelled)

    def _run(self):
        gdbus = self._which("gdbus")
        if not gdbus:
            self._log("warning", "gdbus not found; the panel won't react to sleep or shutdown")
            return
        while not self.stopping.is_set():
            try:
                self.monitor = self._popen([MONITOR_NAME] + MONITOR, executable=gdbus, stdin=subprocess.DEVNULL,
                                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                           env=clean_environment(), start_new_session=True,
                                           preexec_fn=die_with_parent, text=True, bufsize=1)
            except OSError as error:
                self._log("warning", "could not start gdbus monitor: %s" % error)
                self.stopping.wait(30)
                continue
            for line in self.monitor.stdout:
                event = parse_line(line)
                if event:
                    self._log("info", "%s %s" % (event[0], "starting" if event[1] else "over"))
                    self.handle(*event)
                if self.stopping.is_set():
                    break
            if not self.stopping.is_set():
                self._log("warning", "gdbus monitor exited; restarting in 5 s")
                self.stopping.wait(5)
