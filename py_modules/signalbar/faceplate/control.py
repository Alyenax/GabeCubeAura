# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Faceplate access policy and one persistent, exclusively opened tty.

This policy never opens a device by itself. The existing Link configures a tty
and lends transactions a duplicate of the retained descriptor in priority mode.
The transaction lock covers a complete command/upload, not individual packets.
"""
from __future__ import annotations

import errno
import fcntl
import os
import termios
import threading

MODES = ("automatic", "gca-priority", "other-app")
SETTING_KEYS = {"faceplate_control_mode", "faceplate_allow_das", "faceplate_allow_dva"}


def mode(values):
    value = values.get("faceplate_control_mode", "automatic")
    return value if value in MODES else "automatic"


def allows_output(values):
    return mode(values) != "other-app"


def allows_integration(values, integration):
    if not allows_output(values):
        return False
    if mode(values) != "gca-priority":
        return True
    return integration in ("das", "dva") and values.get("faceplate_allow_" + integration, True) is True


def wants_claim(values):
    return allows_output(values) and (mode(values) == "gca-priority"
                                    or bool(values.get("faceplate_lab_enabled")))


class FaceplateControl:
    def __init__(self, values=None):
        self._state = threading.RLock()
        self._transaction = threading.RLock()
        self._mode = "automatic"
        self._closed = False
        self._active = 0
        self._fd = None
        self._port = ""
        self._identity = None
        self._discard = False
        self._phase = "automatic"
        self._error = ""
        self._generation = 0
        self._wake = threading.Event()
        self._maintenance = None
        self.configure(values or {})

    def configure(self, values):
        desired = mode(values)
        with self._state:
            changed = desired != self._mode
            if changed:
                self._mode = desired
                self._generation += 1
                self._error = ""
            # A configured preference does not reopen a stopped backend.
            if self._closed or self._mode == "other-app":
                self._phase = "releasing" if self._active else "released"
            elif self._mode == "gca-priority":
                self._phase = "reserved" if self._fd is not None else "waiting"
            else:
                self._phase = "releasing" if self._active and self._fd is not None else "automatic"
        self._settle()
        if changed:
            self._wake.set()
        return changed

    def permitted(self):
        with self._state:
            return not self._closed and self._mode != "other-app"

    def begin(self):
        if not self.permitted():
            raise OSError(errno.EBUSY, "Faceplate access is released to other apps")
        self._transaction.acquire()
        with self._state:
            if self._closed or self._mode == "other-app":
                self._transaction.release()
                raise OSError(errno.EBUSY, "Faceplate access is released to other apps")
            self._active += 1

    def open_port(self, port, flags):
        # Serialize the actual non-blocking open with a mode change, not only
        # its earlier preflight check. A releasing mode cannot open a new tty.
        with self._state:
            if not self.permitted():
                raise OSError(errno.EBUSY, "Faceplate access is released to other apps")
            return os.open(port, flags)

    def write_port(self, fd, data):
        # The tty is non-blocking. Finish an already-started syscall before a
        # release becomes effective, and reject every subsequent packet.
        with self._state:
            if not self.permitted():
                raise OSError(errno.EBUSY, "Faceplate access is released to other apps")
            return os.write(fd, data)

    def reuse(self, port, identity):
        """Called inside a Link transaction. Return a private duplicate or None."""
        with self._state:
            if self._mode != "gca-priority" or self._closed:
                return None
            if self._fd is not None and (self._discard or self._port != port or self._identity != identity):
                self._close_retained_locked()
            if self._fd is None:
                return None
            try:
                fd = os.dup(self._fd)
            except OSError:
                self._close_retained_locked()
                raise
            self._phase, self._error = "reserved", ""
            return fd

    def retain(self, fd, port, identity):
        """The caller owns an opened/configured/flock-locked tty, not a pathname."""
        with self._state:
            if self._closed or self._mode == "other-app":
                raise OSError(errno.EBUSY, "Faceplate access is released to other apps")
            if self._mode != "gca-priority":
                return
            # Do not silently fall back to a merely advisory priority mode.
            fcntl.ioctl(fd, termios.TIOCEXCL)
            try:
                kept = os.dup(fd)
            except OSError:
                fcntl.ioctl(fd, termios.TIOCNXCL)
                raise
            self._close_retained_locked()
            self._fd, self._port, self._identity = kept, port, identity
            self._discard = False
            self._phase, self._error = "reserved", ""

    def end(self):
        try:
            with self._state:
                self._active = max(0, self._active - 1)
                self._settle_locked()
        finally:
            self._transaction.release()

    def _close_retained_locked(self):
        if self._fd is not None:
            try:
                fcntl.ioctl(self._fd, termios.TIOCNXCL)
            except OSError:
                pass
            try:
                os.close(self._fd)
            finally:
                self._fd, self._port, self._identity = None, "", None
                self._discard = False

    def _settle_locked(self):
        if self._active:
            return
        if self._closed or self._mode != "gca-priority":
            self._close_retained_locked()
            self._phase = "released" if self._closed or self._mode == "other-app" else "automatic"
        elif self._discard:
            self._close_retained_locked()
            self._phase = "waiting"

    def _settle(self):
        if not self._transaction.acquire(blocking=False):
            return
        try:
            with self._state:
                self._settle_locked()
        finally:
            self._transaction.release()

    def failed(self, error):
        with self._state:
            if self._mode == "gca-priority" and not self._closed:
                self._phase = "waiting"
                self._error = str(error)[:180]
                self._discard = True
        self._settle()

    def current_reservation(self, port, identity):
        with self._state:
            return (self._fd is not None and not self._discard and self._phase == "reserved" and self._port == port
                    and self._identity == identity and self._mode == "gca-priority"
                    and not self._closed)

    def maintain(self, reserve):
        """One opt-in maintenance thread; never discover/open USB in the LED loop."""
        with self._state:
            if self._closed or self._mode != "gca-priority":
                return
            if self._maintenance is not None and self._maintenance.is_alive():
                return
            self._maintenance = threading.Thread(target=self._maintain, args=(reserve,),
                                                 name="faceplate-priority", daemon=True)
            self._maintenance.start()

    def _maintain(self, reserve):
        try:
            while self.permitted() and self.status()["mode"] == "gca-priority":
                self._wake.clear()
                try:
                    reserve()
                except Exception as error:
                    self.failed(error)
                self._wake.wait(2.0)
        finally:
            with self._state:
                self._maintenance = None

    def close(self):
        with self._state:
            self._closed = True
            self._phase = "releasing" if self._active else "released"
        self._wake.set()
        self._settle()

    def status(self):
        with self._state:
            return {"mode": self._mode, "phase": self._phase,
                    "reserved": self._fd is not None and not self._discard and self._phase == "reserved",
                    "active_transactions": self._active,
                    "generation": self._generation, "error": self._error,
                    "port": self._port,
                    "exclusive_limit": "Privileged or already-open applications may bypass terminal exclusion."}
