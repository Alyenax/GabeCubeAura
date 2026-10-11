"""Say when the Steam Machine is about to sleep, so the bridge can go offline first.

Without this Home Assistant shows the old state until the broker's keepalive
gives up on the sleeping machine and sends the last will, about 45 s later.
logind announces a suspend with PrepareForSleep(true) on the system bus. The
bridge has no D-Bus library to rely on, so this follows gdbus monitor (part of
GLib, on SteamOS) in a subprocess. Without gdbus or a system bus it does
nothing; it never raises into the bridge.

PrepareForSleep(false) is the wake, or a suspend that was cancelled; the
bridge then comes back online. A shutdown is PrepareForShutdown and does not
count. logind does not wait for this process, but Steam holds a delay lock,
so the publish has had seconds to spare; the will still covers a miss.
"""

from __future__ import annotations

import re
import subprocess
import threading

COMMAND = ("gdbus", "monitor", "--system", "--dest", "org.freedesktop.login1",
           "--object-path", "/org/freedesktop/login1")
_SLEEP = re.compile(r"\.PrepareForSleep \((true|false),\)")
# gdbus exits if the bus restarts; it is started again after this long.
RETRY_S = 60.0


class SleepWatch:
    def __init__(self, on_sleep, command=COMMAND, logger=None):
        self._on_sleep, self._command, self.log = on_sleep, list(command), logger
        self._stop = threading.Event()
        self._process = None
        self._thread = None

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="gabecubeaura-sleep-watch", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        process = self._process
        if process is not None:
            try:
                process.terminate()
            except OSError:
                pass
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def _run(self):
        while not self._stop.is_set():
            try:
                self._process = subprocess.Popen(self._command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                                 stderr=subprocess.DEVNULL, text=True, errors="replace")
            except OSError as error:
                if self.log:
                    self.log.info(f"[GabeCubeAura] not watching for sleep: {type(error).__name__}")
                return  # no gdbus: nothing to try again
            try:
                if self._stop.is_set():
                    break
                for line in self._process.stdout:
                    if self._stop.is_set():
                        break
                    self.handle(line)
            finally:
                self._close()
            self._stop.wait(RETRY_S)

    def handle(self, line):
        """Pass on one line of gdbus output: True before a suspend, False after it."""
        found = _SLEEP.search(line)
        if found:
            try:
                self._on_sleep(found.group(1) == "true")
            except Exception:
                pass

    def _close(self):
        process, self._process = self._process, None
        if process is None:
            return
        try:
            process.terminate()
            process.wait(timeout=2.0)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass
        if process.stdout:
            process.stdout.close()
