"""termios serial link to the faceplate (no pyserial on SteamOS or in Decky's Python)."""

from __future__ import annotations

import fcntl
import glob
import os
import select
import termios
import time

from . import protocol

# The CH340 has no serial number, so match on VID:PID through sysfs.
CH340 = ("1a86", "7523")
BAUD = 1000000
# Replies carry 0x01 for success. On GIF begin, 0x02 means the panel already
# holds a GIF with that size and CRC32, so it skips the upload (seen: sending
# the same picture twice gets 02 the second time).
OK = (0x00, 0x01)
ALREADY_STORED = 0x02


class LinkError(Exception):
    pass


class LinkBusy(LinkError):
    """Another program holds the faceplate (usually the standalone Pixel Faceplate plugin)."""


def find_port():
    for tty in sorted(glob.glob("/sys/class/tty/ttyUSB*")):
        # device -> .../3-1/3-1:1.0/ttyUSB0; walk up to the node with idVendor.
        node = os.path.realpath(os.path.join(tty, "device"))
        for _ in range(4):
            node = os.path.dirname(node)
            try:
                with open(os.path.join(node, "idVendor")) as v, open(os.path.join(node, "idProduct")) as p:
                    if (v.read().strip(), p.read().strip()) == CH340:
                        return "/dev/" + os.path.basename(tty)
                break
            except OSError:
                continue
    return None


class Link:
    def __init__(self, port=None, log=None):
        self.port = port or find_port()
        self.log = log or (lambda *_: None)
        self.fd = None
        self.rx = bytearray()

    def open(self):
        if not self.port:
            raise LinkError("faceplate not found (no CH340 ttyUSB)")
        fd = os.open(self.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        # Two writers on one port interleave packets and the panel rejects
        # both. Anything that drives the faceplate takes an exclusive flock on
        # the tty first (the standalone Pixel Faceplate plugin does the same).
        # TIOCEXCL won't do: it doesn't stop root, and GabeCubeAura runs as root.
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise LinkBusy("faceplate in use by another app (the Pixel Faceplate plugin?)")
        try:
            attrs = termios.tcgetattr(fd)
            iflag, oflag, cflag, lflag, _, _, cc = attrs
            iflag = 0
            oflag = 0
            lflag = 0
            # 8N1, receiver on, ignore modem lines, no flow control.
            cflag = termios.CS8 | termios.CREAD | termios.CLOCAL
            cc[termios.VMIN] = 0
            cc[termios.VTIME] = 0
            speed = termios.B1000000
            termios.tcsetattr(fd, termios.TCSANOW, [iflag, oflag, cflag, lflag, speed, speed, cc])
            termios.tcflush(fd, termios.TCIOFLUSH)
        except Exception:
            os.close(fd)
            raise
        self.fd = fd
        self.rx.clear()
        return self

    def close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            finally:
                self.fd = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *_):
        self.close()

    def write(self, data):
        view = memoryview(data)
        deadline = time.monotonic() + 2.0
        while view:
            _, ready, _ = select.select([], [self.fd], [], 0.5)
            if not ready:
                if time.monotonic() > deadline:
                    raise LinkError("write timed out")
                continue
            sent = os.write(self.fd, view)
            view = view[sent:]
        termios.tcdrain(self.fd)

    def read_replies(self, timeout):
        """Collect replies until at least one arrives or timeout passes."""
        deadline = time.monotonic() + timeout
        while True:
            replies, junk = protocol.parse(self.rx)
            if junk:
                self.log("rx junk: %s" % junk.hex(" "))
            if replies:
                return replies
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return []
            ready, _, _ = select.select([self.fd], [], [], remaining)
            if ready:
                chunk = os.read(self.fd, 4096)
                if not chunk:
                    raise LinkError("port closed")
                self.rx += chunk

    def command(self, data, timeout=1.0, retries=3):
        """Send one frame and wait for the reply with the same type and cmd."""
        kind, cmd = data[2], data[3]
        for attempt in range(retries):
            self.write(data)
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                for reply in self.read_replies(end - time.monotonic()):
                    if reply.kind == kind and reply.cmd == cmd:
                        return reply
                    self.log("unexpected reply %r" % reply)
            self.log("no reply to type=%02X cmd=%02X (attempt %d)" % (kind, cmd, attempt + 1))
        raise LinkError("no reply to type=0x%02X cmd=0x%02X" % (kind, cmd))

    def send_gif(self, gif, chunk_gap=0.0):
        """Upload one GIF. Returns False if the panel already had it (no write)."""
        begin = self.command(protocol.gif_begin(gif))
        if begin.status == ALREADY_STORED:
            return False
        if begin.status not in OK:
            raise LinkError("GIF begin refused: %r" % begin)
        for chunk in protocol.gif_chunks(gif):
            reply = self.command(chunk)
            if reply.status not in OK:
                raise LinkError("chunk refused: %r" % reply)
            if chunk_gap:
                time.sleep(chunk_gap)
        end = self.command(protocol.gif_end(), timeout=2.0)
        if end.status not in OK:
            raise LinkError("GIF end refused: %r" % end)
        return True
