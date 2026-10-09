"""Worker thread that owns the faceplate link and feeds it frames for the chosen mode."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time

from . import gif, protocol, render
from .options import for_game, parse_colour
from .transport import Link, LinkBusy, LinkError, find_port

W, H = protocol.WIDTH, protocol.HEIGHT
# The panel stores every GIF in its SPI flash, and each upload takes long
# enough to look like a sector erase. Modes only send when the picture changes,
# and nothing goes out faster than this.
MIN_UPLOAD_GAP = 1.0
# Aura skips light bar changes smaller than this (largest per-channel step,
# 0-255), so slow breathing effects don't turn into a stream of flash writes.
AURA_THRESHOLD = 24
# Brightness x average pixel level the panel may draw. Measured on a Steam
# Machine USB-A port with solid white: 0.40, 0.50 and 0.60 each held for 8 s,
# 0.70 browned out at once (and so did 1.0). A brownout also drops whatever
# shares the port's supply, and the panel can boot-loop because it replays
# its stored picture and brightness at power on. 0.50 leaves margin under the
# 0.60 that held, since 8 s is not a long soak.
POWER_BUDGET = 0.50


def frame_load(rgb):
    return sum(rgb) / (len(rgb) * 255.0) if rgb else 0.0


def safe_brightness(level, load):
    if load * level / 100.0 <= POWER_BUDGET:
        return level
    return max(1, int(POWER_BUDGET * 100 / load))
# Brightness used by the "dim" sleep/shutdown action.
SLEEP_DIM = 10
# How often artwork mode checks which game is running (a /proc scan; art is cached).
ARTWORK_POLL = 5.0


def encode_frame(rgb):
    palette, indices = gif.quantize(rgb)
    return gif.encode(W, H, palette, [indices])


class WriteCounter:
    """Lifetime count of uploads to this faceplate, kept next to the settings."""

    def __init__(self, path):
        self.path = path
        self.total = 0
        if path:
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    self.total = int(json.load(handle).get("uploads", 0))
            except (OSError, ValueError, AttributeError):
                self.total = 0

    def add(self):
        self.total += 1
        if not self.path:
            return
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump({"uploads": self.total}, handle)
            os.replace(tmp, self.path)
        except OSError:
            pass  # the count is informational; never block an upload on it


class FaceplateService:
    def __init__(self, settings, logger=None, link_factory=Link, counter_path=None):
        self.cfg = dict(settings)
        self.logger = logger
        self._link_factory = link_factory
        self.link = None
        self.appid = 0
        self.reported_app = 0
        self.thread = None
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.lock = threading.Lock()
        # The worker and the sleep/shutdown handler both talk to the panel.
        self.link_lock = threading.RLock()
        self.asleep = False
        self.last_hash = None
        self.last_aura = None
        self.last_upload = 0.0
        self.uploads = 0
        self.counter = WriteCounter(counter_path)
        self.upload_ms = 0.0
        self.applied_brightness = None
        self.wanted_brightness = int(self.cfg.get("brightness", 60))
        self.rotate = bool(self.cfg.get("rotate", False))
        # Unknown until our first upload: assume the worst (it may be showing white).
        self.shown_load = 1.0
        self.phase = "starting"
        self.detail = ""
        self.last_error = ""
        self.image_cache = {}

    # ---- lifecycle -----------------------------------------------------
    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name="pixel-faceplate", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=5)
        self._close_link()

    def configure(self, values):
        with self.lock:
            old = self.cfg
            self.cfg = dict(values)
            redraw = (
                "mode", "image_path", "artwork_idle", "clock_colour", "clock_24h",
                "art_style", "logo_position", "rotate", "game_profiles",
            )
            if any(old.get(k) != self.cfg.get(k) for k in redraw):
                self.last_hash = None
                self.last_aura = None
            if old.get("brightness") != self.cfg.get("brightness"):
                self.applied_brightness = None
        self.wake.set()

    def game_event(self, appid, running):
        """Steam said a game started or stopped; redraw now instead of at the next poll."""
        appid = int(appid or 0)
        if running and appid:
            self.reported_app = appid
        elif not appid or appid == self.reported_app:
            self.reported_app = 0  # app ID 0 means no game at all
        self.wake.set()

    def status(self):
        with self.lock:
            cfg = dict(self.cfg)
        return {
            "phase": self.phase,
            "detail": self.detail,
            "connected": self.link is not None,
            "port": find_port() or "",
            "uploads": self.uploads,
            "lifetime_uploads": self.counter.total,
            "upload_ms": round(self.upload_ms),
            "brightness_applied": self.applied_brightness,
            "appid": self.appid,
            "last_error": self.last_error,
            "settings": cfg,
        }

    # ---- helpers -------------------------------------------------------
    def _log(self, level, message):
        if self.logger:
            getattr(self.logger, level)("[GabeCubeAura] faceplate: " + message)

    def _set(self, phase, detail=""):
        if (phase, detail) != (self.phase, self.detail):
            self._log("info", "%s %s" % (phase, detail))
        self.phase, self.detail = phase, detail

    def _close_link(self):
        if self.link:
            self.link.close()
        self.link = None
        self.applied_brightness = None

    def _ensure_link(self):
        port = find_port()
        if self.link is not None and port == self.link.port:
            return True
        if self.link is not None:
            # Replugged (often under a new ttyUSB name): the old fd is dead.
            self._close_link()
        if not port:
            self._set("waiting", "faceplate not plugged in")
            return False
        try:
            self.link = self._link_factory(log=lambda m: self._log("debug", m)).open()
        except LinkBusy as error:
            self.link = None
            self._set("busy", "%s; turn one of them off" % error)
            return False
        except (LinkError, OSError) as error:
            self.last_error = str(error)
            self.link = None
            self._set("error", str(error))
            return False
        # The screen may have been switched off at the last sleep or shutdown.
        try:
            self.link.command(protocol.power(True), timeout=0.5, retries=2)
        except LinkError:
            pass
        # A fresh link (or a replugged panel) gets the current picture once.
        self.last_hash = None
        self.last_aura = None
        return True

    def _apply_brightness(self, level):
        if self.applied_brightness == level:
            return
        # The panel never acknowledges brightness, so write it and move on.
        self.link.write(protocol.brightness(level))
        self.applied_brightness = level

    def _upload(self, rgb):
        if self.rotate:
            rgb = render.rotate(rgb)
        digest = hashlib.blake2b(rgb, digest_size=16).digest()
        if digest == self.last_hash:
            return False
        gap = time.monotonic() - self.last_upload
        if gap < MIN_UPLOAD_GAP:
            time.sleep(MIN_UPLOAD_GAP - gap)
        load = frame_load(rgb)
        target = safe_brightness(self.wanted_brightness, load)
        # Dim before a bright frame goes up, never after: the panel stores
        # both and replays them at boot.
        if self.applied_brightness is None or target < self.applied_brightness:
            self._apply_brightness(target)
        data = encode_frame(rgb)
        started = time.monotonic()
        wrote = self.link.send_gif(data)
        self.last_upload = time.monotonic()
        self.last_hash = digest
        self.shown_load = load
        self._apply_brightness(target)
        if not wrote:
            return False  # the panel already held this exact GIF
        self.upload_ms = (self.last_upload - started) * 1000
        self.uploads += 1
        self.counter.add()
        return True

    # ---- modes ---------------------------------------------------------
    def _image_frame(self, path, fill):
        key = (path, fill, os.path.getmtime(path) if path and os.path.exists(path) else 0)
        if key not in self.image_cache:
            self.image_cache.clear()
            self.image_cache[key] = render.decode_image(path, fill=fill) if path else None
        return self.image_cache[key]

    def _artwork_frame(self, appid, cfg):
        if not appid:
            return None
        key = ("app", appid, cfg["art_style"], cfg["logo_position"])
        if key not in self.image_cache:
            self.image_cache.clear()
            self.image_cache[key] = render.artwork(appid, style=cfg["art_style"], position=cfg["logo_position"])
        return self.image_cache[key]

    def _steam_logo(self):
        if "steam_logo" not in self.__dict__:
            self.steam_logo = render.steam_logo()
        return self.steam_logo

    def _clock_frame(self, cfg):
        return render.clock(colour=parse_colour(cfg["clock_colour"]), use_24h=cfg["clock_24h"])

    @staticmethod
    def _until_next_minute():
        return 60.5 - time.time() % 60  # wake just after the minute turns

    def _aura_changed(self, colours):
        if self.last_aura is None or len(colours) != len(self.last_aura):
            return True
        return max(
            (abs(a - b) for old, new in zip(self.last_aura, colours) for a, b in zip(old, new)),
            default=0,
        ) >= AURA_THRESHOLD

    def _mode_step(self, cfg):
        mode = cfg["mode"]
        if mode == "clock":
            self._upload(self._clock_frame(cfg))
            self._set("running", "clock")
            return self._until_next_minute()
        if mode == "aura":
            colours = render.read_lightbar()
            if self._aura_changed(colours):
                if self._upload(render.aura(colours)):
                    self.last_aura = colours
            self._set("running", "aura from %d light bar LEDs" % len(colours))
            return cfg["aura_interval"]
        if mode == "image":
            rgb = self._image_frame(cfg["image_path"], True)
            if rgb is None:
                self._set("error", "can't read image %s" % (cfg["image_path"] or "(none set)"))
                return 5.0
            self._upload(rgb)
            self._set("running", "showing %s" % os.path.basename(cfg["image_path"]))
            return 30.0
        if mode == "artwork":
            # Steam's own launch/exit event (from the frontend) is instant; the
            # /proc check covers a client where that event never arrives.
            self.appid = self.reported_app or render.running_appid()
            rgb = self._artwork_frame(self.appid, for_game(cfg, self.appid))
            if rgb is None:
                # Nothing running (or no art cached for this game).
                idle = cfg["artwork_idle"]
                if idle == "steam":
                    logo = self._steam_logo()
                    if logo is not None:
                        self._upload(logo)
                        self._set("running", "no game running, showing the Steam logo")
                        return ARTWORK_POLL
                    idle = "keep"  # no icon on this system
                if idle == "clock":
                    self._upload(self._clock_frame(cfg))
                    self._set("running", "no game running, showing the clock")
                    return min(ARTWORK_POLL, self._until_next_minute())
                self._set("running", "no game running, keeping the last picture")
                return ARTWORK_POLL
            self._upload(rgb)
            self._set("running", "artwork for app %d" % self.appid)
            return ARTWORK_POLL
        return 5.0

    def step(self):
        with self.link_lock:
            return self._step()

    def _step(self):
        with self.lock:
            cfg = dict(self.cfg)
        if self.asleep:
            return 5.0  # the system is going down; don't wake the screen
        if cfg["mode"] == "off":
            self._close_link()  # release the port so other tools can use it
            self._set("off", "panel keeps its last picture")
            return 3600.0
        if not self._ensure_link():
            return 10.0 if self.phase == "busy" else 2.0
        try:
            self.rotate = cfg["rotate"]
            self.wanted_brightness = cfg["brightness"]
            self._apply_brightness(safe_brightness(self.wanted_brightness, self.shown_load))
            return self._mode_step(cfg)
        except (LinkError, OSError) as error:
            self.last_error = str(error)
            self._log("warning", "link error: %s" % error)
            self._close_link()
            self._set("error", str(error))
            return 2.0

    def power_event(self, kind, starting):
        """Steam Machine about to sleep/shut down (starting) or back again. Must be quick."""
        with self.lock:
            cfg = dict(self.cfg)
        if cfg["mode"] == "off":
            return  # the panel is not ours to touch
        action = cfg["sleep_action"] if kind == "sleep" else cfg["shutdown_action"]
        with self.link_lock:
            if starting:
                self.asleep = True
                if action == "keep" or not self._ensure_link():
                    return
                if action == "off":
                    self.link.command(protocol.power(False), timeout=0.5, retries=2)
                else:  # dim; no ACK for brightness
                    self.link.write(protocol.brightness(min(SLEEP_DIM, self.applied_brightness or SLEEP_DIM)))
                    self.applied_brightness = None
                self._set("asleep", "%s: screen %s" % (kind, "off" if action == "off" else "dimmed"))
            else:
                self.asleep = False
                self.applied_brightness = None  # put the user's brightness back
                if self._ensure_link():
                    self.link.command(protocol.power(True), timeout=0.5, retries=2)
                self.wake.set()

    def _run(self):
        while not self.stop_event.is_set():
            try:
                delay = self.step()
            except Exception as error:  # keep the thread alive; report and back off
                self.last_error = "%s: %s" % (type(error).__name__, error)
                self._log("error", self.last_error)
                self._set("error", self.last_error)
                delay = 5.0
            if delay:
                self.wake.wait(delay)
                self.wake.clear()
