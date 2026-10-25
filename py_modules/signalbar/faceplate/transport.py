"""Bounded stdlib-only serial transport for the JSAUX PIXEL faceplate.

Adapted from hodapp/pixel-faceplate 0.1.9 (BSD-3-Clause), copyright
2026 Eli Hodapp. See licenses/Pixel-Faceplate-BSD-3-Clause.txt.
"""

from __future__ import annotations

import errno
import fcntl
import glob
import hashlib
import os
import select
import termios
import time
import stat
import threading
import math
from pathlib import Path

from . import protocol
from . import runtime
from .flash import default_manager, UploadDeferred, ContentCollision
from .gif_transform import repack_for_restore
from . import timing

CH340 = ("1a86", "7523")
ALREADY_STORED = 0x02
OK = (0x01,)
CHUNK_PACING_SECONDS = 0.012
GIF_PREFLIGHT_SECONDS = 0.020
TRANSFER_RETRY_SECONDS = 0.036
PROFILE_BASELINE = "baseline"
PROFILE_VENDOR = "vendor"
PROFILE_AUTO = "auto"
TRANSPORT_PROFILES = (PROFILE_BASELINE, PROFILE_VENDOR, PROFILE_AUTO)
GIF_END_BASE_SECONDS = 1.25
GIF_END_PER_4K_SECONDS = timing.END_PER_4K_SECONDS
GIF_END_MIN_SECONDS = 1.50
GIF_END_MAX_SECONDS = 10.0


def coordinated_transfer_ms(size_bytes):
    """Preparation/admission estimate, not a hardware latency guarantee.

    Conservative measured-envelope policy: per-chunk allowance, physical wire
    time, scaled END wait, identification and TV reveal margin. Validate against
    physical logs; this is not a predicted optical start or learned calibration.
    A reused CRC must not be used to bypass admission or manufacture phase zero.
    """
    return timing.transfer_ms(size_bytes)


def timing_admission(size_bytes, remaining_ms):
    return timing.admits(size_bytes, remaining_ms)


class LinkError(RuntimeError):
    pass


class ReplyTimeout(LinkError):
    """A command was drained to the tty but no matching reply arrived."""


class NativeClockRejected(LinkError):
    """An invalid or negative 0x05 reply; physical mode remains unknown."""


class GifCommitUnconfirmed(LinkError):
    """Every data chunk was ACKed; only the final GIF_END reply is missing."""


class LinkBusy(LinkError):
    """Another process has already claimed the JSAUX serial port."""


class TransferCancelled(LinkError):
    """A newer latest-only scene superseded an in-flight GIF transfer."""


def gif_end_timeout(payload_bytes: int) -> float:
    """Return a bounded finalization timeout scaled to the GIF size.

    The panel acknowledges chunks quickly but commits the completed GIF only
    after GIF_END. Physical measurements show that this last acknowledgement
    grows with the encoded size, so a fixed one-second timeout rejects valid
    larger artwork.
    """
    return timing.end_timeout(payload_bytes)


def find_port() -> str | None:
    for tty in sorted(glob.glob("/sys/class/tty/ttyUSB*")):
        node = os.path.realpath(os.path.join(tty, "device"))
        for _ in range(4):
            node = os.path.dirname(node)
            try:
                with open(os.path.join(node, "idVendor"), encoding="ascii") as vendor, \
                        open(os.path.join(node, "idProduct"), encoding="ascii") as product:
                    if (vendor.read().strip(), product.read().strip()) == CH340:
                        return "/dev/" + os.path.basename(tty)
                break
            except OSError:
                continue
    return None


def device_identity(port: str):
    """Return an identity that changes when Linux recreates the USB tty node."""
    try:
        stat = os.stat(port)
    except OSError:
        return None
    return (os.path.realpath(port), stat.st_rdev, stat.st_ino, stat.st_ctime_ns)


def port_owners(port: str, proc_root: str = "/proc") -> list[int]:
    """Return other processes already holding the tty, without invoking tools."""
    target = os.path.realpath(port)
    owners = []
    try:
        entries = os.listdir(proc_root)
    except OSError:
        return owners
    for entry in entries:
        if not entry.isdigit() or int(entry) == os.getpid():
            continue
        directory = os.path.join(proc_root, entry, "fd")
        try:
            descriptors = os.listdir(directory)
        except OSError:
            continue
        for descriptor in descriptors:
            try:
                if os.path.realpath(os.path.join(directory, descriptor)) == target:
                    owners.append(int(entry))
                    break
            except OSError:
                continue
    return sorted(owners)


def port_owner_details(port: str, proc_root: str = "/proc") -> list[str]:
    details = []
    for pid in port_owners(port, proc_root):
        name = "unknown process"
        try:
            raw = Path(proc_root, str(pid), "cmdline").read_bytes().split(b"\0", 1)[0]
            if raw:
                name = os.path.basename(raw.decode("utf-8", "replace"))
        except OSError:
            try:
                name = Path(proc_root, str(pid), "comm").read_text(
                    encoding="utf-8", errors="replace",
                ).strip() or name
            except OSError:
                pass
        details.append(f"{name} (PID {pid})")
    return details


class PhysicalOwnership:
    """Long-lived cooperative lock, distinct from a transaction's tty flock.

    USB serial identity is preferred. Without it use the physical sysfs USB
    location (not VID/PID alone); tty aliases resolve to the same lock key.
    Locks remain held while the owner closes/reopens the serial descriptor.
    """
    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.descriptors = {}

    @staticmethod
    def key(port):
        name = os.path.basename(os.path.realpath(port))
        node = Path(os.path.realpath("/sys/class/tty/"+name+"/device"))
        identity = None
        for candidate in (node, *node.parents):
            try:
                vendor = (candidate/"idVendor").read_text(encoding="ascii").strip()
                product = (candidate/"idProduct").read_text(encoding="ascii").strip()
            except OSError:
                continue
            try:
                serial = (candidate/"serial").read_text(encoding="ascii").strip()
            except OSError:
                serial = ""
            identity = "usb:"+vendor+":"+product+":"+("serial:"+serial if serial else "location:"+str(candidate))
            break
        if identity is None:
            try:
                info = os.stat(port)
                identity = "rdev:"+str(info.st_rdev) if stat.S_ISCHR(info.st_mode) else "path:"+os.path.realpath(port)
            except OSError:
                identity = "path:"+os.path.realpath(port)
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def claim(self, port):
        key = self.key(port)
        with self.lock:
            if key in self.descriptors:
                return True
            if len(self.descriptors) >= 4:
                return False
            fd = None
            try:
                # Provision the endpoint leaf BEFORE mkdir of ownership. A
                # parents=True claim must never recreate canonical v1 as 0755.
                runtime.provision_ownership(self.root)
                path = self.root/(key+".lock")
                fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_nlink != 1:
                    raise OSError("Unsafe JSAUX ownership lock")
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.descriptors[key] = fd
                return True
            except OSError:
                if fd is not None:
                    os.close(fd)
                return False

    def close(self):
        with self.lock:
            for fd in self.descriptors.values():
                os.close(fd)
            self.descriptors.clear()


_ownership_manager = None


def install_ownership_manager(manager):
    global _ownership_manager
    _ownership_manager = manager


class Link:
    def __init__(self, port: str | None = None, log=None,
                 transport_profile: str = PROFILE_BASELINE):
        if transport_profile not in TRANSPORT_PROFILES:
            raise ValueError(f"unknown faceplate transport profile: {transport_profile}")
        self.port = port or find_port()
        self.log = log or (lambda *_: None)
        self.transport_profile = transport_profile
        self.fd = None
        self.rx = bytearray()
        self.last_command_sent_at = None
        self.last_command_first_sent_at = None
        self.last_command_ack_ms = 0
        self.last_transfer_timings = {}
        self.flash_manager = None
        self.flash_priority = "background"
        self.flash_scene = "scene"

    def open(self):
        if not self.port:
            raise LinkError("faceplate not found (no JSAUX CH340 ttyUSB)")
        if _ownership_manager is not None and not _ownership_manager.claim(self.port):
            raise LinkBusy("Faceplate physical ownership is unavailable")
        owners = port_owner_details(self.port)
        if owners:
            raise LinkError("faceplate serial port owned by " + ", ".join(owners))
        fd = os.open(self.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        # Cooperate with Pixel Faceplate's flock; /proc checks are advisory
        # diagnostics and cannot prevent simultaneous competing opens.
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            os.close(fd)
            if error.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES):
                raise LinkBusy("Faceplate serial port is in use by another program") from error
            raise LinkError(f"Faceplate serial lock failed: {error}") from error
        try:
            attrs = termios.tcgetattr(fd)
            _iflag, _oflag, _cflag, _lflag, _ispeed, _ospeed, control = attrs
            control[termios.VMIN] = 0
            control[termios.VTIME] = 0
            flags = termios.CS8 | termios.CREAD | termios.CLOCAL
            speed = termios.B1000000
            termios.tcsetattr(fd, termios.TCSANOW, [0, 0, flags, 0, speed, speed, control])
            termios.tcflush(fd, termios.TCIOFLUSH)
        except Exception as error:
            os.close(fd)
            if isinstance(error, termios.error):
                raise LinkError(f'faceplate serial configuration failed: {error}') from error
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

    def write(self, data: bytes):
        if (len(data) >= 4 and (data[2], data[3]) in {
                (protocol.TYPE_CONTROL, protocol.CMD_GIF_BEGIN),
                (protocol.TYPE_CONTROL, protocol.CMD_GIF_END),
                (protocol.TYPE_DATA, protocol.CMD_GIF_CHUNK)}
                and not getattr(self, "_gif_transaction", False)):
            raise LinkError("GIF packets must pass through protected send_gif")
        view = memoryview(data)
        deadline = time.monotonic() + 2.0
        while view:
            _, ready, _ = select.select([], [self.fd], [], 0.5)
            if not ready:
                if time.monotonic() > deadline:
                    raise LinkError("serial write timed out")
                continue
            view = view[os.write(self.fd, view):]
        try:
            termios.tcdrain(self.fd)
        except termios.error as error:
            raise LinkError(f'faceplate serial drain failed: {error}') from error
        if len(data) >= 4 and data[2] == protocol.TYPE_CONTROL:
            name = {protocol.CMD_BRIGHTNESS: "brightness", protocol.CMD_POWER: "power",
                    protocol.CMD_NATIVE_CLOCK: "native_clock"}.get(data[3])
            if name:
                manager = self.flash_manager or default_manager()
                manager.record_command(name)

    def read_replies(self, timeout: float):
        deadline = time.monotonic() + timeout
        while True:
            replies, junk = protocol.parse(self.rx)
            if junk:
                self.log("faceplate rx junk: " + junk.hex(" "))
            if replies:
                return replies
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return []
            ready, _, _ = select.select([self.fd], [], [], remaining)
            if ready:
                chunk = os.read(self.fd, 4096)
                if not chunk:
                    raise LinkError("faceplate serial port closed")
                self.rx += chunk

    def command(self, data: bytes, timeout: float = 1.0, retries: int = 3):
        kind, command = data[2], data[3]
        self.last_command_first_sent_at = None
        for _attempt in range(retries):
            self.write(data)
            # The display can act as soon as the command has drained to the
            # serial device. Its reply may arrive much later, especially after
            # a power-on, so keep the successful attempt's transmit epoch.
            sent_at = time.monotonic()
            if self.last_command_first_sent_at is None:
                self.last_command_first_sent_at = sent_at
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                for reply in self.read_replies(deadline - time.monotonic()):
                    if reply.kind == kind and reply.command == command:
                        self.last_command_sent_at = sent_at
                        self.last_command_ack_ms = round((time.monotonic() - sent_at) * 1000)
                        return reply
        raise ReplyTimeout(f"no reply to type=0x{kind:02x} cmd=0x{command:02x}")

    def synchronize_native_clock(self, when):
        """One activation attempt only; a lost ACK must never trigger retries."""
        reply = self.command(protocol.native_clock(when), timeout=1.0, retries=1)
        if (not isinstance(reply, protocol.Reply)
                or reply.kind != protocol.TYPE_CONTROL
                or reply.command != protocol.CMD_NATIVE_CLOCK
                or reply.payload != b"\x01"):
            raise NativeClockRejected("faceplate refused native clock (invalid 0x05 ACK)")
        return reply

    def capabilities(self):
        return {
            "protocol": "jsaux-pixel-gif-v1",
            "configured_profile": self.transport_profile,
            "active_profile": self.last_transfer_timings.get("active_profile", ""),
            "profiles": list(TRANSPORT_PROFILES),
            "factory_test": "optional-fire-and-forget",
            "gif_end_timeout": "adaptive",
            "native_clock": True,
            "native_clock_flash_effect": "unverified",
            "raw_pixels": False,
            "single_serial_owner": True,
            "panel_crc_deduplication": True,
            "long_gif_delays": True,
            "long_gif_delay_state": "unused-dashboard-uses-standard-delays",
            "performance_live_updates": False,
            "performance_policy": "removed-from-faceplate",
        }

    def _vendor_preflight(self, timings: dict):
        """Match JSAUX's write-only F0 preflight; the panel does not ACK it."""
        started = time.monotonic()
        self.write(protocol.factory_test(0))
        timings["preflight_ms"] += round((time.monotonic() - started) * 1000)
        time.sleep(GIF_PREFLIGHT_SECONDS)

    @staticmethod
    def _check_cancelled(cancelled):
        if callable(cancelled) and cancelled():
            raise TransferCancelled("faceplate GIF transfer superseded")

    def _send_gif_once(self, data: bytes, timings: dict, profile: str,
                       cancelled=None) -> bool:
        self._check_cancelled(cancelled)
        if profile == PROFILE_VENDOR:
            self._vendor_preflight(timings)
        self._check_cancelled(cancelled)
        started = time.monotonic()
        timings["begin_attempted"] = True
        begin = self.command(protocol.gif_begin(data), timeout=1.0, retries=3)
        timings['begin_status'] = begin.status
        timings["begin_ms"] += round((time.monotonic() - started) * 1000)
        timings["begin_ack_ms"] = self.last_command_ack_ms
        if begin.status == ALREADY_STORED:
            self._check_cancelled(cancelled)
            self.flash_manager.check_reuse(timings["identity"])
            timings["already_stored"] = True
            # Normal CRC reuse opens no body transaction: do not finalize it.
            # Explicit return from a known built-in mode is different.
            activate = bool(getattr(self, 'activate_stored_gif', False))
            timings['stored_activation_required'] = activate
            if not activate:
                return False
            if getattr(self, 'restore_stored_gif', False):
                # Lab147 reports show that stored BEGIN -> empty END can stay
                # silent after a delegated session. Do not retry that command
                # or fabricate a successful display receipt. Reframe the SAME
                # compressed image once and use the ordinary budgeted upload.
                source = timings['identity']
                data = repack_for_restore(data)
                wanted = self.flash_manager.preflight(data, self.flash_priority)
                if (wanted['size'], wanted['crc32']) == (source['size'], source['crc32']):
                    raise LinkError('recovery GIF identity collision')
                timings.update(restore_repacked=True, source_identity=source,
                               identity=wanted, stored_activation_required=False,
                               source_begin_status=begin.status)
                self.last_wire_data = data
                self._check_cancelled(cancelled)
                started = time.monotonic()
                begin = self.command(protocol.gif_begin(data), timeout=1.0, retries=1)
                timings['begin_ms'] += round((time.monotonic() - started) * 1000)
                timings['begin_ack_ms'] = self.last_command_ack_ms
                timings['begin_status'] = begin.status
                timings['already_stored'] = begin.status == ALREADY_STORED
                timings['restore_begin_status'] = begin.status
                if begin.status == ALREADY_STORED:
                    raise LinkError('recovery GIF already stored; playback remains unconfirmed')
                # Continue below, with one body reservation and one END only.
            else:
                try:
                    end = self.command(protocol.gif_end(), timeout=gif_end_timeout(len(data)), retries=1)
                except ReplyTimeout as error:
                    timings["end_sent"] = True
                    timings["sent_unconfirmed"] = True
                    raise GifCommitUnconfirmed(str(error)) from error
                timings["end_sent"] = True
                timings['end_status'] = end.status
                if end.status not in OK:
                    raise LinkError("faceplate refused stored GIF display")
                timings["end_ack_ms"] = self.last_command_ack_ms
                timings["stored_display_restarted"] = True
                return False
        if begin.status not in OK:
            raise LinkError("faceplate refused GIF begin")
        self.flash_manager.reserve_body(timings["identity"], self.flash_priority)
        timings["body_reserved"] = True
        started = time.monotonic()
        for sequence, chunk in enumerate(protocol.gif_chunks(data)):
            self._check_cancelled(cancelled)
            reply = self.command(chunk, timeout=1.0, retries=3)
            if reply.status not in OK:
                timings['failed_chunk'] = sequence
                timings['chunk_status'] = reply.status
                timings['payload_bytes_confirmed'] = min(len(data), sequence * protocol.CHUNK_SIZE)
                raise LinkError("faceplate refused a GIF chunk")
            timings["chunks"] += 1
            time.sleep(CHUNK_PACING_SECONDS)
        timings["chunks_ms"] += round((time.monotonic() - started) * 1000)
        self._check_cancelled(cancelled)
        started = time.monotonic()
        timings['payload_complete'] = True
        final_timeout = gif_end_timeout(len(data))
        timings["end_timeout_seconds"] = final_timeout
        try:
            end = self.command(protocol.gif_end(), timeout=final_timeout, retries=1)
        except ReplyTimeout as error:
            timings['end_sent'] = True
            timings['sent_unconfirmed'] = True
            raise GifCommitUnconfirmed(str(error)) from error
        finally:
            timings["finalize_ms"] += round((time.monotonic() - started) * 1000)
        timings['end_sent'] = True
        timings['end_status'] = end.status
        timings["end_ack_ms"] = self.last_command_ack_ms
        if end.status not in OK:
            raise LinkError("faceplate refused GIF end")
        return True

    def send_gif(self, data: bytes, cancelled=None) -> bool:
        """Send one GIF with a bounded, capability-recorded fallback.

        Baseline deliberately omits the factory command and is the default.
        Vendor mode mirrors JSAUX's write-only F0 preflight; it never waits for
        an F0 reply. Auto tries baseline first, then the vendor preflight.
        """
        if len(data) > protocol.MAX_GIF_BYTES:
            raise ValueError("faceplate GIF exceeds the 192 KiB transfer limit")
        total_started = time.monotonic()
        self.last_wire_data = bytes(data)
        # Every caller, including future tools using Link directly, crosses
        # the same admission point. The coordinator injects persisted policy.
        self.flash_manager = getattr(self, "flash_manager", None) or default_manager()
        self.flash_priority = getattr(self, "flash_priority", "background")
        wanted = self.flash_manager.preflight(data, self.flash_priority)
        timings = {
            "identity": wanted, "body_reserved": False, "stored_display_restarted": False,
            "preflight_ms": 0,
            "begin_ms": 0,
            "begin_ack_ms": 0,
            "chunks_ms": 0,
            "finalize_ms": 0,
            "end_ack_ms": 0,
            "chunks": 0,
            "transfer_retries": 0,
            "already_stored": False,
            "configured_profile": self.transport_profile,
            "attempt_profiles": [],
            "active_profile": "",
            "end_timeout_seconds": 0.0,
            "cancelled": False,
            'payload_complete': False, 'end_sent': False, 'sent_unconfirmed': False,
        }
        self._gif_transaction = True
        try:
            if self.transport_profile == PROFILE_AUTO:
                profiles = (PROFILE_BASELINE, PROFILE_VENDOR)
            elif self.transport_profile == PROFILE_VENDOR:
                profiles = (PROFILE_VENDOR, PROFILE_BASELINE)
            else:
                profiles = (PROFILE_BASELINE,)
            error = None
            for attempt, profile in enumerate(profiles):
                timings["attempt_profiles"].append(profile)
                try:
                    result = self._send_gif_once(
                        data, timings, profile, cancelled=cancelled,
                    )
                    timings["active_profile"] = profile
                    self.flash_manager.receipt(timings['identity'], wrote=result,
                                               scene=getattr(self, "flash_scene", "scene"))
                    return result
                except TransferCancelled:
                    timings["cancelled"] = True
                    raise
                except GifCommitUnconfirmed:
                    # A fully sent GIF is not a reason to resend its payload
                    # with a different profile and risk another flash write.
                    raise
                except LinkError as caught:
                    error = caught
                    if timings["body_reserved"] or timings.get('restore_repacked'):
                        # Partial/rejected commits are uncertain, not a reason
                        # to run another body transaction with a new profile.
                        raise
                    if attempt + 1 >= len(profiles):
                        raise
                    timings["transfer_retries"] += 1
                    if self.fd is not None:
                        try:
                            termios.tcflush(self.fd, termios.TCIOFLUSH)
                        except termios.error as error:
                            raise LinkError(f'faceplate serial reset failed: {error}') from error
                    self.rx.clear()
                    time.sleep(TRANSFER_RETRY_SECONDS)
            raise error or LinkError("faceplate GIF transfer failed")
        finally:
            self._gif_transaction = False
            if (timings["body_reserved"] or timings["end_sent"]) and timings["active_profile"] == "":
                self.flash_manager.receipt(timings['identity'], error=True,
                                           scene=getattr(self, "flash_scene", "scene"))
            elif timings["active_profile"] == "":
                self.flash_manager.invalidate()
            timings["total_ms"] = round((time.monotonic() - total_started) * 1000)
            self.last_transfer_timings = timings
