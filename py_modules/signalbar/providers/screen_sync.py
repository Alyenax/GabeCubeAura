"""Live Gamescope capture and 17-pixel screen colour mapping.

Frames stay in memory. The capture service never creates screenshots, cache
files, or network requests.
"""

from __future__ import annotations

import colorsys
import codecs
import json
import os
import pwd
import re
import select
import signal
import shutil
import subprocess
import threading
import time
from collections import deque

from signalbar.models import LED_COUNT, ProviderOutput, normalize_frame
from signalbar.shutdown import ShutdownBudget
from signalbar.updates import _clean_system_command_environment
from signalbar.screen_sync_trace import ScreenSyncTrace, TRACE_GST_DEBUG


CAPTURE_WIDTH = 34
CAPTURE_HEIGHT = 18
BYTES_PER_PIXEL = 4
FRAME_BYTES = CAPTURE_WIDTH * CAPTURE_HEIGHT * BYTES_PER_PIXEL
CAPTURE_REVISION = "1.4.1-system-capture-v10"
CAPTURE_PROCESS_MARKER = "client-name=GabeCubeAura-Screen-Sync"
SESSION_RESTART_SETTLE_SECONDS = 2.0
# Connecting/prerolling is different from losing an established stream. Do not
# repeatedly disconnect a slow Gamescope producer before its first frame.
FIRST_FRAME_TIMEOUT_SECONDS = 8.0
FRAME_STALL_TIMEOUT_SECONDS = 1.5

VALID_STYLES = {"panorama", "ambient"}
VALID_REACTIVITY = {"calm", "balanced", "fast"}
VALID_COLOUR_INTENSITY = {"natural", "vivid"}


def _clamp(value, low=0.0, high=255.0):
    return max(low, min(high, value))


def _srgb_to_linear(channel):
    value = channel / 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(channel):
    value = 12.92 * channel if channel <= 0.0031308 else 1.055 * channel ** (1 / 2.4) - 0.055
    return int(round(_clamp(value, 0.0, 1.0) * 255.0))


def _luma(pixel):
    red, green, blue = pixel
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


class ScreenSyncProcessor:
    """Turn a tiny BGRx screen frame into a stable 17-pixel RGB frame."""

    _ALPHAS = {
        "calm": (0.24, 0.14),
        "balanced": (0.46, 0.28),
        "fast": (0.72, 0.52),
    }

    def __init__(self, width=CAPTURE_WIDTH, height=CAPTURE_HEIGHT):
        self.width = int(width)
        self.height = int(height)
        self._previous = None
        self._bar_candidate = (0, 0)
        self._bar_streak = 0
        self._stable_bars = (0, 0)
        self._black_streak = 0
        self._palette_samples = ()

    def reset(self):
        self._previous = None
        self._bar_candidate = (0, 0)
        self._bar_streak = 0
        self._stable_bars = (0, 0)
        self._black_streak = 0
        self._palette_samples = ()

    def _decode(self, raw):
        expected = self.width * self.height * BYTES_PER_PIXEL
        if not isinstance(raw, (bytes, bytearray, memoryview)) or len(raw) != expected:
            raise ValueError(f"screen frame must contain exactly {expected} BGRx bytes")
        pixels = []
        view = memoryview(raw)
        for offset in range(0, expected, 4):
            blue, green, red = view[offset], view[offset + 1], view[offset + 2]
            pixels.append((red, green, blue))
        return pixels

    def _detect_bars(self, pixels, threshold):
        def row_is_black(row):
            start = row * self.width
            values = pixels[start:start + self.width]
            dark = sum(_luma(pixel) <= threshold + 4 for pixel in values)
            return dark >= int(self.width * 0.90)

        limit = max(0, self.height // 3)
        top = 0
        while top < limit and row_is_black(top):
            top += 1
        bottom = 0
        while bottom < limit and row_is_black(self.height - 1 - bottom):
            bottom += 1
        candidate = (top, bottom)
        if candidate == self._bar_candidate:
            self._bar_streak += 1
        else:
            self._bar_candidate = candidate
            self._bar_streak = 1
        if self._bar_streak >= 3:
            self._stable_bars = candidate
        return self._stable_bars

    @staticmethod
    def _mean_colour(pixels):
        if not pixels:
            return (0, 0, 0)
        # Bright HUD elements should not pull an entire LED zone to white.
        ordered = sorted(pixels, key=_luma)
        keep = max(1, int(round(len(ordered) * 0.95)))
        sample = ordered[:keep]
        linear = [sum(_srgb_to_linear(pixel[channel]) for pixel in sample) / len(sample)
                  for channel in range(3)]
        return tuple(_linear_to_srgb(channel) for channel in linear)

    def _zones(self, pixels, top, bottom, style):
        rows = range(top, max(top + 1, self.height - bottom))
        if style == "ambient":
            colour = self._mean_colour([
                pixels[row * self.width + column]
                for row in rows for column in range(self.width)
            ])
            return [colour] * LED_COUNT

        out = []
        for index in range(LED_COUNT):
            left = index * self.width // LED_COUNT
            right = max(left + 1, (index + 1) * self.width // LED_COUNT)
            out.append(self._mean_colour([
                pixels[row * self.width + column]
                for row in rows for column in range(left, right)
            ]))
        return out

    @staticmethod
    def _adjust(colours, brightness, colour_intensity, black_threshold):
        scale = _clamp(float(brightness), 34.0, 255.0) / 255.0
        saturation_scale = 1.30 if colour_intensity == "vivid" else 1.0
        adjusted = []
        for red, green, blue in colours:
            if _luma((red, green, blue)) <= black_threshold:
                adjusted.append((0, 0, 0))
                continue
            hue, saturation, value = colorsys.rgb_to_hsv(red / 255.0, green / 255.0, blue / 255.0)
            red_f, green_f, blue_f = colorsys.hsv_to_rgb(
                hue, _clamp(saturation * saturation_scale, 0.0, 1.0), value * scale
            )
            adjusted.append((
                int(round(_clamp(red_f, 0.0, 1.0) * 255)),
                int(round(_clamp(green_f, 0.0, 1.0) * 255)),
                int(round(_clamp(blue_f, 0.0, 1.0) * 255)),
            ))
        return adjusted

    @staticmethod
    def _spatial_blur(colours):
        if len(colours) < 2 or len(set(colours)) == 1:
            return list(colours)
        out = []
        for index, centre in enumerate(colours):
            left = colours[max(0, index - 1)]
            right = colours[min(len(colours) - 1, index + 1)]
            out.append(tuple(int(round(left[channel] * 0.2 + centre[channel] * 0.6
                                       + right[channel] * 0.2)) for channel in range(3)))
        return out

    def process(self, raw, *, style="panorama", brightness=160, reactivity="balanced",
                colour_intensity="natural", black_threshold=8, ignore_black_bars=True):
        if style not in VALID_STYLES:
            style = "panorama"
        if reactivity not in VALID_REACTIVITY:
            reactivity = "balanced"
        if colour_intensity not in VALID_COLOUR_INTENSITY:
            colour_intensity = "natural"
        black_threshold = int(_clamp(float(black_threshold), 0.0, 32.0))
        pixels = self._decode(raw)
        top, bottom = self._detect_bars(pixels, black_threshold) if ignore_black_bars else (0, 0)
        rows = range(top, max(top + 1, self.height - bottom))
        self._palette_samples = tuple(
            pixels[row * self.width + column]
            for row in rows for column in range(self.width)
        )
        colours = self._zones(pixels, top, bottom, style)
        colours = self._adjust(colours, brightness, colour_intensity, black_threshold)
        colours = self._spatial_blur(colours)

        all_black = all(_luma(colour) <= black_threshold for colour in colours)
        self._black_streak = self._black_streak + 1 if all_black else 0
        if self._black_streak >= 3:
            result = [(0, 0, 0)] * LED_COUNT
        elif self._previous is None:
            result = colours
        else:
            brighten_alpha, darken_alpha = self._ALPHAS[reactivity]
            result = []
            for previous, current in zip(self._previous, colours):
                alpha = brighten_alpha if _luma(current) >= _luma(previous) else darken_alpha
                result.append(tuple(int(round(previous[channel] +
                                              (current[channel] - previous[channel]) * alpha))
                                    for channel in range(3)))
        self._previous = normalize_frame(result)
        return self._previous

    @property
    def crop(self):
        return self._stable_bars

    @property
    def palette_samples(self):
        """Raw RGB Gamescope pixels after stable cinematic bar cropping."""
        return self._palette_samples


class ScreenCaptureService:
    """Supervise a low-resolution GStreamer consumer of Gamescope PipeWire."""

    def __init__(self, clock=time.monotonic, popen=subprocess.Popen, run=subprocess.run, trace=None):
        self._clock = clock
        self._popen = popen
        self._run_command = run
        self._lock = threading.RLock()
        self._process_stop_lock = threading.Lock()
        self._stderr_read_lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._process = None
        self._active = False
        self._frame = None
        self._frame_at = 0.0
        self._sequence = 0
        self._phase = "off"
        self._error = ""
        self._node_id = None
        self._node_name = ""
        self._runtime_dir_used = ""
        self._capture_identity = ""
        self._discovery_detail = ""
        self._selector_mode = "target-object"
        self._capture_selector = ""
        self._conflicting_consumers = 0
        self._stderr = deque(maxlen=12)
        self._frames_seen = 0
        self._started_at = 0.0
        self._orphan_processes_cleaned = 0
        self._capture_sessions_released = 0
        self._last_release_error = ""
        self._bytes_seen = 0
        self._first_frame_at = None
        self._attempt_started_at = None
        self._producer_state = "unknown"
        self._attempt_history = deque(maxlen=3)
        self.trace = trace if trace is not None else ScreenSyncTrace(clock=clock)
        self._attempt_number = 0
        self._stderr_decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._stderr_pending = ""
        self._last_gst_failure = ""
        self._trace_stages = set()
        self._trace_graph = None
        self._runtime_inspected = False
        self._retry_paused = False
        self._unhealthy_sessions = 0
        self._paused_graph_check_at = 0.0

    @staticmethod
    def _runtime_dirs():
        candidates = []
        configured = os.environ.get("XDG_RUNTIME_DIR")
        if configured:
            candidates.append(configured)
        sudo_uid = os.environ.get("SUDO_UID")
        if sudo_uid and sudo_uid.isdigit():
            candidates.append(f"/run/user/{sudo_uid}")
        candidates.append("/run/user/1000")
        try:
            candidates.extend(
                f"/run/user/{entry}" for entry in os.listdir("/run/user") if entry.isdigit()
            )
        except OSError:
            pass
        return [
            candidate for candidate in dict.fromkeys(candidates)
            if os.path.exists(os.path.join(candidate, "pipewire-0"))
        ]

    @classmethod
    def _runtime_dir(cls):
        """Return the first candidate for compatibility with older callers."""
        candidates = cls._runtime_dirs()
        return candidates[0] if candidates else ""

    @staticmethod
    def _node_label(item):
        props = (item.get("info") or {}).get("props") or {}
        return " ".join(filter(None, (str(props.get(key, "")).strip() for key in (
            "node.name", "node.nick", "node.description", "media.name", "media.title",
            "application.name",
        )))).strip()

    @classmethod
    def find_gamescope_node(cls, dump):
        best = None
        for item in dump if isinstance(dump, list) else []:
            if item.get("type") != "PipeWire:Interface:Node":
                continue
            props = (item.get("info") or {}).get("props") or {}
            label = cls._node_label(item)
            lowered = label.lower()
            media_class = str(props.get("media.class", "")).lower()
            node_name = str(props.get("node.name", "")).strip().lower()
            description = str(props.get("node.description", "")).strip().lower()
            exact_gamescope = node_name == "gamescope" or description == "gamescope"
            if any(term in lowered for term in ("camera", "v4l2", "loopback")):
                continue
            if not exact_gamescope and "video" not in media_class and "video" not in lowered:
                continue
            score = 0
            if exact_gamescope:
                score += 200
            elif "gamescope" in lowered:
                score += 100
            if "steam" in lowered and "game" in lowered:
                score += 20
            if "source" in media_class:
                score += 10
            if score and (best is None or score > best[0]):
                best = (score, int(item["id"]), label or "Gamescope video")
        return None if best is None else (best[1], best[2])

    @staticmethod
    def count_consumers(dump, node_id):
        count = 0
        for item in dump if isinstance(dump, list) else []:
            if item.get("type") != "PipeWire:Interface:Link":
                continue
            info = item.get("info") or {}
            props = info.get("props") or {}
            output_node = props.get("link.output.node", info.get("output-node-id"))
            state = str(info.get("state", "active")).lower()
            try:
                matches = int(output_node) == int(node_id)
            except (TypeError, ValueError):
                matches = False
            if matches and state not in {"error", "unlinked"}:
                count += 1
        return count

    @staticmethod
    def capture_clients(dump, node_id):
        """Describe only linked/targeted video consumers, never all processes.

        A registered node targeting Gamescope can be stuck before a Link exists.
        Report it as a candidate, not as proof of a conflicting active capture.
        Audio nodes sharing the PipeWire server are deliberately excluded.
        """
        rows = [item for item in dump if isinstance(item, dict)]
        by_id = {str(item.get("id")): item for item in rows}
        producer = by_id.get(str(node_id), {})
        serial = str(((producer.get("info") or {}).get("props") or {}).get("object.serial", ""))
        targets = {"gamescope"}
        if node_id is not None:
            targets.add(str(node_id))
        if serial:
            targets.add(serial)
        links = {}
        for item in rows:
            if item.get("type") != "PipeWire:Interface:Link":
                continue
            info = item.get("info") or {}
            props = info.get("props") or {}
            if node_id is not None and str(props.get("link.output.node", info.get("output-node-id"))) == str(node_id):
                target = str(props.get("link.input.node", info.get("input-node-id")))
                links.setdefault(target, set()).add(str(info.get("state", "unknown")))
        result = []
        for item in rows:
            if item.get("type") != "PipeWire:Interface:Node" or item.get("id") == node_id:
                continue
            info = item.get("info") or {}; props = info.get("props") or {}
            media = str(props.get("media.class", ""))
            target = str(props.get("target.object", props.get("node.target", "")))
            linked = str(item.get("id")) in links
            targeted = target in targets and "audio" not in media.lower()
            if not linked and not targeted:
                continue
            client = by_id.get(str(props.get("client.id")), {})
            client_props = (client.get("info") or {}).get("props") or {}
            name = str(props.get("application.name") or client_props.get("application.name") or "")
            client_name = str(client_props.get("client.name", ""))
            binary = os.path.basename(str(client_props.get("application.process.binary") or props.get("application.process.binary") or ""))
            states = sorted(links.get(str(item.get("id")), set()))
            result.append({"node_id": item.get("id"), "linked": linked,
                "targeted": targeted, "link_states": states[:4],
                "application": name[:80], "client": client_name[:80], "binary": binary[:80],
                "gca_marker": client_name == "GabeCubeAura-Screen-Sync" or name == "GabeCubeAura-Screen-Sync"})
        return result[:8]

    def _trace_pipewire(self, dump, node_id):
        producer = next((item for item in dump if item.get("id") == node_id), None) if node_id is not None else None
        state = str((producer.get("info") or {}).get("state", "unknown")) if producer else "unknown"
        if state not in {"suspended", "idle", "running", "error", "creating"}:
            state = "unknown"
        snapshot = {"producer_present": producer is not None, "producer_state": state,
                    "consumers": self.capture_clients(dump, node_id),
                    "links": self.count_consumers(dump, node_id) if node_id is not None else 0}
        self._producer_state = state
        if snapshot != self._trace_graph:
            self.trace.record("pipewire-graph", attempt=self._attempt_number, **snapshot)
            self._trace_graph = snapshot

    def _inspect_runtime(self, gst, environment):
        if self._runtime_inspected or self.trace.directory is None:
            return
        self._runtime_inspected = True
        details = {}
        for name, command in (("gstreamer", [gst, "--version"]),
                ("pipewiresrc", [shutil.which("gst-inspect-1.0") or "gst-inspect-1.0", "pipewiresrc"])):
            try:
                result = self._run_command(command, capture_output=True, text=True,
                    timeout=1.0, check=False, env=environment)
                text = result.stdout or ""
                match = re.search(r"(?:[Vv]ersion|GStreamer)\s+([0-9][0-9A-Za-z.\-]*)", text)
                details[name] = match.group(1)[:48] if match else "unavailable"
                if name == "pipewiresrc":
                    details["keepalive_supported"] = "keepalive-time" in text
                    details["always_copy_supported"] = "always-copy" in text
            except Exception as error:
                details[name] = type(error).__name__
        self.trace.record("capture-runtime", **details)

    @staticmethod
    def _runtime_owner(runtime_dir):
        """Return the user owning a /run/user/<uid> PipeWire session."""
        try:
            uid = int(os.path.basename(os.path.normpath(str(runtime_dir))))
            account = pwd.getpwuid(uid)
        except (KeyError, TypeError, ValueError):
            return None
        return uid, account.pw_name

    @classmethod
    def _command_for_runtime(cls, command, runtime_dir):
        """Run PipeWire clients as the session owner when Decky runs as root.

        PipeWire registry permissions are attached to the connecting Unix
        identity.  A root Decky backend can reach the UID 1000 socket yet see a
        different or restricted registry, so discovery and capture must use the
        owner of that runtime directory.
        """
        owner = cls._runtime_owner(runtime_dir)
        effective_uid = os.geteuid() if hasattr(os, "geteuid") else -1
        if owner is None:
            return list(command), f"uid {effective_uid}"
        uid, username = owner
        if effective_uid != 0 or uid == effective_uid:
            return list(command), f"{username} (uid {uid})"
        runuser = shutil.which("runuser")
        if not runuser:
            return list(command), f"root fallback; {username} runuser unavailable"
        return [runuser, "-u", username, "--", *command], f"{username} (uid {uid})"

    def _pipewire_dump(self, runtime_dir):
        executable = shutil.which("pw-dump")
        if not executable:
            raise RuntimeError("pw-dump is not installed")
        environment = _clean_system_command_environment()
        if runtime_dir:
            environment["XDG_RUNTIME_DIR"] = runtime_dir
        command, identity = self._command_for_runtime([executable], runtime_dir)
        with self._lock:
            self._capture_identity = identity
        result = self._run_command(
            command, capture_output=True, text=True, timeout=2.0,
            check=False, env=environment,
        )
        if result.returncode:
            raise RuntimeError((result.stderr or "pw-dump failed").strip()[-240:])
        return json.loads(result.stdout)

    def _discover_gamescope_node(self):
        """Search every local PipeWire session and retain a direct-name fallback.

        Current Gamescope consumers can connect with ``target-object=gamescope``
        even when registry enumeration omits the producer node.  Discovery is
        therefore useful for diagnostics, legacy numeric capture and conflict
        checks, but it is no longer a prerequisite for starting Screen Sync.
        """
        runtime_dirs = self._runtime_dirs()
        if not runtime_dirs:
            raise RuntimeError("PipeWire session was not found")

        failures = []
        visible_video_nodes = []
        direct_candidate = None
        for runtime_dir in runtime_dirs:
            try:
                dump = self._pipewire_dump(runtime_dir)
            except Exception as error:
                failures.append(f"{runtime_dir}: {str(error)[:100]}")
                continue
            candidate_uid = self._runtime_owner(runtime_dir)
            current_uid = (
                self._runtime_owner(direct_candidate[0])
                if direct_candidate is not None else None
            )
            if (direct_candidate is None
                    or current_uid is not None and current_uid[0] == 0
                    and candidate_uid is not None and candidate_uid[0] != 0):
                direct_candidate = (runtime_dir, dump)
            node = self.find_gamescope_node(dump)
            if node is not None:
                with self._lock:
                    self._runtime_dir_used = runtime_dir
                    self._discovery_detail = f"Gamescope found in {runtime_dir}"
                return runtime_dir, node, dump
            for item in dump if isinstance(dump, list) else []:
                if item.get("type") != "PipeWire:Interface:Node":
                    continue
                props = (item.get("info") or {}).get("props") or {}
                if "video" in str(props.get("media.class", "")).lower():
                    label = self._node_label(item)
                    if label:
                        visible_video_nodes.append(label[:80])

        searched = ", ".join(runtime_dirs)
        if direct_candidate is not None:
            runtime_dir, dump = direct_candidate
            detail = (
                f"No enumerated Gamescope node in {searched}; "
                "trying target-object=gamescope directly"
            )
            if visible_video_nodes:
                detail += "; video nodes: " + ", ".join(
                    dict.fromkeys(visible_video_nodes)
                )[:160]
            with self._lock:
                self._runtime_dir_used = runtime_dir
                self._discovery_detail = detail
                self._node_id = None
                self._node_name = "gamescope (direct name)"
            return runtime_dir, None, dump

        detail = f"No Gamescope node in {searched}"
        if visible_video_nodes:
            detail += "; video nodes: " + ", ".join(dict.fromkeys(visible_video_nodes))[:160]
        elif failures:
            detail += "; " + "; ".join(failures)[:160]
        with self._lock:
            self._runtime_dir_used = ""
            self._discovery_detail = detail
            self._node_id = None
            self._node_name = ""
        raise RuntimeError(detail)

    @staticmethod
    def _capture_command(gst, node_id, selector_mode="target-object"):
        selector = (
            "target-object=gamescope"
            if selector_mode in {"target-object", "target-object-compat"}
            else f"path={int(node_id)}"
        )
        source = [
            gst, "-q", "pipewiresrc", selector, "do-timestamp=true",
            CAPTURE_PROCESS_MARKER,
        ]
        if selector_mode == "target-object":
            # Current PipeWire keeps a variable-rate Gamescope source alive
            # between compositor updates. Older plugins may not expose this
            # property, in which case supervision retries with the node ID.
            source.append("keepalive-time=33")
        return source + [
            "!", "queue", "max-size-buffers=1", "leaky=downstream",
            "!", "videoconvert", "!", "videoscale", "method=1",
            "!", "videorate", "drop-only=true",
            "!", "video/x-raw,format=BGRx,width=34,height=18,framerate=10/1",
            "!", "fdsink", "fd=1", "sync=false",
        ]

    @staticmethod
    def _marked_capture_pids(proc_root="/proc"):
        """Find only stale GStreamer clients carrying GabeCubeAura's marker.

        This deliberately avoids process names and broad pkill matching. The
        marker is part of the exact pipeline command created above, so other
        Gamescope recorders and GStreamer applications are never selected.
        """
        found = []
        try:
            entries = os.listdir(proc_root)
        except OSError:
            return found
        for entry in entries:
            if not entry.isdigit() or int(entry) == os.getpid():
                continue
            try:
                with open(os.path.join(proc_root, entry, "cmdline"), "rb") as handle:
                    raw = handle.read(65536)
            except OSError:
                continue
            arguments = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
            if not arguments:
                continue
            has_gstreamer = any(os.path.basename(argument) == "gst-launch-1.0" for argument in arguments)
            if has_gstreamer and CAPTURE_PROCESS_MARKER in arguments:
                found.append(int(entry))
        return found

    def _cleanup_orphan_captures(self):
        """Release GabeCubeAura pipelines left by a replaced backend.

        Decky can replace the plugin while switching between Desktop and
        Gaming Mode without giving the old backend enough time to reap its
        child. Such a client keeps the old PipeWire graph busy until reboot.
        """
        current = None
        with self._lock:
            if self._process is not None:
                current = getattr(self._process, "pid", None)
        cleaned = 0
        targets = set(self._marked_capture_pids())
        self.trace.record("stale-gca-captures", marked_processes=len(targets))
        for pid in targets:
            if pid == current:
                continue
            try:
                os.kill(pid, signal.SIGINT)
                cleaned += 1
            except (ProcessLookupError, PermissionError):
                continue
        if cleaned:
            with self._lock:
                self._orphan_processes_cleaned += cleaned
                self._discovery_detail = (
                    f"Released {cleaned} stale GabeCubeAura capture process"
                    f"{'es' if cleaned != 1 else ''} after plugin replacement"
                )
            self._wait(0.50)
            # A pipeline stuck in PAUSED can ignore a graceful request. Check
            # the exact marker again before escalating, so PID reuse or an
            # unrelated GStreamer process can never be killed accidentally.
            remaining = set(self._marked_capture_pids())
            for pid in targets & remaining:
                if pid == current:
                    continue
                try:
                    os.kill(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    continue
            if targets & remaining:
                self._wait(0.25)
                for pid in (targets & set(self._marked_capture_pids())) - {current}:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        continue
        return cleaned

    @staticmethod
    def _graceful_capture_pids(process, proc_root="/proc"):
        """SIGINT only our gst-launch child; never interrupt its runuser wrapper.

        runuser translates an interrupt into SIGTERM for its child. Walk only
        this subprocess's descendants and require the exact GCA marker before
        targeting a wrapped GStreamer child. No global process scan or arguments
        are exported to diagnostics.
        """
        pid = getattr(process, "pid", None)
        args = getattr(process, "args", ())
        if pid is None or not isinstance(args, (tuple, list)) or not args:
            return []
        if os.path.basename(str(args[0])) == "gst-launch-1.0":
            return [pid]
        if os.path.basename(str(args[0])) != "runuser":
            return []
        found, pending, seen = [], [pid], set()
        while pending and len(seen) < 16:
            parent = pending.pop()
            if parent in seen:
                continue
            seen.add(parent)
            try:
                with open(os.path.join(proc_root, str(parent), "task", str(parent), "children")) as handle:
                    children = handle.read(256).split()[:8]
            except OSError:
                continue
            for child in children:
                if not child.isdigit():
                    continue
                try:
                    with open(os.path.join(proc_root, child, "cmdline"), "rb") as handle:
                        arguments = [part.decode("utf-8", "replace") for part in handle.read(8192).split(b"\0") if part]
                except OSError:
                    continue
                if (arguments and os.path.basename(arguments[0]) == "gst-launch-1.0"
                        and CAPTURE_PROCESS_MARKER in arguments):
                    found.append(int(child))
                else:
                    pending.append(int(child))
        return found

    @staticmethod
    def _terminate_process(process, timeout=2.0, drain=None):
        """Graceful GStreamer NULL transition, then bounded group escalation."""
        if process is None or process.poll() is not None:
            return "already-exited"
        budget = ShutdownBudget(timeout)
        pid = getattr(process, "pid", None)
        def wait_after_signal(seconds):
            if drain is None:
                return process.wait(timeout=budget.remaining(seconds))
            deadline = time.monotonic() + budget.remaining(seconds)
            while True:
                drain(process)
                exit_code = process.poll()
                if exit_code is not None:
                    return exit_code
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired("capture-stop", seconds)
                try:
                    return process.wait(timeout=min(0.05, remaining))
                except subprocess.TimeoutExpired:
                    continue
        interrupted = False
        for target in ScreenCaptureService._graceful_capture_pids(process):
            try:
                os.kill(target, signal.SIGINT)
                interrupted = True
            except OSError:
                continue
        if interrupted:
            try:
                wait_after_signal(0.6)
                return "sigint"
            except subprocess.TimeoutExpired:
                pass
        try:
            if pid is None:
                raise OSError("process has no pid")
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            process.terminate()
        try:
            wait_after_signal(0.6 if interrupted else 1.0)
            return "sigterm"
        except subprocess.TimeoutExpired:
            pass
        try:
            if pid is None:
                raise OSError("process has no pid")
            os.killpg(pid, signal.SIGKILL)
        except OSError:
            process.kill()
        try:
            wait_after_signal(1.0)
            return "sigkill"
        except subprocess.TimeoutExpired:
            return "pending"  # Supervisor retains responsibility for reaping.

    def _drain_stopping_capture(self, process):
        # A full pipe must not prevent GStreamer from completing NULL teardown.
        # Discard image bytes only during stop, while retaining metadata logs.
        try:
            if process.stdout is not None:
                os.set_blocking(process.stdout.fileno(), False)
                os.read(process.stdout.fileno(), FRAME_BYTES * 8)
        except (OSError, ValueError):
            pass
        self._read_stderr(process)

    def _stop_capture_process(self, process, timeout=2.0):
        # Engine.stop and the supervisor's finally can arrive together. A
        # second SIGINT after gst-launch removes its handler would be abrupt.
        if process is None:
            return "already-exited"
        budget = ShutdownBudget(timeout)
        if not self._process_stop_lock.acquire(timeout=budget.remaining(2.0)):
            return "pending"
        try:
            return self._terminate_process(process, timeout=budget.remaining(2.0),
                                           drain=self._drain_stopping_capture)
        finally:
            self._process_stop_lock.release()

    def _release_failed_capture(self, process, error):
        """Close a failed client before waiting or selecting another source.

        GStreamer can remain alive while its pipeline is stuck in PAUSED. It
        must be reaped before the retry delay, otherwise its PipeWire link can
        keep the Gamescope node busy while the next selector is prepared.
        """
        if process is None:
            return False
        # Record before killing the child: -SIGTERM would otherwise masquerade
        # as its original exit status. Retain evidence across selector retries.
        self._read_stderr(process)
        exit_code = process.poll()
        with self._lock:
            failure = {
                **self._attempt_status(),
                "exit_code": exit_code,
                "failure": self._failure_kind(error, exit_code),
                "stderr_tail": list(self._stderr)[-4:],
            }
            self._attempt_history.append(failure)
        self.trace.record("capture-failed", attempt=self._attempt_number, **failure)
        self._finish_process(process, "capture-failed")
        with self._lock:
            if self._process is process:
                self._process = None
            self._frame = None
            self._frame_at = 0.0
            self._frames_seen = 0
            self._started_at = 0.0
            self._capture_sessions_released += 1
            self._last_release_error = str(error)[:300]
        return True

    def _attempt_status(self):
        # Caller holds the capture lock. No pixels or process arguments leave
        # the capture service; reports contain only counters and bounded errors.
        started = self._attempt_started_at
        return {
            "selector": self._capture_selector,
            "producer_state": self._producer_state,
            "elapsed_s": round(max(0.0, self._clock() - started), 3) if started is not None else 0.0,
            "bytes_received": self._bytes_seen,
            "frames_received": self._frames_seen,
            "first_frame_after_s": round(self._first_frame_at - started, 3)
                if self._first_frame_at is not None and started is not None else None,
        }

    def _failure_kind(self, error, exit_code):
        text = (str(error) + " " + " ".join(self._stderr)).lower()
        if "first gamescope frame timed out" in text:
            return "first-frame-timeout"
        if "stopped producing frames" in text:
            return "frame-stall"
        if "not-negotiated" in text or "could not link" in text:
            return "negotiation"
        if "no element" in text or "no property" in text:
            return "unsupported-pipeline"
        if "permission denied" in text or "not permitted" in text:
            return "permission"
        return "child-exit" if exit_code is not None else "capture-error"

    def set_active(self, active):
        active = bool(active)
        with self._lock:
            changed = active != self._active
            self._active = active
            if not active:
                self._phase = "off"
                self._error = ""
                self._conflicting_consumers = 0
            elif changed:
                self._selector_mode = "target-object"
                self._capture_selector = ""
                self._retry_paused = False
                self._unhealthy_sessions = 0
            # A game transition can request a stop while discovery or process
            # cleanup is still unwinding.  The provider calls this method on
            # every render tick, so recreate a dead supervisor even if the
            # logical active flag was already true on the previous tick.
            if active and (self._thread is None or not self._thread.is_alive()):
                self._stop.clear()
                self._thread = threading.Thread(
                    target=self._supervise,
                    name="gabecubeaura-screen-capture",
                    daemon=True,
                )
                self._thread.start()
        if changed:
            self.trace.record("capture-request", active=active)
            self._wake.set()

    def request_retry(self):
        """Explicit Preview can retry a paused source without killing a live one."""
        with self._lock:
            paused = self._retry_paused
            self._retry_paused = False
            self._unhealthy_sessions = 0
            if paused:
                self._selector_mode = "target-object"
        self.trace.record("capture-retry-request", was_paused=paused)
        self._wake.set()

    def stop(self, timeout=None):
        self.trace.record("capture-stop-request", reason="service-stop")
        budget = ShutdownBudget(timeout)
        self._stop.set()
        self._wake.set()
        with self._lock:
            process = self._process
        strategy = self._stop_capture_process(process, timeout=budget.remaining(2.0))
        self.trace.record("capture-stop-signal", strategy=strategy)
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=budget.remaining(3.5))
        with self._lock:
            self._active = False
            self._phase = "off"
            if self._thread is not None and not self._thread.is_alive():
                self._thread = None
            self._process = None

    def latest(self):
        with self._lock:
            return self._frame, self._sequence, self._frame_at

    def status(self):
        with self._lock:
            age = max(0.0, self._clock() - self._frame_at) if self._frame_at else None
            elapsed = max(0.001, self._clock() - self._started_at) if self._started_at else 0.0
            return {
                "revision": CAPTURE_REVISION,
                "phase": self._phase,
                "error": self._error,
                "node_id": self._node_id,
                "node_name": self._node_name,
                "runtime_dir": self._runtime_dir_used,
                "capture_identity": self._capture_identity,
                "discovery_detail": self._discovery_detail,
                "capture_selector": self._capture_selector,
                "stderr_tail": list(self._stderr),
                "conflicting_consumers": self._conflicting_consumers,
                "frame_age_s": age,
                "frames_per_second": self._frames_seen / elapsed if elapsed else 0.0,
                "orphan_processes_cleaned": self._orphan_processes_cleaned,
                "capture_sessions_released": self._capture_sessions_released,
                "last_release_error": self._last_release_error,
                "attempt": self._attempt_status(),
                "recent_failures": [dict(item, stderr_tail=list(item["stderr_tail"]))
                                    for item in self._attempt_history],
                "retry_paused": self._retry_paused,
                "unhealthy_sessions": self._unhealthy_sessions,
            }

    def _set_state(self, phase, error="", consumers=0):
        with self._lock:
            changed = (phase, str(error)[:300]) != (self._phase, self._error)
            self._phase = phase
            self._error = str(error)[:300]
            self._conflicting_consumers = max(0, int(consumers))
        if changed:
            self.trace.record("capture-phase", phase=phase, error=str(error), consumers=consumers)

    def _wait(self, seconds):
        self._wake.wait(seconds)
        self._wake.clear()

    def _read_stderr(self, process):
        with self._stderr_read_lock:
            self._drain_stderr(process)

    def _drain_stderr(self, process):
        # The child can exit before select() runs. Preserve its actual failure
        # instead of reporting only that a selector failed.
        # Preserve lines split across pipe reads; drain bounded bursts promptly
        # so increased metadata logging cannot fill the child's stderr pipe.
        try:
            os.set_blocking(process.stderr.fileno(), False)
        except (OSError, ValueError):
            return
        for _ in range(8):
            try:
                chunk = os.read(process.stderr.fileno(), 8192)
            except (OSError, ValueError):
                break
            if not chunk:
                break
            self._stderr_pending += self._stderr_decoder.decode(chunk)
            lines = self._stderr_pending.split("\n")
            self._stderr_pending = lines.pop()
            for line in lines:
                self._trace_stderr_line(line)
            if len(self._stderr_pending) > 4096:
                self._trace_stderr_line(self._stderr_pending[:4096])
                self._stderr_pending = ""
        if process.poll() is not None and self._stderr_pending:
            self._trace_stderr_line(self._stderr_pending)
            self._stderr_pending = ""

    def _trace_stderr_line(self, line):
        line = line.strip()
        if not line:
            return
        with self._lock:
            self._stderr.append(line[-720:])
            if not self._last_gst_failure and (re.search(r"\berror\b", line, re.IGNORECASE)
                    or any(term in line.lower() for term in ("not-negotiated", "no element", "no property", "could not link"))):
                self._last_gst_failure = line[-720:]
        self.trace.record("gstreamer", important=False, attempt=self._attempt_number, message=line)
        lower = line.lower()
        stage = next((stage for needle, stage in (
            ("connect capture", "connect-request"),
            ("got stream state", "pipewire-state-" + lower.rsplit(" ", 1)[-1][:24]),
            ("waiting for streaming", "waiting-streaming"),
            ("waiting for negotiated", "waiting-negotiation"),
            ("we got format", "negotiated-format"),
            ("set format", "negotiated-format"),
            ("have common caps", "common-caps"),
            ("completed state change to null", "pipeline-null" if "pipeline" in lower else "element-null"),
            ("error", "gstreamer-error"),
        ) if needle in lower), None)
        if stage and stage not in self._trace_stages:
            self._trace_stages.add(stage)
            self.trace.record("gstreamer-stage", attempt=self._attempt_number, stage=stage, message=line)

    def _finish_process(self, process, reason):
        if process is None:
            return
        self.trace.record("capture-stop-request", attempt=self._attempt_number, reason=reason,
                          exit_code_before_stop=process.poll())
        strategy = self._stop_capture_process(process)
        self._read_stderr(process)
        exit_code = process.poll()
        self.trace.record("capture-stopped" if exit_code is not None else "capture-stop-pending",
                          attempt=self._attempt_number, exit_code_after_stop=exit_code,
                          stop_strategy=strategy, null_transition_seen="pipeline-null" in self._trace_stages)
        if exit_code is not None:
            for stream in (process.stdout, process.stderr):
                stream.close()

    def _supervise(self):
        backoff = 0.5
        cleanup_armed = True
        while not self._stop.is_set():
            with self._lock:
                active = self._active
            if not active:
                cleanup_armed = True
                self._wait(0.25)
                continue
            if self._retry_paused:
                # Observe the registry only. Do not reconnect a video consumer
                # indefinitely when Gamescope may already be wedged.
                now = self._clock()
                interval = 0.5 if self.trace.previewing else 2.0
                if self._runtime_dir_used and now - self._paused_graph_check_at >= interval:
                    self._paused_graph_check_at = now
                    try:
                        self._trace_pipewire(self._pipewire_dump(self._runtime_dir_used), self._node_id)
                    except Exception as error:
                        self.trace.record("paused-registry-check-failed", error_type=type(error).__name__)
                self._wait(0.5)
                continue
            process = None
            captured_frame = False
            selector_mode = self._selector_mode
            # Discovery can fail while Gaming Mode is being suspended or while
            # Steam switches between the desktop and Gamescope sessions. Keep
            # the retry path valid even when no node was returned this cycle.
            node_id = None
            try:
                gst = shutil.which("gst-launch-1.0")
                if not gst:
                    raise RuntimeError("GStreamer is not installed")
                if cleanup_armed:
                    self._cleanup_orphan_captures()
                    cleanup_armed = False
                self.trace.record("discovery-start", selector=selector_mode)
                runtime_dir, node, dump = self._discover_gamescope_node()
                if node is None:
                    node_id, node_name = None, "gamescope (direct name)"
                else:
                    node_id, node_name = node
                if selector_mode == "path" and node_id is None:
                    # The numeric node belonged to an older PipeWire graph.
                    # Restart the complete selector sequence for the current
                    # session instead of retaining a stale fallback mode.
                    selector_mode = "target-object"
                    with self._lock:
                        self._selector_mode = selector_mode
                consumers = self.count_consumers(dump, node_id) if node_id is not None else 0
                with self._lock:
                    self._node_id, self._node_name = node_id, node_name
                    state = next((str((item.get("info") or {}).get("state", "unknown"))
                                  for item in dump if item.get("id") == node_id), "unknown")
                    self._producer_state = state if state in {
                        "suspended", "idle", "running", "error", "creating"
                    } else "unknown"
                self._trace_pipewire(dump, node_id)
                self.trace.record("discovery-result", node_id=node_id,
                                  direct_name=node_id is None, identity=self._capture_identity)
                if consumers:
                    self._set_state("conflict", "Another app is already capturing Gamescope", consumers)
                    self._wait(1.0)
                    continue
                environment = _clean_system_command_environment()
                environment["XDG_RUNTIME_DIR"] = runtime_dir
                # Warnings plus source format negotiation, never per-frame
                # traces. stderr is bounded and exported through sanitization.
                detail_started = self.trace.detailed()
                environment["GST_DEBUG"] = TRACE_GST_DEBUG if detail_started else "1"
                environment["GST_DEBUG_NO_COLOR"] = "1"
                environment.pop("GST_DEBUG_FILE", None)
                environment.pop("GST_DEBUG_DUMP_DOT_DIR", None)
                self._inspect_runtime(gst, environment)
                command = self._capture_command(gst, node_id, selector_mode)
                command, identity = self._command_for_runtime(command, runtime_dir)
                with self._lock:
                    self._stderr.clear()
                    self._capture_identity = identity
                    self._capture_selector = (
                        "gamescope name"
                        if selector_mode == "target-object"
                        else "gamescope name (compatibility)"
                        if selector_mode == "target-object-compat"
                        else f"legacy node {node_id}"
                    )
                    self._attempt_started_at = self._clock()
                    self._bytes_seen = 0
                    self._frames_seen = 0
                    self._first_frame_at = None
                    self._attempt_number += 1
                    self._trace_stages.clear()
                    self._stderr_pending = ""
                    self._last_gst_failure = ""
                    self._stderr_decoder.reset()
                    self._trace_graph = None
                self.trace.record("capture-launch", attempt=self._attempt_number,
                    selector=self._capture_selector, identity=identity,
                    gst_debug=TRACE_GST_DEBUG, frame_bytes=FRAME_BYTES)
                process = self._popen(
                    command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL, env=environment, bufsize=0,
                    start_new_session=True,
                )
                with self._lock:
                    self._process = process
                self.trace.record("capture-child-started", attempt=self._attempt_number)
                os.set_blocking(process.stdout.fileno(), False)
                os.set_blocking(process.stderr.fileno(), False)
                buffer = bytearray()
                last_frame = self._clock()
                last_conflict_check = last_frame
                last_progress = last_frame
                with self._lock:
                    self._started_at = last_frame
                    self._frames_seen = 0
                self._set_state("waiting", "Waiting for the first Gamescope frame")
                backoff = 0.5
                while not self._stop.is_set():
                    with self._lock:
                        active = self._active
                    if detail_started != self.trace.detailed():
                        break
                    if not active or process.poll() is not None:
                        break
                    readable, _, _ = select.select(
                        [process.stdout.fileno(), process.stderr.fileno()], [], [], 0.20
                    )
                    if process.stdout.fileno() in readable:
                        chunk = os.read(process.stdout.fileno(), FRAME_BYTES * 2)
                        if chunk:
                            with self._lock:
                                first_bytes = self._bytes_seen == 0
                                self._bytes_seen += len(chunk)
                            if first_bytes:
                                self.trace.record("capture-first-bytes", attempt=self._attempt_number, bytes=len(chunk))
                            buffer.extend(chunk)
                            while len(buffer) >= FRAME_BYTES:
                                frame = bytes(buffer[:FRAME_BYTES])
                                del buffer[:FRAME_BYTES]
                                last_frame = self._clock()
                                with self._lock:
                                    self._frame = frame
                                    self._frame_at = last_frame
                                    self._sequence += 1
                                    self._frames_seen += 1
                                    if self._first_frame_at is None:
                                        self._first_frame_at = last_frame
                                    self._phase = "capturing"
                                    self._error = ""
                                if not captured_frame:
                                    self.trace.record("capture-first-frame", attempt=self._attempt_number,
                                                      after_s=round(last_frame - self._attempt_started_at, 3))
                                captured_frame = True
                    if process.stderr.fileno() in readable:
                        self._read_stderr(process)
                    now = self._clock()
                    if now - last_progress >= 1.0:
                        with self._lock:
                            progress = self._attempt_status()
                        self.trace.record("capture-progress", attempt=self._attempt_number, **progress)
                        last_progress = now
                    if not captured_frame and now - last_frame > FIRST_FRAME_TIMEOUT_SECONDS:
                        raise RuntimeError("First Gamescope frame timed out")
                    if captured_frame and now - last_frame > FRAME_STALL_TIMEOUT_SECONDS:
                        raise RuntimeError("Gamescope capture stopped producing frames")
                    interval = 0.5 if self.trace.previewing else 2.0
                    if now - last_conflict_check >= interval:
                        current = self._pipewire_dump(runtime_dir)
                        self._trace_pipewire(current, node_id)
                        consumers = (
                            self.count_consumers(current, node_id)
                            if node_id is not None else 0
                        )
                        if consumers > 1:
                            self._set_state(
                                "conflict", "Another Gamescope capture consumer appeared",
                                consumers - 1,
                            )
                            break
                        last_conflict_check = now
                if process.poll() is not None and active and not self._stop.is_set():
                    self._read_stderr(process)
                    # Closing-state INFO messages must not replace the actual
                    # negotiation/plugin error in the user-facing failure.
                    detail = self._last_gst_failure or "GStreamer capture ended without a live stream"
                    raise RuntimeError(detail)
            except Exception as error:
                self.trace.record("capture-exception", attempt=self._attempt_number,
                                  error=str(error), error_type=type(error).__name__)
                failed_before_frame = process is not None and not captured_frame
                if process is not None:
                    with self._lock:
                        sustained = (self._first_frame_at is not None and self._frames_seen >= 10
                                     and self._frame_at - self._first_frame_at >= 3.0)
                        self._unhealthy_sessions = 0 if sustained else self._unhealthy_sessions + 1
                    # Release our PipeWire client first. Waiting before this
                    # point leaves a PAUSED pipeline attached to Gamescope and
                    # can make every following selector fail in the same way.
                    self._release_failed_capture(process, error)
                    process = None
                    if self._unhealthy_sessions >= 3:
                        self._selector_mode = "target-object"
                        self._retry_paused = True
                        self.trace.record("capture-retries-paused", attempts=self._attempt_number,
                                          reason="repeated-short-or-empty-sessions")
                        self._set_state("error", "Screen capture paused after repeated failures. Use Preview to retry.")
                        self._wait(SESSION_RESTART_SETTLE_SECONDS)
                        continue
                if captured_frame:
                    # A previously healthy source disappearing means the
                    # Gamescope/PipeWire session is being rebuilt. Do not run
                    # the selector fallback ladder during that transition.
                    self._selector_mode = "target-object"
                    self._set_state(
                        "waiting",
                        "Gamescope session changed; capture closed before rediscovery",
                    )
                    self._wait(max(SESSION_RESTART_SETTLE_SECONDS, backoff))
                    backoff = min(5.0, max(1.0, backoff * 2.0))
                    continue
                if selector_mode == "target-object" and failed_before_frame:
                    self._selector_mode = "target-object-compat"
                    self._set_state(
                        "error",
                        "Gamescope keepalive selector failed; retrying compatibility mode",
                    )
                    backoff = 0.1
                    self._wait(backoff)
                    continue
                if (selector_mode == "target-object-compat" and node_id is not None
                        and failed_before_frame):
                    self._selector_mode = "path"
                    self._set_state(
                        "error",
                        "Named Gamescope selector failed; retrying the legacy node ID",
                    )
                    backoff = 0.1
                    self._wait(backoff)
                    continue
                if (selector_mode in {"target-object-compat", "path"}
                        and failed_before_frame):
                    # A complete failed selector cycle is enough evidence.
                    # Repeated detach/reconnect can aggravate producer faults
                    # and interfere with Steam Recording. Require a new route
                    # activation or an explicit Preview before another cycle.
                    self._selector_mode = "target-object"
                    self._retry_paused = True
                    self.trace.record("capture-retries-paused", attempts=self._attempt_number)
                    self._set_state(
                        "error",
                        "Screen capture paused after repeated failures. Use Preview to retry.",
                    )
                    self._wait(max(SESSION_RESTART_SETTLE_SECONDS, backoff))
                    backoff = min(5.0, max(1.0, backoff * 2.0))
                    continue
                if process is None:
                    # Discovery can fail while the runtime socket is replaced.
                    # Do not carry a selector chosen for the old graph into the
                    # next Gaming Mode session.
                    self._selector_mode = "target-object"
                with self._lock:
                    conflict = self._phase == "conflict"
                if not conflict:
                    self._set_state("error", error)
                self._wait(backoff)
                backoff = min(5.0, backoff * 2.0)
            finally:
                self._finish_process(process, "inactive-or-stopped")
                with self._lock:
                    if self._process is process:
                        self._process = None


class ScreenSyncProvider:
    def __init__(self, capture=None, processor=None, clock=time.monotonic):
        self.capture = capture or ScreenCaptureService(clock=clock)
        self.processor = processor or ScreenSyncProcessor()
        self.clock = clock
        self._active = False
        self._sequence = -1
        self._frame = None

    def set_active(self, active):
        active = bool(active)
        if active != self._active:
            self._active = active
            if not active:
                self.processor.reset()
                self._sequence = -1
                self._frame = None
        # Also acts as an idempotent liveness check. A stopped supervisor may
        # finish just after a game transition; the next tick must spawn its
        # replacement instead of leaving Screen Sync logically on but dead.
        self.capture.set_active(active)

    def stop(self, timeout=None):
        self._active = False
        if timeout is None: self.capture.stop()
        else: self.capture.stop(timeout=timeout)
        self.processor.reset()
        self._frame = None

    def output(self, values):
        if not self._active:
            return ProviderOutput("screen-sync", None, "Screen Sync is off")
        capture_status = self.capture.status()
        if capture_status.get("phase") != "capturing":
            reason = capture_status.get("error") or "Waiting for Gamescope capture"
            return ProviderOutput("screen-sync", None, reason)
        raw, sequence, sampled_at = self.capture.latest()
        if raw is None or not sampled_at or self.clock() - sampled_at > 1.0:
            return ProviderOutput("screen-sync", None, "Waiting for a fresh Gamescope frame")
        if sequence != self._sequence:
            self._frame = self.processor.process(
                raw,
                style=values["screen_sync_style"],
                brightness=values["screen_sync_brightness"],
                reactivity=values["screen_sync_reactivity"],
                colour_intensity=values["screen_sync_colour_intensity"],
                black_threshold=values["screen_sync_black_threshold"],
                ignore_black_bars=values["screen_sync_ignore_black_bars"],
            )
            self._sequence = sequence
        return ProviderOutput("screen-sync", self._frame, "Live Gamescope colours")

    def status(self):
        status = self.capture.status()
        status.update({
            "active": self._active,
            "colors": [list(pixel) for pixel in self._frame] if self._frame else [],
            "crop_top": self.processor.crop[0],
            "crop_bottom": self.processor.crop[1],
        })
        return status

    @property
    def palette_samples(self):
        return self.processor.palette_samples
