# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Coordinate Faceplate GIF scenes and autonomous firmware modes."""

from __future__ import annotations

import copy
from contextlib import contextmanager
import hashlib
import json
import math
from collections import OrderedDict
import os
import threading
import time
import zlib
from datetime import datetime
from pathlib import Path

from .continuous_return import ContinuousReturn
from . import artwork as artwork_render
from . import gif, protocol
from .power import POWER_BUDGET
from .flash import FlashWearProtection, UploadDeferred, install_manager
from .performance_policy import CONSENT_REVISION, interval_seconds
from .gif_transform import rotate_gif
from .artwork_layout import validate_layout
from .steamgriddb import SteamGridDBFaceplate
from .scenes import WEATHER_VARIANTS
from .transport import (
    Link, LinkError, NativeClockRejected, TransferCancelled, GifCommitUnconfirmed, device_identity, find_port,
    port_owner_details,
)

POWER_EVENT_LOCK_TIMEOUT_SECONDS = 2.5
STATUS_HARDWARE_CACHE_SECONDS = 15.0
RECENT_DETECTION_SECONDS = 600.0
MAX_ASSET_BYTES = protocol.MAX_GIF_BYTES
FACEPLATE_FRAME_SECONDS = 0.1
STATE_SCHEMA = 2
UPLOAD_JOURNAL_LIMIT = 64
FLASH_CAPACITY_BYTES = 2 * 1024 * 1024
ASSETS = {
    ("rain", 0): "weather/rain-bluewater-64x54.gif",
    ("rain", 1): "weather/rain-pearl-64x54.gif",
}
# Peak average RGB load measured across every decoded frame. Both Rain assets
# stay well below Pixel Faceplate's conservative 0.50 USB-A power budget at
# 100%. The hashes are pinned in the backend tests, so an asset change must
# deliberately remeasure these values.
ASSET_PEAK_LOADS = {
    ("rain", 0): 0.2871,
    ("rain", 1): 0.2872,
}


def encode_frame(rgb: bytes) -> bytes:
    palette, indices = gif.quantize(rgb)
    return gif.encode(protocol.WIDTH, protocol.HEIGHT, palette, [indices])


def safe_brightness(level: int, peak_load=None) -> int:
    """Clamp the user's command range; legacy load arguments have no effect.

    Normal images and the native clock share the manual setting. Delegated
    clients retain their separate prepared-content admission contract.
    """
    return max(5, min(100, int(level)))


def verify_faceplate_power(link, enabled=True, timeout=0.5):
    """CH340 identification: require a Faceplate power reply before any data."""
    reply = link.command(protocol.power(bool(enabled)), timeout=timeout, retries=2)
    # Existing synthetic test links return None. Real hardware returns Reply.
    if reply is not None and getattr(reply, "status", 1) != 1:
        raise LinkError("Connected CH340 rejected the Faceplate power command")
    return reply


def validate_gif(data: bytes):
    if len(data) < 13 or data[:6] not in (b"GIF87a", b"GIF89a"):
        raise ValueError("faceplate asset is not a complete GIF")
    width = int.from_bytes(data[6:8], "little")
    height = int.from_bytes(data[8:10], "little")
    if (width, height) != (protocol.WIDTH, protocol.HEIGHT):
        raise ValueError(f"faceplate GIF must be {protocol.WIDTH}x{protocol.HEIGHT}")
    if not data[10] & 0x80:
        raise ValueError("faceplate GIF requires a global colour table")
    if len(data) > MAX_ASSET_BYTES:
        raise ValueError("faceplate GIF exceeds the 192 KiB transfer limit")


class FaceplateCoordinator(ContinuousReturn):
    """Sole serial owner for budgeted GIF scenes and one-shot native clocks."""

    def __init__(self, asset_root: str | Path, state_path: str | Path, logger=None,
                 link_factory=Link, monotonic=time.monotonic, wall_clock=time.time,
                 port_finder=find_port, identity_reader=device_identity,
                 sleeper=time.sleep, steamgriddb=None):
        self.asset_root = Path(asset_root)
        self.state_path = Path(state_path)
        self.logger = logger
        self.link_factory = link_factory
        self.monotonic = monotonic
        self.wall_clock = wall_clock
        self.port_finder = port_finder
        self.identity_reader = identity_reader
        self.sleeper = sleeper
        self.steamgriddb = steamgriddb or SteamGridDBFaceplate(logger=logger)
        self.lock = threading.Lock()
        self.enabled = False
        self.brightness = 100
        self.effective_brightness = 100
        self._brightness_command = None
        self._last_brightness_command = None
        self.command_counts = {"brightness": 0, "brightness_deduplicated": 0}
        self.phase = "off"
        self.detail = "Faceplate automation is off"
        self.error = ""
        self.last_asset = ""
        self.last_upload_ms = 0
        self.last_start_ack_ms = 0
        self.last_transfer = {}
        self.last_synchronized = False
        # A delegated/uncertain commit can change the visible mode while the
        # firmware still reports the normal picture's CRC as stored. Clear only
        # after a normal picture has been acknowledged, never on lease release.
        self._delegated_gif_activation_pending = False
        self._screensaver_exit_blank = False
        self.delivery = {'state': 'idle', 'scene': '', 'signature': ''}
        self.native_clock = {
            "state": "idle", "activations_session": 0, "confirmed_session": 0,
            "last_success_at": None, "reason": "", "device_identity": None,
            "error": "", "flash_effect": "unverified",
        }
        self._native_attempt = None
        self._native_result = None
        self.powered = None
        # Legacy content estimate retained for delegated telemetry only.
        # Normal output always follows the saved manual brightness.
        self.displayed_peak_load = 1.0
        self._displayed_power_identity = ""
        self.rotate_180 = False
        self.rotated_gif_cache = OrderedDict()
        self.artwork_style = "logo_dim"
        self.logo_position = "bottom"
        self.artwork_profiles = {}
        self.writes_session = 0
        self.uploads_session = 0
        self.identical_session = 0
        self.failed_session = 0
        self.unconfirmed_session = 0
        self.payload_bytes_written_session = 0
        self.state = self._load_state()
        # Host lifecycle evidence, not a claim about visible pixels. Keep a
        # dark handoff across Decky/plugin restarts until a current scene ACK.
        self._delegated_gif_activation_pending = self.state['delegated_display_pending']
        self._screensaver_exit_blank = self._delegated_gif_activation_pending
        self._restore_alias = None  # One bounded source -> wire representation.
        self._restore_uncertain = None
        self._continuous_return = None
        self._return_trace = {}
        self._return_trace_at = 0.0
        self._journal_saved_at = None
        self._journal_pending = 0
        self.flash = FlashWearProtection(self.state_path.with_name("flash-protection.json"),
                                        monotonic=monotonic, wall_clock=wall_clock,
                                        prior_usage=self.state_path.exists())
        install_manager(self.flash)
        self.performance_interval_seconds = 5
        self.performance_consent = False
        self.performance_next_at = 0.0
        self.performance_last_at = None
        # A wall-clock epoch stored on disk cannot prove that the autonomous
        # panel has not restarted. Only trust epochs observed by this process,
        # and invalidate them when Linux recreates the USB tty node.
        self.known_epochs = {}
        self.device_token = None
        self._status_hardware = ("", [])
        self._status_hardware_expires = 0.0
        self._status_hardware_lock = threading.Lock()
        self._last_detected_at = None
        self._last_device_status = {}
        # A status read must never queue behind a multi-second GIF transfer.
        # Keep one complete snapshot that Decky can reuse while the serial
        # owner holds ``self.lock``.
        self._status_snapshot = {
            "enabled": False, "available": False, "busy": False,
            "recently_detected": False, "last_detected_age_s": None,
            "owners": [], "port": "", "phase": "off",
            "detail": self.detail, "error": "", "brightness": 100,
            "effective_brightness": 100, "displayed_peak_load": 1.0,
            "rotated_180": False, "last_asset": "", "last_upload_ms": 0,
            "last_start_ack_ms": 0, "last_transfer": {},
            "last_synchronized": False, "writes_session": 0,
            "writes_total": int(self.state.get("writes", 0)),
            "upload_observability": {}, "supported_weather": [],
            "flash_protection": self.flash.status(),
            "native_clock": dict(self.native_clock),
            "automatic_artwork": True, "powered": None, "steamgriddb": {},
        }

    def _log(self, level: str, message: str):
        if self.logger:
            getattr(self.logger, level)("[GabeCubeAura Faceplate] " + message)

    def _load_state(self):
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and value.get("schema") in (1, STATE_SCHEMA):
                return self._normalized_state(value)
        except (OSError, ValueError):
            pass
        return self._normalized_state({})

    @staticmethod
    def _normalized_state(value):
        """Migrate the old write counter without discarding Lab history."""
        observability = value.get("observability")
        if not isinstance(observability, dict):
            observability = {}
        journal = observability.get("journal")
        if not isinstance(journal, list):
            journal = []
        daily = observability.get("daily")
        if not isinstance(daily, dict):
            daily = {}
        assets = value.get("assets")
        if not isinstance(assets, dict):
            assets = {}
        writes = max(0, int(value.get("writes", 0) or 0))
        pending = value.get('delegated_display_pending')
        if not isinstance(pending, bool):
            # Upgrade recovery for the actual Lab147 report: an unconfirmed
            # screensaver followed by an unconfirmed current-route restore.
            pending = False
            for event in journal[-UPLOAD_JOURNAL_LIMIT:]:
                if not isinstance(event, dict):
                    continue
                if event.get('scene') == 'screensaver':
                    pending = True
                elif event.get('outcome') == 'written' or (
                        event.get('outcome') == 'identical' and event.get('stored_display_restarted')):
                    pending = False
        return {
            "schema": STATE_SCHEMA,
            'delegated_display_pending': pending,
            "writes": writes,
            "assets": assets,
            "observability": {
                "attempts": max(0, int(observability.get("attempts", writes) or 0)),
                "identical": max(0, int(observability.get("identical", 0) or 0)),
                "failed": max(0, int(observability.get("failed", 0) or 0)),
                "unconfirmed": max(0, int(observability.get('unconfirmed', 0) or 0)),
                "writes_measured": max(
                    0, int(observability.get("writes_measured", 0) or 0),
                ),
                "payload_bytes_written": max(
                    0, int(observability.get("payload_bytes_written", 0) or 0),
                ),
                "daily": {
                    "date_utc": str(daily.get("date_utc", ""))[:10],
                    "attempts": max(0, int(daily.get("attempts", 0) or 0)),
                    "writes": max(0, int(daily.get("writes", 0) or 0)),
                    "identical": max(0, int(daily.get("identical", 0) or 0)),
                    "failed": max(0, int(daily.get("failed", 0) or 0)),
                    "unconfirmed": max(0, int(daily.get('unconfirmed', 0) or 0)),
                    "payload_bytes_written": max(
                        0, int(daily.get("payload_bytes_written", 0) or 0),
                    ),
                },
                "journal": [item for item in journal[-UPLOAD_JOURNAL_LIMIT:]
                            if isinstance(item, dict)],
            },
        }

    def _save_state(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(self.state_path.name + ".tmp")
        temporary.write_text(json.dumps(self.state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.state_path)

    def _persist_delegated_pending(self, pending, required=False):
        pending = bool(pending)
        self._delegated_gif_activation_pending = pending
        if self.state.get('delegated_display_pending') == pending:
            return
        self.state['delegated_display_pending'] = pending
        try:
            self._save_state()
        except OSError as error:
            # Keep recovery state in memory if optional storage is unavailable.
            self.state['delegated_display_pending'] = pending
            self._log('warning', 'could not persist display handoff: ' + str(error)[:120])
            if pending and required:
                # Do not begin a delegation whose recovery marker is not durable.
                self._log('warning', 'Continuing display handoff with in-memory recovery state')

    def _retained_restore(self, data, token):
        """Suppress an identical uncertain recovery, not new content/reconnects."""
        uncertain = self._restore_uncertain
        if uncertain and uncertain['key'] == (hashlib.sha256(data).hexdigest(), token):
            self.last_transfer = dict(uncertain['transfer'])
            return {'attempted': False, 'synchronized': False,
                    'retry_suppressed': True, 'error': uncertain['error'],
                    'transfer': dict(self.last_transfer),
                    'sent_unconfirmed': uncertain['sent_unconfirmed']}
        return None

    def retry_uncertain_restore(self):
        """Permit one caller-authorized retry; no packets or power change here.

        Engine owns the delay/attempt limit. Incomplete bodies and negative
        acknowledgements cannot use this path, nor can a busy serial owner.
        The next send still uses normal BEGIN/body/END and flash accounting.
        """
        if not self.lock.acquire(blocking=False):
            return False
        try:
            uncertain = self._restore_uncertain
            receipt = uncertain.get('transfer', {}) if uncertain else {}
            if not (self._screensaver_exit_blank and uncertain
                    and uncertain.get('sent_unconfirmed')
                    and receipt.get('payload_complete') and receipt.get('end_sent')):
                return False
            self._restore_uncertain = None
            return True
        finally:
            self.lock.release()

    def restoration_status(self):
        return {'pending': bool(self._delegated_gif_activation_pending),
                'held_dark': bool(self._screensaver_exit_blank),
                'power_off_confirmed': self.powered is False,
                'retry_suppressed': self._restore_uncertain is not None,
                'wire_alias_cached': self._restore_alias is not None,
                'continuous_return': self.continuous_return_status(),
                'physical_playback': 'not-measured'}

    @staticmethod
    def _utc_day(timestamp: float) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(timestamp))

    @staticmethod
    def _asset_identity(data: bytes):
        return hashlib.sha256(data).hexdigest(), f"{zlib.crc32(data) & 0xffffffff:08x}"

    def configure_performance(self, interval=5, consent=""):
        self.performance_interval_seconds = interval_seconds(interval)
        if self.performance_last_at is not None:
            self.performance_next_at = self.performance_last_at + self.performance_interval_seconds
        self.performance_consent = False
        self.flash.configure_performance(False)

    def _upload_priority(self, scene, reason=""):
        return ("player-city-restore" if scene == 'player-city' and reason == 'player-city-confirmed-restore' else
                    "player-city" if scene == "player-city" else
                    "restore" if reason in {"gabe-finished-current-route", "current-route-restore", "broker-current-route-restore"} else
                    "assistant" if scene == "gabe" else
                    "interactive" if scene == "artwork" or "preview" in reason.lower() else "background")

    def _observe_power_device(self, port):
        """A remembered image belongs only to the USB session that confirmed it."""
        token = self.identity_reader(port)
        changed = token != self.device_token
        if changed:
            self.known_epochs.clear()
            self.flash.invalidate()
            self.device_token = token
            self.displayed_peak_load = 1.0
            self._displayed_power_identity = ""
            self._brightness_command = None
            self._last_brightness_command = None
        return changed

    def _write_brightness(self, link, level, *, force=False):
        """Deduplicate emitted commands only; not an ACK/readback guarantee."""
        port = getattr(link, "port", None)
        token = self.identity_reader(port) if port else self.device_token
        wanted = (token, int(level))
        if (not force and self._continuous_return and token==self._continuous_return['device']
                and self.effective_brightness==int(level)):
            self.command_counts['brightness_deduplicated']+=1
            return False
        if not force and self._brightness_command == wanted:
            self.command_counts["brightness_deduplicated"] += 1
            return False
        if self._continuous_return:self._return_event('brightness',percent=int(level))
        link.write(protocol.brightness(int(level)))
        self._brightness_command = wanted
        self._last_brightness_command = wanted
        self.effective_brightness = int(level)
        self.command_counts["brightness"] += 1
        return True

    @contextmanager
    def _upload_link(self, port, data, scene, reason="", *, allow_brightness=True):
        # Admission check before changing the previous picture's brightness.
        self.flash.preflight(data, self._upload_priority(scene, reason))
        with self.link_factory(port=port, log=lambda message: self._log("debug", message)) as link:
            try:
                if scene != 'screensaver':self._prepare_return_link(link,len(data))
                yield link
            except Exception:
                if self._continuous_return:
                    try:self._fail_continuous_return(link,'transfer-failed')
                    except (OSError,ValueError,LinkError):pass
                # Recover the user's command after a failed normal transfer.
                # Uncertainty changes the delivery state, never the gain.
                if allow_brightness:
                    try:
                        self._write_brightness(link, safe_brightness(self.brightness))
                    except (OSError, ValueError, LinkError):
                        pass
                raise

    def _send_protected(self, link, data, *, scene, reason="", cancelled=None):
        priority = self._upload_priority(scene, reason)
        if isinstance(link, Link):
            source_sha = hashlib.sha256(data).hexdigest()
            if scene != 'screensaver' and self._restore_alias and self._restore_alias[0] == source_sha:
                data = self._restore_alias[1]
            link.flash_manager = self.flash
            link.flash_priority = priority
            link.flash_scene = scene
            if scene == 'screensaver':
                self._persist_delegated_pending(True, required=True)
                self._restore_uncertain = None
            link.restore_stored_gif = bool(scene != 'screensaver' and self._delegated_gif_activation_pending)
            link.activate_stored_gif = bool(
                self._native_attempt is not None or self.last_asset == 'native-clock'
                or self._delegated_gif_activation_pending
            )
            try:
                if getattr(link,'preserve_running_gif',False):
                    original_cancelled=cancelled
                    cancelled=lambda:self._return_cancelled(link,original_cancelled)
                result = link.send_gif(data, cancelled=cancelled)
                self._native_attempt = None
                self.native_clock["state"] = "inactive"
                return result
            except Exception as error:
                self.flash.invalidate()
                if link.last_transfer_timings.get("begin_attempted"):
                    self._native_attempt = None
                    self.native_clock["state"] = "unknown"
                # Partial/rejected pictures cannot inherit the old estimate.
                if link.last_transfer_timings.get("body_reserved"):
                    self.displayed_peak_load = 1.0
                    self._displayed_power_identity = ""
                if (isinstance(error, LinkError) and (not isinstance(error, TransferCancelled) or self._continuous_return is not None)
                        and link.last_transfer_timings.get('body_reserved')
                        and scene != 'screensaver' and (self._screensaver_exit_blank or self._continuous_return)):
                    self._restore_uncertain = {'key': (source_sha, self.device_token),
                        'error': str(error)[:180], 'transfer': dict(link.last_transfer_timings),
                        'sent_unconfirmed': isinstance(error, GifCommitUnconfirmed)}
                raise
            finally:
                if self._continuous_return:
                    receipt=getattr(link,'last_transfer_timings',{})
                    self._return_event('gif-receipt',**{k:receipt[k] for k in ('chunks','chunks_ms','finalize_ms','total_ms','begin_status','end_status','end_sent','sent_unconfirmed') if k in receipt})
                wire = getattr(link, 'last_wire_data', data)
                if scene != 'screensaver' and wire != data:
                    self._restore_alias = (source_sha, wire)
        # Injected adapters have no device CRC preflight: reserve conservatively.
        wanted = self.flash.preflight(data, priority)
        self.flash.reserve_body(wanted, priority)
        try:
            wrote = link.send_gif(data, cancelled=cancelled) if cancelled is not None else link.send_gif(data)
        except Exception:
            self._native_attempt = None
            self.native_clock["state"] = "unknown"
            self.displayed_peak_load = 1.0
            self._displayed_power_identity = ""
            self.flash.receipt(wanted, error=True, scene=scene)
            raise
        self.flash.receipt(wanted, wrote=wrote, scene=scene)
        self._native_attempt = None
        self.native_clock["state"] = "inactive"
        return wrote

    def _deferred(self, error, scene):
        self.phase = "deferred"
        self.detail = "Flash protection: keeping the last picture; only the latest route will be retried"
        self.error = ""
        self.last_synchronized = False
        self.delivery = {"state": "deferred", "scene": scene, "signature": ""}
        return {"attempted": False, "wrote": False, "synchronized": False,
                "deferred": True, "retry_after": error.retry_after, "scene": scene}

    def _record_upload(self, *, reason: str, data: bytes, wrote, duration_ms: int,
                       scene: str = "",
                       transfer=None, error: str = "", unconfirmed=False):
        """Persist a bounded, secret-free account of a hardware GIF attempt."""
        timestamp = float(self.wall_clock())
        # Unlimited opt-in telemetry must not create an unbounded host hash
        # catalogue. Historic transaction counters remain intact.
        while len(self.state["assets"]) > 128:
            self.state["assets"].pop(next(iter(self.state["assets"])))
        sha256, crc32 = self._asset_identity(data)
        transfer = dict(transfer or {})
        wire_identity = transfer.get('identity') or {}
        size_bytes = int(wire_identity.get('size', len(data)))
        source_sha = sha256
        sha256 = wire_identity.get('sha256', sha256)
        crc32 = f"{wire_identity['crc32']:08x}" if 'crc32' in wire_identity else crc32
        identical = wrote is False and not error and not unconfirmed
        outcome = 'unconfirmed' if unconfirmed else "failed" if error else "written" if wrote else "identical"
        event = {
            "timestamp": timestamp,
            "timestamp_utc": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp),
            ),
            "reason": str(reason or "unspecified")[:96],
            "scene": str(scene or str(reason).partition(":")[0] or "scene")[:32],
            "sha256": sha256,
            "crc32": crc32,
            "size_bytes": size_bytes,
            "ack_ms": int(transfer.get("begin_ack_ms", transfer.get("begin_ms", 0)) or 0),
            "duration_ms": max(0, int(duration_ms or 0)),
            "outcome": outcome,
            "wrote": None if unconfirmed else bool(wrote),
            "identical": identical,
            "end_sent": bool(transfer.get('end_sent')),
            "stored_display_restarted": bool(transfer.get('stored_display_restarted')),
            'restore_repacked': bool(transfer.get('restore_repacked')),
        }
        if sha256 != source_sha:
            event['source_sha256'] = source_sha
        if error:
            event["error"] = str(error)[:180]
        for key in ('failed_chunk', 'chunk_status', 'payload_bytes_confirmed'):
            if key in transfer:
                event[key] = int(transfer[key])

        observed = self.state["observability"]
        observed["attempts"] += 1
        if unconfirmed:
            observed['unconfirmed'] += 1
        elif wrote:
            observed["writes_measured"] += 1
            observed["payload_bytes_written"] += size_bytes
        elif identical:
            observed["identical"] += 1
        else:
            observed["failed"] += 1
        journal = observed["journal"]
        journal.append(event)
        del journal[:-UPLOAD_JOURNAL_LIMIT]

        day_key = self._utc_day(timestamp)
        daily = observed["daily"]
        if daily.get("date_utc") != day_key:
            daily.clear()
            daily.update({
                "date_utc": day_key, "attempts": 0, "writes": 0,
                "identical": 0, "failed": 0, 'unconfirmed': 0, "payload_bytes_written": 0,
            })
        daily["attempts"] += 1
        if unconfirmed:
            daily['unconfirmed'] += 1
        elif wrote:
            daily["writes"] += 1
            daily["payload_bytes_written"] += size_bytes
        elif identical:
            daily["identical"] += 1
        else:
            daily["failed"] += 1

        self.uploads_session += 1
        if unconfirmed:
            self.unconfirmed_session += 1
        elif wrote:
            self.payload_bytes_written_session += size_bytes
        elif identical:
            self.identical_session += 1
        else:
            self.failed_session += 1
        self._journal_pending += 1
        self.flush_statistics()
        return event

    def flush_statistics(self, force=False):
        if not self._journal_pending:
            return
        if (not force and self._journal_saved_at is not None
                and time.monotonic() - self._journal_saved_at < 60):
            return
        try:
            self._save_state()
            self._journal_pending = 0
            self._journal_saved_at = time.monotonic()
        except OSError as caught:
            # Observability must never turn an acknowledged hardware write
            # into a reported transfer failure. Keep the in-memory counters
            # and surface a bounded diagnostic through the regular logger.
            self._log("warning", "could not persist upload journal: " + str(caught)[:120])

    def _observability_status(self):
        observed = self.state["observability"]
        today = self._utc_day(float(self.wall_clock()))
        daily = dict(observed["daily"])
        if daily.get("date_utc") != today:
            daily = {
                "date_utc": today, "attempts": 0, "writes": 0,
                "identical": 0, "failed": 0, "payload_bytes_written": 0,
            }
        total_bytes = int(observed.get("payload_bytes_written", 0))
        return {
            "journal_limit": UPLOAD_JOURNAL_LIMIT,
            "journal": [dict(item) for item in observed["journal"]],
            "session": {
                "attempts": self.uploads_session,
                "writes": self.writes_session,
                "identical": self.identical_session,
                "failed": self.failed_session,
                'unconfirmed': self.unconfirmed_session,
                "payload_bytes_written": self.payload_bytes_written_session,
            },
            "today_utc": daily,
            "total": {
                "attempts": int(observed.get("attempts", 0)),
                "writes": int(self.state.get("writes", 0)),
                "writes_measured": int(observed.get("writes_measured", 0)),
                "identical": int(observed.get("identical", 0)),
                "failed": int(observed.get("failed", 0)),
                'unconfirmed': int(observed.get('unconfirmed', 0)),
                "payload_bytes_written": total_bytes,
            },
            "estimate": {
                "method": "payload-accounting-not-physical-wear",
                "confidence": "physical-endurance-unknown",
                "assumed_flash_bytes": FLASH_CAPACITY_BYTES,
                "unmeasured_legacy_writes": max(
                    0, int(self.state.get("writes", 0))
                    - int(observed.get("writes_measured", 0)),
                ),
            },
        }

    def configure(self, enabled: bool, brightness: int):
        with self.lock:
            self.enabled = bool(enabled)
            self.brightness = max(5, min(100, int(brightness)))
            self.effective_brightness = safe_brightness(self.brightness)
            if not self.enabled:
                self.phase = "off"
                self.detail = "Faceplate automation is off"
            elif self.phase == "off":
                self.phase = "ready"
                self.detail = "Ready; game artwork and supported scenes follow automatically"

    def configure_artwork(self, style="logo_dim", position="bottom",
                          profiles=None, rotate=False):
        """Update lightweight presentation settings without touching hardware."""
        validate_layout(style, position)
        with self.lock:
            if self.rotate_180 != bool(rotate):
                self.rotated_gif_cache.clear()
            self.rotate_180 = bool(rotate)
            self.artwork_style = style
            self.logo_position = position
            self.artwork_profiles = dict(profiles or {})

    def artwork_presentation(self, appid):
        profile = self.artwork_profiles.get(str(appid), {})
        return (profile.get("style", self.artwork_style),
                profile.get("position", self.logo_position))

    def _orient_gif(self, data):
        """Cached 180° transform of all frames, with no external media decoder."""
        if not self.rotate_180:
            return data
        digest = hashlib.sha256(data).digest()
        cached = self.rotated_gif_cache.get(digest)
        if cached is not None:
            self.rotated_gif_cache.move_to_end(digest)
            return cached
        converted = rotate_gif(data)
        self.rotated_gif_cache[digest] = converted
        while len(self.rotated_gif_cache) > 6:
            self.rotated_gif_cache.popitem(last=False)
        return converted

    def supports(self, condition: str, variant: int) -> bool:
        return condition in WEATHER_VARIANTS and 0 <= int(variant) < len(
            WEATHER_VARIANTS[condition]
        )

    def _hardware_status(self, *, scan_owners=True):
        """Return a cached USB snapshot without taking the serial lock."""
        now = self.monotonic()
        port = self.port_finder() or ""
        with self._status_hardware_lock:
            if port: self._last_detected_at = now
            if now < self._status_hardware_expires and port == self._status_hardware[0]:
                return self._status_hardware
            owners = port_owner_details(port) if port and scan_owners else []
            self._status_hardware = (port, owners)
            self._status_hardware_expires = now + STATUS_HARDWARE_CACHE_SECONDS
            return self._status_hardware

    def _presence_status(self, port, *, observed=True):
        """Session-local monotonic recency, independent of power or automation.

        A cached content/ACK/port owner is not a new physical detection.
        No disk writes, USB commands, serial lock or additional observer.
        """
        if not port and self.flash.hardware_state != "unknown":
            self.flash.invalidate()
        now = self.monotonic()
        with self._status_hardware_lock:
            if observed and port: self._last_detected_at = now
            age = None if self._last_detected_at is None else max(0.0, now-self._last_detected_at)
        return {"recently_detected": bool(port) or age is not None and age < RECENT_DETECTION_SECONDS,
                "last_detected_age_s": None if age is None else round(age, 3)}

    def device_status(self):
        """Cheap continuity probe used by the one-second engine loop.

        Process-owner discovery walks ``/proc`` and belongs to diagnostics,
        not to the Dashboard scheduler.  A cached owner result is retained
        when it still describes the same tty, but this method never starts a
        new owner scan.
        """
        port = self.port_finder() or ""
        now = self.monotonic()
        with self._status_hardware_lock:
            cached_port, cached_owners = self._status_hardware
            owners = (
                cached_owners
                if cached_port == port and now < self._status_hardware_expires else []
            )
        observed = {"available": bool(port), "busy": bool(owners), "port": port,
                    "device_identity": self.identity_reader(port) if port else None,
                    **self._presence_status(port)}
        if not port:
            self._brightness_command = None
        # Atomic replacement keeps the Apply receipt current even if the
        # complete status snapshot has never acquired the busy serial lock.
        self._last_device_status = observed
        return dict(observed)

    def _status_payload(self, port, owners):
        return {
            "command_counts": dict(self.command_counts),
            "enabled": self.enabled,
            "available": bool(port),
            **self._presence_status(port, observed=False),
            "busy": bool(owners),
            "owners": owners,
            "port": port,
            "phase": self.phase,
            "detail": self.detail,
            "error": self.error,
            "brightness": self.brightness,
            "effective_brightness": self.effective_brightness,
            "brightness_control": self._brightness_status(),
            "displayed_peak_load": self.displayed_peak_load,
            "rotated_180": self.rotate_180,
            "last_asset": self.last_asset,
            "last_upload_ms": self.last_upload_ms,
            "last_start_ack_ms": self.last_start_ack_ms,
            "last_transfer": dict(self.last_transfer),
            "last_synchronized": self.last_synchronized,
            'delivery': dict(self.delivery),
            'restoration': self.restoration_status(),
            "writes_session": self.writes_session,
            "writes_total": int(self.state.get("writes", 0)),
            "upload_observability": self._observability_status(),
            "flash_protection": self.flash.status(),
            "native_clock": dict(self.native_clock),
            "supported_weather": [
                f"{condition}:{variant}"
                for condition, variants in WEATHER_VARIANTS.items()
                for variant in range(len(variants))
            ],
            "automatic_artwork": True,
            "powered": self.powered,
            "steamgriddb": self.steamgriddb.status(),
        }

    def _brightness_status(self):
        """Separate the manual target from the last unacknowledged USB write."""
        # Deduplication may be invalidated by power changes while the history
        # of the last emitted command remains useful. Neither is a readback.
        command = self._last_brightness_command
        if command and command[0] != self.device_token:
            command = None
        target = safe_brightness(self.brightness)
        return {
            "requested_percent": self.brightness,
            "target_percent": target,
            "last_commanded_percent": command[1] if command else None,
            "command_acknowledged": False,
            "limit_reason": "none",
            "content_sha256": self._displayed_power_identity,
            "mode": "manual",
            "estimate_source": "not-used",
            "peak_rgb_load": None,
            "power_budget": None,
        }

    def cached_status(self):
        """Nonblocking receipt view; no port discovery, owner scan or media IO.

        Decky uses this only after an explicit Apply, until the existing worker
        completes. Scalar progress fields remain readable while USB is busy.
        Hardware presence stays last-observed, not a fresh physical guarantee.
        """
        snapshot = copy.deepcopy(self._status_snapshot)
        snapshot.update(self._last_device_status)
        snapshot.update({
            "enabled": self.enabled, "phase": self.phase, "detail": self.detail,
            "error": self.error, "brightness": self.brightness,
            "effective_brightness": self.effective_brightness,
            "brightness_control": self._brightness_status(),
            "displayed_peak_load": self.displayed_peak_load,
            "rotated_180": self.rotate_180, "last_asset": self.last_asset,
            "last_upload_ms": self.last_upload_ms,
            "last_start_ack_ms": self.last_start_ack_ms,
            "last_transfer": dict(self.last_transfer),
            "last_synchronized": self.last_synchronized,
            "delivery": dict(self.delivery), "powered": self.powered,
            'restoration': self.restoration_status(),
            "flash_protection": self.flash.status(),
            "native_clock": dict(self.native_clock),
            "writes_session": self.writes_session,
            "writes_total": int(self.state.get("writes", 0)),
        })
        return snapshot

    def status(self):
        if not self.lock.acquire(blocking=False):
            port = self.port_finder() or ""
            now = self.monotonic()
            with self._status_hardware_lock:
                cached_port, cached_owners = self._status_hardware
                owners = (
                    cached_owners
                    if cached_port == port and now < self._status_hardware_expires else []
                )
            # Python assignments of these scalar fields are atomic. They make
            # the retained snapshot truthful enough to show upload progress
            # without ever stalling Decky's RPC/UI thread.
            snapshot = copy.deepcopy(self._status_snapshot)
            snapshot.update({
                "enabled": self.enabled,
                "available": bool(port), "busy": bool(owners),
                **self._presence_status(port),
                "owners": list(owners), "port": port,
                "phase": self.phase, "detail": self.detail,
                "error": self.error, "brightness": self.brightness,
                "effective_brightness": self.effective_brightness,
                "brightness_control": self._brightness_status(),
                "last_asset": self.last_asset,
                "last_upload_ms": self.last_upload_ms,
                "last_start_ack_ms": self.last_start_ack_ms,
                "last_synchronized": self.last_synchronized,
                'delivery': dict(self.delivery),
                'restoration': self.restoration_status(),
                'native_clock': dict(self.native_clock),
                "powered": self.powered,
            })
            self._last_device_status = {key: snapshot[key] for key in (
                "available", "busy", "port", "recently_detected", "last_detected_age_s",
            )}
            return snapshot
        try:
            port, owners = self._hardware_status()
            snapshot = self._status_payload(port, owners)
            self._status_snapshot = copy.deepcopy(snapshot)
            self._last_device_status = {key: snapshot[key] for key in (
                "available", "busy", "port", "recently_detected", "last_detected_age_s",
            )}
            return snapshot
        finally:
            self.lock.release()

    def set_power(self, enabled: bool, reason="manual", lock_timeout=None):
        """Volatile power command; never wait forever for a GIF commit."""
        timeout = POWER_EVENT_LOCK_TIMEOUT_SECONDS if lock_timeout is None else max(
            0.0, float(lock_timeout),
        )
        if not self.lock.acquire(timeout=timeout):
            return {"ok": False, "powered": self.powered,
                    "error": "Faceplate busy uploading; power change deferred"}
        try:
            if not enabled and reason == 'screensaver-exit':
                # Record intent even if the Off ACK is lost. A missing reply
                # cannot authorize a later automatic On of the old content.
                self._screensaver_exit_blank = True
                self._persist_delegated_pending(True)
            if not enabled and self._continuous_return:
                self._screensaver_exit_blank=True
                self._end_continuous_return('interrupted','power-off')
            if enabled and reason in {"automatic power recovery", "automatic resume"}:
                port = self.port_finder()
                current = (self.delivery.get("state") == "confirmed"
                           and not self._delegated_gif_activation_pending
                           and self.delivery.get("scene") != "screensaver"
                           and port and self.identity_reader(port) == self.device_token)
                if not current:
                    # USB/host restart may autonomously replay a stored DAS GIF.
                    # Only the fresh current-route ACK may authorize power On.
                    self._screensaver_exit_blank = True
                    self._persist_delegated_pending(True)
                    return {'ok': False, 'powered': self.powered, 'error': '',
                            'deferred_to_route': True}
            if enabled and self._continuous_return:
                return {'ok':False,'powered':self.powered,'error':'','deferred_to_route':True}
            if enabled and self._screensaver_exit_blank:
                # An old queued On must not undo the ACKed exit Off. Returning
                # deferred (not success) lets Engine clear the stale power job
                # and reconcile the current route, which owns the eventual On.
                return {'ok': False, 'powered': self.powered, 'error': '',
                        'deferred_to_route': True}
            port = self.port_finder()
            if not port:
                self.phase = "error"
                self.error = "faceplate not found (no JSAUX CH340 ttyUSB)"
                self.detail = "Faceplate power command failed"
                return {"ok": False, "powered": self.powered, "error": self.error}
            try:
                self._observe_power_device(port)
                with self.link_factory(
                    port=port, log=lambda message: self._log("debug", message),
                ) as link:
                    if enabled:
                        # Reapply the saved command before autonomous replay.
                        level = safe_brightness(self.brightness)
                        self._write_brightness(link, level, force=True)
                        self.effective_brightness = level
                    self._power_command(link, enabled, timeout=0.7)
                self._native_attempt = None
                self.native_clock["state"] = "idle"
                self.powered = bool(enabled)
                self.flash.invalidate()
                self._brightness_command = None
                self.error = ""
                self.phase = "ready" if enabled else "powered-off"
                self.detail = (
                    f"Faceplate powered on ({reason})"
                    if enabled else f"Faceplate powered off ({reason}); stored GIF preserved"
                )
                return {"ok": True, "powered": self.powered, "error": ""}
            except (OSError, ValueError, LinkError) as error:
                self.phase = "error"
                self.error = str(error)[:180]
                self.detail = "Faceplate power command failed"
                self._log("warning", self.error)
                return {"ok": False, "powered": self.powered, "error": self.error}
        finally:
            self.lock.release()

    def set_brightness(self, brightness: int, reason="manual"):
        """Apply the manual command without decoding or rewriting the GIF."""
        with self.lock:
            self.brightness = max(5, min(100, int(brightness)))
            if not self.enabled:
                return {"ok": False, "brightness": self.brightness,
                        "error": "Faceplate automation is off"}
            port = self.port_finder()
            if not port:
                self.phase = "error"
                self.error = "faceplate not found (no JSAUX CH340 ttyUSB)"
                return {"ok": False, "brightness": self.brightness, "error": self.error}
            try:
                new_device = self._observe_power_device(port)
                applied = safe_brightness(self.brightness)
                with self.link_factory(
                    port=port, log=lambda message: self._log("debug", message),
                ) as link:
                    if self._continuous_return:self._prepare_return_link(link)
                    keep_off = self.powered is False or self._screensaver_exit_blank
                    if new_device or self.powered is not True:
                        # Identify the MCU while dark before an unknown stored
                        # picture can replay. An unresponsive CH340 gets no gain.
                        verify_faceplate_power(link, False, timeout=0.7)
                        self._write_brightness(link, applied)
                        if not keep_off:
                            self._begin_scene_power(link)
                    else:
                        self._begin_scene_power(link)
                        self._write_brightness(link, applied)
                if not keep_off:self.powered = True
                self.effective_brightness = applied
                self.error = ""
                self.detail = (
                    f"Faceplate brightness set to {applied}% "
                    f"(requested {self.brightness}%, {reason})"
                )
                return {"ok": True, "brightness": self.brightness,
                        "effective_brightness": applied, "error": ""}
            except (OSError, ValueError, LinkError) as error:
                self.phase = "error"
                self.error = str(error)[:180]
                self.detail = "Faceplate brightness command failed"
                return {"ok": False, "brightness": self.brightness,
                        "error": self.error}

    def preview_artwork(self, appid: int, source: str = "hero"):
        """Render the exact GIF sent to the panel, without opening the USB port.

        Prefer the already-prepared SteamGridDB payload, never download or
        compile source media at game launch. Explicit Decky previews may
        decode local Steam fallback artwork in this worker thread.
        """
        appid = int(appid)
        if appid <= 0:
            return None, "no-game"
        selected = self.steamgriddb.selected(appid)
        if selected is not None:
            data = selected[0]
            origin = "prepared"
        else:
            style, position = self.artwork_presentation(appid)
            rgb, _, origin = artwork_render.artwork(
                appid, source, style=style, position=position,
            )
            if rgb is None:
                return None, "not-found"
            data = encode_frame(rgb)
        validate_gif(data)
        result = self._orient_gif(data)
        validate_gif(result)
        return result, origin

    supports_source_projection_callback = True

    def synchronize_artwork(self, appid: int, source: str = "hero", *, source_ready=None, reason=None, cancelled=None, home=False):
        """Render and upload the current game's local artwork once.

        Rendering happens outside the serial lock because GStreamer can take a
        moment to start. The worker serializes this operation with automatic
        weather requests, so the live LED loop never waits for it.
        """
        def check_current():
            Link._check_cancelled(cancelled)

        data = None
        upload_started = None
        reason = reason or f"artwork:{appid}:{str(source or 'hero')[:32]}"
        try:
            appid = max(0, int(appid or 0))
        except (TypeError, ValueError, OverflowError):
            appid = 0
        if callable(cancelled) and cancelled():
            return {"attempted": False, "synchronized": False, "superseded": True}
        with self.lock:
            if not self.enabled:
                return {"attempted": False, "wrote": False, "found": False}
            brightness = self.brightness
            style, position = self.artwork_presentation(appid)
            self.phase = "rendering"
            self.detail = f"Preparing local artwork for Steam app {appid}"
            self.error = ""
        if not appid:
            return {"attempted": False, "wrote": False, "found": False}

        try:
            check_current()
            # Never search, download or compile here. A game launch may use an
            # explicitly activated prepared GIF; otherwise the proven local
            # Steam frame is sent immediately.
            selected = self.steamgriddb.home_selected(appid) if home else self.steamgriddb.selected(appid)
            selected_cached = selected is not None
            selected_animated = False
            selected_square = False
            projection_source = None
            if selected is not None:
                data, manifest, compiled_path = selected
                # Bind to this prepared GIF, not a selection read after USB ACK.
                if manifest.get('dashboard_pack') == 'artwork-dashboard.rgb':
                    projection_source = {'kind': 'artwork',
                        'path': str(Path(compiled_path).parent / 'artwork-dashboard.rgb'),
                        'root': str(self.steamgriddb.artwork_root),
                        'frames': manifest.get('dashboard_pack_frames', 0),
                        'sha256': manifest.get('dashboard_pack_sha256', '')}
                selected_animated = bool(manifest.get("animated"))
                source_width = int(manifest.get("source_width", 0) or 0)
                source_height = int(manifest.get("source_height", 0) or 0)
                selected_square = bool(source_width and source_height and abs(
                    source_width / source_height - 1.0,
                ) < 0.08)
                path = str(compiled_path)
                format_name = str(manifest.get("asset_kind", "grid"))
                actual_source = "steamgriddb-" + format_name + (
                    "-animated" if manifest.get("animated") else ""
                )
                peak_load = POWER_BUDGET
            else:
                rgb, path, actual_source = artwork_render.artwork(
                    appid, source, style=style, position=position,
                )
                if rgb is None:
                    with self.lock:
                        self.phase = "no-artwork"
                        self.detail = f"No local Steam or SteamGridDB artwork for app {appid}; keeping the last picture"
                        self.last_synchronized = False
                    return {"attempted": True, "wrote": False, "found": False, "appid": appid}
                data = encode_frame(rgb)
                peak_load = POWER_BUDGET
                from .source_projection import project_backgrounds
                projection_source = {'kind': 'artwork-strip',
                    'sha256': hashlib.sha256(rgb).hexdigest(),
                    'colours': {mapping + ('-rotated' if rotated else ''):
                        project_backgrounds((rgb,), mapping, rotated)
                        for mapping in ('bottom', 'whole') for rotated in (False, True)}}
            check_current()
            validate_gif(data)
            data = self._orient_gif(data)
            validate_gif(data)
            if callable(source_ready) and projection_source is not None:
                source_ready(dict(projection_source))
            peak_load = POWER_BUDGET
            effective_brightness = safe_brightness(brightness)
            digest = hashlib.sha256(data).hexdigest()
            with self.lock:
                check_current()
                if not self.enabled:
                    return {"attempted": False, "wrote": False, "found": True, "appid": appid}
                port = self.port_finder()
                if not port:
                    raise LinkError("faceplate not found (no JSAUX CH340 ttyUSB)")
                token = self.identity_reader(port)
                retained = self._retained_restore(data, token)
                if retained:
                    return retained
                if token != self.device_token:
                    self.known_epochs.clear()
                    self.flash.invalidate()
                    self.device_token = token
                    self.displayed_peak_load = 1.0
                    self._displayed_power_identity = ""
                self.phase = "uploading"
                self.detail = f"Sending artwork for Steam app {appid}"
                self.delivery = {'state': 'sending', 'scene': 'artwork', 'signature': digest}
                started = self.monotonic()
                upload_started = started
                self.last_transfer = {}
                with self._upload_link(port, data, "artwork", reason) as link:
                    check_current()
                    # Brightness is a volatile command with no ACK. Reapply it
                    # before every persistent GIF exactly as the panel expects.
                    self._write_brightness(link, safe_brightness(brightness))
                    check_current()
                    self._begin_scene_power(link)
                    try:
                        wrote = self._send_protected(link, data, scene="artwork", reason=reason, cancelled=cancelled)
                    finally:
                        self.last_transfer = dict(
                            getattr(link, "last_transfer_timings", {}) or {},
                        )
                    self.displayed_peak_load = float(peak_load)
                    self._displayed_power_identity = hashlib.sha256(data).hexdigest()
                    # Raise brightness only after the new GIF is committed.
                    check_current()
                    self._write_brightness(link, effective_brightness)
                    self._finish_scene_power(link, cancelled=cancelled)
                self.last_upload_ms = round((self.monotonic() - started) * 1000)
                self.last_start_ack_ms = 0
                self.displayed_peak_load = float(peak_load)
                self.effective_brightness = effective_brightness
                self.last_asset = f"artwork:{appid}:{Path(path).name}"
                self.last_synchronized = True
                self.delivery = {'state': 'confirmed', 'scene': 'artwork', 'signature': digest}
                if wrote:
                    self.state["writes"] = int(self.state.get("writes", 0)) + 1
                    self.state["assets"][digest] = {
                        "last_written_at": self.wall_clock(),
                        "asset": self.last_asset,
                        "appid": appid,
                    }
                    self.writes_session += 1
                self._record_upload(
                    reason=reason, data=data, wrote=wrote,
                    scene="artwork",
                    duration_ms=self.last_upload_ms, transfer=self.last_transfer,
                )
                self.phase = "artwork"
                self.detail = (
                    f"Artwork for app {appid} acknowledged"
                    if wrote else f"Artwork for app {appid} already stored; flash write skipped"
                )
                return {
                    "attempted": True,
                    "wrote": wrote,
                    "found": True,
                    "synchronized": True,
                    "appid": appid,
                    "source": actual_source,
                    "path": path,
                    "brightness": effective_brightness,
                    "selected_cached": selected_cached,
                    "selected_animated": selected_animated,
                    "selected_square": selected_square,
                    "projection_source": projection_source,
                }
        except TransferCancelled:
            return {"attempted": upload_started is not None, "synchronized": False,
                    "superseded": True, "cancelled": True, "appid": appid}
        except UploadDeferred as error:
            with self.lock:
                return self._deferred(error, "artwork")
        except GifCommitUnconfirmed as error:
            with self.lock:
                result = self._sent_unconfirmed_locked(data=data, scene='artwork',
                    signature=digest, reason=reason, error=error,
                    started=upload_started, peak_load=peak_load)
                return {**result, 'found': True, 'appid': appid, 'source': actual_source}
        except (OSError, ValueError, LinkError) as error:
            with self.lock:
                if data is not None and upload_started is not None:
                    self.last_upload_ms = round(
                        max(0.0, self.monotonic() - upload_started) * 1000,
                    )
                    self._record_upload(
                        reason=reason, data=data, wrote=None,
                        scene="artwork",
                        duration_ms=self.last_upload_ms, transfer=self.last_transfer,
                        error=str(error),
                    )
                self.phase = "error"
                self.error = str(error)[:180]
                self.detail = "Automatic game artwork failed; the light bar remains active"
                self.last_synchronized = False
            self._log("warning", self.error)
            return {
                "attempted": True, "wrote": False, "found": False,
                "appid": appid, "error": self.error,
            }

    def _sent_unconfirmed_locked(self, *, data, scene, signature, reason, error,
                                 started, peak_load=1.0):
        """Data delivery is not proof of flash commit or playback on the matrix."""
        self.last_upload_ms = round(max(0, self.monotonic() - started) * 1000)
        self.last_synchronized = False
        self.powered = not self._screensaver_exit_blank
        self.phase = 'sent-unconfirmed'
        self.error = str(error)[:180]
        self.detail = 'GIF sent; final USB confirmation unavailable'
        self.delivery = {'state': 'unconfirmed', 'scene': scene, 'signature': signature}
        self.displayed_peak_load = max(self.displayed_peak_load, float(peak_load))
        self.effective_brightness = safe_brightness(self.brightness)
        self._record_upload(reason=reason, data=data, wrote=None, scene=scene,
            duration_ms=self.last_upload_ms, transfer=self.last_transfer,
            error=self.error, unconfirmed=True)
        return {'attempted': True, 'wrote': None, 'scene': scene,
                'signature': signature, 'synchronized': False, 'sent_unconfirmed': True,
                'error': self.error, 'upload_ms': self.last_upload_ms,
                'transfer': dict(self.last_transfer)}

    def _power_command(self,link,enabled,timeout=0.5):
        if self._continuous_return:self._return_event('power-on' if enabled else 'power-off')
        return verify_faceplate_power(link,enabled,timeout=timeout)

    def _begin_scene_power(self,link):
        # Do not resurrect the old autonomous GIF while uploading its
        # replacement after a screensaver exit. This is volatile power only.
        if getattr(link,'preserve_running_gif',False):return None
        reply = self._power_command(link,not self._screensaver_exit_blank)
        if self._screensaver_exit_blank:
            self.powered = False
        return reply

    def _finish_scene_power(self,link,normal=True,cancelled=None):
        if self._return_cancelled(link,cancelled):
            if self._continuous_return:self._fail_continuous_return(link,'cancelled-at-commit')
            raise TransferCancelled('Return superseded')
        if self._screensaver_exit_blank:
            self._power_command(link,True)
            Link._check_cancelled(cancelled)
            self._screensaver_exit_blank=False
        self.powered = True
        if normal:
            if self._continuous_return:self._end_continuous_return('confirmed','replacement-ack')
            self._persist_delegated_pending(False)
            self._restore_uncertain = None

    def synchronize_native_clock(self, *, sync_key, reason="route", cancelled=None):
        """Activate a first-class scene under the sole serial lock, without GIF IO.

        Same-key retries, including lost ACKs, are inert until a real continuity
        event or another scene replaced the panel. No native receipt enters the
        GIF journal/budget. The mode's settings-sector effect remains unknown.
        """
        scene = "native-clock"
        with self.lock:
            if not self.enabled or (self.powered is False and not self._screensaver_exit_blank):
                return {"attempted": False, "synchronized": False, "scene": scene,
                        "error": "Faceplate automation or display power is off"}
            def superseded():
                return callable(cancelled) and cancelled()
            if superseded():
                return {"attempted": False, "superseded": True}
            if self.rotate_180:
                return {"attempted": False, "scene": scene, "synchronized": False,
                        "error": "Native clock cannot rotate 180 degrees; disable Faceplate rotation"}
            port = self.port_finder()
            if not port:
                self.native_clock.update(state="disconnected", error="Faceplate not detected")
                return {"attempted": False, "scene": scene, "error": "Faceplate not detected"}
            token = self.identity_reader(port)
            attempt = (token, str(sync_key))
            if attempt == self._native_attempt:
                # A different scene may have been deferred before any serial
                # IO. Reconcile the retained native receipt without a command.
                if self._native_result.get("synchronized"):
                    self.last_synchronized = True
                    self.last_asset = scene
                    self.phase = scene
                    self.error = ""
                    self.detail = "Native clock synchronized; MCU keeps time autonomously"
                    self.delivery = {"state": "confirmed", "scene": scene, "signature": str(sync_key)}
                return {**self._native_result, "attempted": False, "unchanged": True}
            self.native_clock.update(reason=str(reason)[:96], device_identity=token, error="")
            sent = False
            new_device = token != self.device_token
            try:
                if new_device:
                    self.known_epochs.clear()
                    self.flash.invalidate()
                    self.device_token = token
                    self.displayed_peak_load = 1.0
                    self._displayed_power_identity = ""
                with self.link_factory(port=port, log=lambda message: self._log("debug", message)) as link:
                    if superseded():
                        return {"attempted": False, "superseded": True}
                    # Native mode follows the same manual brightness setting.
                    level = safe_brightness(self.brightness)
                    if new_device or self.powered is None or self.effective_brightness != level:
                        self._write_brightness(link, level)
                        self.effective_brightness = level
                    self._prepare_return_link(link)
                    reply = self._begin_scene_power(link)
                    if reply is None and not getattr(link,'preserve_running_gif',False):
                        raise LinkError("Native clock device identification ACK missing")
                    if superseded():
                        return {"attempted": False, "superseded": True}
                    # Take local SteamOS wall time immediately before transmission;
                    # astimezone() consults the system timezone (including DST).
                    when = datetime.now().astimezone()
                    self._native_attempt = attempt
                    self.native_clock["activations_session"] += 1
                    self.native_clock["state"] = "sending"
                    self.delivery = {"state": "sending", "scene": scene, "signature": str(sync_key)}
                    self.last_synchronized = False
                    self.known_epochs.clear()
                    self.flash.invalidate()
                    sent = True
                    self.displayed_peak_load = 1.0
                    self._displayed_power_identity = ""
                    try:link.synchronize_native_clock(when)
                    except Exception:
                        if self._continuous_return:self._fail_continuous_return(link,'native-failed')
                        raise
                    if self._continuous_return:self._return_event('native-clock-ack')
                    self._finish_scene_power(link,cancelled=cancelled)
                self.native_clock.update(state="confirmed", last_success_at=when.isoformat(), error="")
                self.native_clock["confirmed_session"] += 1
                self.powered = True
                self.displayed_peak_load = 1.0
                self._displayed_power_identity = ""
                self.last_asset = scene
                self.last_synchronized = True
                self.delivery = {"state": "confirmed", "scene": scene, "signature": str(sync_key)}
                self.phase = scene
                self.detail = "Native clock synchronized; MCU keeps time autonomously"
                self.error = ""
                self._native_result = {"attempted": True, "synchronized": True, "scene": scene,
                                       "flash_effect": "unverified"}
                return dict(self._native_result)
            except (OSError, ValueError, LinkError) as error:
                self.error = str(error)[:180]
                self.phase = "error"
                self.detail = "Native clock synchronization not confirmed; no GIF fallback"
                # An IO failure may follow a partial or complete write. Suppress
                # repeated mode commands until a justified new synchronization.
                unconfirmed = sent and not isinstance(error, NativeClockRejected)
                state = "unconfirmed" if unconfirmed else "error"
                self.native_clock.update(state=state, error=self.error)
                result = {"attempted": sent, "synchronized": False, "scene": scene,
                          "sent_unconfirmed": unconfirmed, "error": self.error}
                if sent:
                    self.delivery = {"state": state, "scene": scene, "signature": str(sync_key)}
                    self._native_result = result
                return dict(result)

    def synchronize_scene(self, data: bytes, scene: str, signature: str,
                          peak_load=POWER_BUDGET, reason="scene", cancelled=None,
                          delegated=False, power_profile=None):
        """Upload one already-rendered scene through the sole serial owner.

        Rendering and route decisions happen outside this coordinator.  The
        panel CRC remains the final protection against rewriting an identical
        GIF, while the persisted journal records whether a real write occurred.
        """
        data = bytes(data) if delegated else self._orient_gif(bytes(data))
        # The saved brightness is the command. No media decode, RGB profile
        # lookup or unknown-content dimming runs on this delivery path.
        if not delegated:
            peak_load = 1.0  # Unused legacy field; not an RGB measurement.
        scene = str(scene or "scene")[:32]
        signature = (
            hashlib.sha256(data).hexdigest() if self.rotate_180 and not delegated else
            str(signature or hashlib.sha256(data).hexdigest())[:64]
        )
        reason = str(reason or scene)[:96]
        upload_started = None
        with self.lock:
            if not self.enabled:
                return {"attempted": False, "wrote": False, "scene": scene}
            if delegated and (not isinstance(peak_load, (float, int))
                              or not math.isfinite(peak_load) or not 0 <= peak_load <= 1):
                return {"attempted": False, "wrote": False, "scene": scene,
                        "policy_reason": "CONTENT_INVALID", "error": "Invalid delegated RGB estimate"}
            if delegated and (self.powered is False or
                    self.effective_brightness * float(peak_load) / 100.0 > POWER_BUDGET):
                # A delegate cannot change user brightness/power or send a
                # scene that would require a safety dim. The client may repair
                # its prepared content; the TV remains independent.
                return {"attempted": False, "wrote": False, "scene": scene,
                        "policy_reason": "DISPLAY_OFF" if self.powered is False else "CONTENT_INVALID",
                        "error": "Delegated content exceeds the current safe power envelope"}
            try:
                if callable(cancelled) and cancelled():
                    return {"attempted": False, "wrote": False, "scene": scene,
                            "superseded": True, "cancelled_before_serial": True}
                validate_gif(data)
                if scene == "performance":
                    raise ValueError("CPU/GPU display has been removed from the Faceplate")
                effective_brightness = self.effective_brightness if delegated else safe_brightness(self.brightness)
                port = self.port_finder()
                if not port:
                    raise LinkError("faceplate not found (no JSAUX CH340 ttyUSB)")
                token = self.identity_reader(port)
                retained = None if delegated or scene == 'player-city' else self._retained_restore(data, token)
                if retained:
                    return retained
                if token != self.device_token:
                    self.known_epochs.clear()
                    self.flash.invalidate()
                    self.device_token = token
                    self.displayed_peak_load = 1.0
                    self._displayed_power_identity = ""
                self.phase = "uploading"
                self.detail = f"Sending {scene} scene"
                self.delivery = {'state': 'sending', 'scene': scene, 'signature': signature}
                self.error = ""
                started = self.monotonic()
                upload_started = started
                self.last_transfer = {}
                with self._upload_link(port, data, scene, reason, allow_brightness=not delegated) as link:
                    if not delegated:
                        self._write_brightness(link, safe_brightness(self.brightness))
                    self._begin_scene_power(link)
                    try:
                        wrote = self._send_protected(link, data, scene=scene, reason=reason, cancelled=cancelled)
                    finally:
                        self.last_transfer = dict(
                            getattr(link, "last_transfer_timings", {}) or {},
                        )
                    self.displayed_peak_load = float(peak_load)
                    self._displayed_power_identity = hashlib.sha256(data).hexdigest()
                    # Raise brightness only after the new GIF is committed.
                    if not delegated:
                        self._write_brightness(link, effective_brightness)
                    self._finish_scene_power(link,normal=not delegated,cancelled=cancelled)
                self.last_upload_ms = round((self.monotonic() - started) * 1000)
                self.last_start_ack_ms = int(
                    self.last_transfer.get("begin_ack_ms", 0) or 0
                )
                self.displayed_peak_load = float(peak_load)
                self.effective_brightness = effective_brightness
                self.last_asset = f"{scene}:{signature[:16]}"
                self.last_synchronized = True
                self.delivery = {'state': 'confirmed', 'scene': scene, 'signature': signature}
                self.powered = True
                if wrote:
                    self.state["writes"] = int(self.state.get("writes", 0)) + 1
                    self.state["assets"][hashlib.sha256(data).hexdigest()] = {
                        "last_written_at": self.wall_clock(),
                        "asset": self.last_asset,
                        "scene": scene,
                    }
                    self.writes_session += 1
                self._record_upload(
                    reason=reason, data=data, wrote=wrote,
                    scene=scene,
                    duration_ms=self.last_upload_ms, transfer=self.last_transfer,
                )
                self.phase = scene
                self.detail = (
                    f"{scene.title()} scene acknowledged"
                    if wrote else f"{scene.title()} scene already stored; flash write skipped"
                )
                return {
                    "attempted": True, "wrote": wrote, "scene": scene,
                    "signature": signature, "brightness": effective_brightness,
                    "synchronized": True,
                    "upload_ms": self.last_upload_ms,
                    "ack_ms": int(self.last_transfer.get("total_ms", 0) or 0),
                    "transfer": dict(self.last_transfer),
                }
            except UploadDeferred as error:
                return self._deferred(error, scene)
            except GifCommitUnconfirmed as error:
                return self._sent_unconfirmed_locked(data=data, scene=scene,
                    signature=signature, reason=reason, error=error,
                    started=upload_started, peak_load=peak_load)
            except TransferCancelled:
                if upload_started is not None:
                    self.last_upload_ms = round(
                        max(0.0, self.monotonic() - upload_started) * 1000,
                    )
                self.phase = "superseded"
                self.detail = f"{scene.title()} transfer superseded; keeping the last picture"
                self.error = ""
                return {
                    "attempted": True, "wrote": False, "scene": scene,
                    "signature": signature, "synchronized": False,
                    "superseded": True, "cancelled": True,
                    "upload_ms": self.last_upload_ms,
                    "transfer": dict(self.last_transfer),
                }
            except (OSError, TypeError, ValueError, LinkError) as error:
                if upload_started is not None:
                    self.last_upload_ms = round(
                        max(0.0, self.monotonic() - upload_started) * 1000,
                    )
                    self._record_upload(
                        reason=reason, data=data, wrote=None,
                        scene=scene,
                        duration_ms=self.last_upload_ms, transfer=self.last_transfer,
                        error=str(error),
                    )
                self.phase = "error"
                self.error = str(error)[:180]
                self.detail = f"{scene.title()} scene failed; keeping the last picture"
                self.delivery = {'state': 'failed', 'scene': scene, 'signature': signature}
                self.last_synchronized = False
                self._log("warning", self.error)
                return {
                    "attempted": True, "wrote": False, "scene": scene,
                    "signature": signature, "synchronized": False,
                    "error": self.error,
                }

    def synchronize_weather(self, condition: str, variant: int, loop_seconds: float):
        with self.lock:
            if not self.enabled:
                return {"attempted": False, "started_at": None, "synchronized": False}
            relative = ASSETS.get((condition, variant))
            if not relative:
                self.phase = "unsupported"
                self.detail = "This preview supports rain animations only"
                self.last_synchronized = False
                return {"attempted": False, "started_at": None, "synchronized": False}
            path = self.asset_root / relative
            data = None
            upload_started = None
            reason = f"weather:{str(condition or '')[:32]}:{int(variant)}"
            try:
                port = self.port_finder()
                if not port:
                    raise LinkError("faceplate not found (no JSAUX CH340 ttyUSB)")
                token = self.identity_reader(port)
                if token != self.device_token:
                    self.known_epochs.clear()
                    self.flash.invalidate()
                    self.device_token = token
                    self.displayed_peak_load = 1.0
                    self._displayed_power_identity = ""
                data = self._orient_gif(path.read_bytes())
                validate_gif(data)
                retained = self._retained_restore(data, token)
                if retained:
                    return retained
                peak_load = POWER_BUDGET
                effective_brightness = safe_brightness(self.brightness)
                self.effective_brightness = effective_brightness
                digest = hashlib.sha256(data).hexdigest()
                known = self.known_epochs.get(digest)
                self.phase = "uploading"
                self.detail = "Waiting for the faceplate GIF acknowledgement"
                self.error = ""
                started = self.monotonic()
                upload_started = started
                self.last_transfer = {}
                soft_resynchronized = False
                restart_started_at = None
                with self._upload_link(port, data, "weather", "weather") as link:
                    self._write_brightness(link, safe_brightness(self.brightness))
                    self._begin_scene_power(link)
                    try:
                        wrote = self._send_protected(link, data, scene="weather", reason="weather")
                    finally:
                        self.last_transfer = dict(
                            getattr(link, "last_transfer_timings", {}) or {},
                        )
                    self.displayed_peak_load = peak_load
                    self._displayed_power_identity = hashlib.sha256(data).hexdigest()
                    # Raise brightness only after the new GIF is committed.
                    self._write_brightness(link, effective_brightness)
                    self._finish_scene_power(link)
                    if not wrote and (not known or self.last_transfer.get("stored_display_restarted")):
                        # The exact GIF survived a plugin/device restart, but
                        # its running phase cannot be inferred. Restart only
                        # the display, not the USB device or its stored content,
                        # and use the power-on acknowledgement as phase zero.
                        try:
                            link.command(protocol.power(False), timeout=0.5, retries=2)
                            self.sleeper(0.08)
                            link.command(protocol.power(True), timeout=0.5, retries=2)
                            restart_started_at = getattr(
                                link, "last_command_first_sent_at", None,
                            )
                            soft_resynchronized = True
                        except LinkError as error:
                            self._log("warning", "soft resynchronization failed: " + str(error))
                acknowledged = self.monotonic()
                self.last_upload_ms = round((acknowledged - started) * 1000)
                self.last_start_ack_ms = 0
                self.displayed_peak_load = peak_load
                if wrote:
                    epoch_wall = self.wall_clock()
                    self.state["writes"] = int(self.state.get("writes", 0)) + 1
                    self.state["assets"][digest] = {
                        "last_written_at": epoch_wall,
                        "asset": relative,
                        "loop_seconds": float(loop_seconds),
                    }
                    self.writes_session += 1
                    if token is not None:
                        self.known_epochs[digest] = {
                            "epoch_wall": epoch_wall,
                            "loop_seconds": float(loop_seconds),
                        }
                    phase = 0.0
                    synchronized = True
                    self.detail = "New GIF acknowledged; light bar joined phase 0"
                elif soft_resynchronized:
                    try:
                        restart_started_at = float(restart_started_at)
                    except (TypeError, ValueError, OverflowError):
                        restart_started_at = acknowledged
                    if not 0 < restart_started_at <= acknowledged:
                        restart_started_at = acknowledged
                    phase = max(0.0, acknowledged - restart_started_at)
                    epoch_wall = self.wall_clock() - phase
                    if token is not None:
                        self.known_epochs[digest] = {
                            "epoch_wall": epoch_wall,
                            "loop_seconds": float(loop_seconds),
                        }
                    self.last_start_ack_ms = round(phase * 1000)
                    synchronized = True
                    self.detail = (
                        "Identical GIF kept by the panel; light bar joined the "
                        "power-on transmit epoch"
                    )
                elif known and float(known.get("loop_seconds", 0)) == float(loop_seconds):
                    phase = (self.wall_clock() - float(known["epoch_wall"])) % float(loop_seconds)
                    synchronized = True
                    self.detail = "Identical GIF skipped; light bar joined the known session phase"
                else:
                    phase = 0.0
                    synchronized = False
                    self.detail = "Identical GIF skipped, but its start epoch is unknown"
                self.phase = "synchronized" if synchronized else "phase-unknown"
                self.last_asset = relative
                self.last_synchronized = synchronized
                self._record_upload(
                    reason=reason, data=data, wrote=wrote,
                    scene="weather",
                    duration_ms=self.last_upload_ms, transfer=self.last_transfer,
                )
                return {
                    "attempted": True,
                    "wrote": wrote,
                    "started_at": acknowledged - phase,
                    "synchronized": synchronized,
                    "phase_seconds": phase,
                    "frame_step_seconds": FACEPLATE_FRAME_SECONDS,
                }
            except UploadDeferred as error:
                return self._deferred(error, "weather")
            except (OSError, ValueError, LinkError) as error:
                if data is not None and upload_started is not None:
                    self.last_upload_ms = round(
                        max(0.0, self.monotonic() - upload_started) * 1000,
                    )
                    self._record_upload(
                        reason=reason, data=data, wrote=None,
                        scene="weather",
                        duration_ms=self.last_upload_ms, transfer=self.last_transfer,
                        error=str(error),
                    )
                self.phase = "error"
                self.error = str(error)[:180]
                self.detail = "Faceplate failed; the light bar preview remains available"
                self.last_synchronized = False
                self._log("warning", self.error)
                return {"attempted": True, "started_at": None, "synchronized": False,
                        "error": self.error}
