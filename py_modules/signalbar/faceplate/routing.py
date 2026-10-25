# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Faceplate-only routing preferences and scene preparation state.

This module deliberately has no dependency on the LED-bar settings or on the
serial transport.  It provides the small shared contract needed by Decky,
Pixel Studio and a future standalone faceplate service:

* versioned, atomic Home/Game route preferences;
* a monotonic revision for cross-process coordination;
* explicit desired/effective/preparation state; and
* generation tickets which make asynchronous preparation latest-wins.

Selecting routes here never enables or writes to the physical faceplate.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, Optional, Tuple

try:  # SteamOS and the development hosts are POSIX.
    import fcntl
except ImportError:  # pragma: no cover - defensive fallback for non-POSIX tools
    fcntl = None


PREFERENCES_SCHEMA = 2
HOME_SCENES: Tuple[str, ...] = ("weather", "dashboard", "native-clock", "artwork", "artwork-dashboard")
GAME_SCENES: Tuple[str, ...] = (
    "dashboard",
    "artwork",
    "artwork-dashboard",
    "weather",
    "player-city",
)
DEFAULT_HOME_SCENE = "dashboard"
DEFAULT_GAME_SCENE = "artwork"
VISUAL_THEMES: Tuple[str, ...] = (
    "integrated",
    "night-paper-v3",
    "night-paper",
    "sun-cut",
    "winter-loom",
)
LEGACY_WEATHER_THEME = "weather-artwork-v1"
REALISTIC_WEATHER_THEME = "weather-artwork-v2"
# Public compatibility name retained for older callers. Lab 42 presents one
# coherent Realistic V2 system; the V1 assets remain packaged for rollback.
LUMINOUS_WEATHER_THEME = REALISTIC_WEATHER_THEME
WEATHER_VISUAL_THEMES: Tuple[str, ...] = (REALISTIC_WEATHER_THEME,)
DASHBOARD_VISUAL_THEMES: Tuple[str, ...] = WEATHER_VISUAL_THEMES
SCENE_THEME_KINDS: Tuple[str, ...] = ("weather", "dashboard")
DEFAULT_VISUAL_THEME = "integrated"

PREPARATION_IDLE = "idle"
PREPARATION_PENDING = "pending"
PREPARATION_PREPARING = "preparing"
PREPARATION_READY = "ready"
PREPARATION_ERROR = "error"


class FaceplatePreferencesError(RuntimeError):
    """Base error for invalid or unreadable faceplate preferences."""


class FaceplateRevisionConflict(FaceplatePreferencesError):
    """Raised when a writer is based on a stale preferences revision."""


def default_preferences_path() -> Path:
    """Return the shared user-level preferences path.

    ``DECKY_USER_HOME`` keeps the path correct when Decky runs the backend as
    root while the standalone component runs as the Steam user.
    """

    home = os.environ.get("DECKY_USER_HOME") or os.path.expanduser("~")
    return Path(home) / ".local" / "share" / "gabecubeaura" / "faceplate" / "preferences.json"


def _validate_scene(context: str, scene: str) -> str:
    context = str(context or "").strip().lower()
    scene = str(scene or "").strip().lower()
    allowed = HOME_SCENES if context == "home" else GAME_SCENES if context == "game" else ()
    if scene not in allowed:
        choices = ", ".join(allowed) if allowed else "home or game context required"
        raise ValueError(f"invalid faceplate {context!r} scene {scene!r}; expected {choices}")
    return scene


def _validate_visual_theme(theme: str, scene_kind: Optional[str] = None) -> str:
    theme = str(theme or "").strip().lower()
    scene_kind = str(scene_kind or "").strip().lower()
    allowed = (
        WEATHER_VISUAL_THEMES if scene_kind == "weather"
        else DASHBOARD_VISUAL_THEMES if scene_kind == "dashboard"
        else VISUAL_THEMES
    )
    if scene_kind and scene_kind not in SCENE_THEME_KINDS:
        raise ValueError(
            f"invalid faceplate scene theme kind {scene_kind!r}; expected "
            + ", ".join(SCENE_THEME_KINDS)
        )
    if theme not in allowed:
        raise ValueError(
            f"invalid faceplate {scene_kind or 'visual'} theme {theme!r}; expected "
            + ", ".join(allowed)
        )
    return theme


@dataclass(frozen=True)
class FaceplateRoutingPreferences:
    """Immutable snapshot shared by all faceplate control surfaces."""

    revision: int = 0
    home_scene: str = DEFAULT_HOME_SCENE
    game_scene: str = DEFAULT_GAME_SCENE
    weather_visual_theme: str = REALISTIC_WEATHER_THEME
    dashboard_visual_theme: str = REALISTIC_WEATHER_THEME
    performance_visual_theme: str = DEFAULT_VISUAL_THEME
    updated_at: float = 0.0
    # None inherits an existing Lab119/121 consent. New acceptances live in
    # this same atomic document as their routes, never in a second write.
    performance_consent: Optional[str] = None
    schema: int = PREFERENCES_SCHEMA

    def scene_for(self, context: str) -> str:
        context = str(context or "").strip().lower()
        if context == "home":
            return self.home_scene
        if context == "game":
            return self.game_scene
        raise ValueError(f"invalid faceplate context {context!r}")

    @property
    def visual_theme(self) -> str:
        """Legacy global-theme alias retained for older clients.

        This alias remains scoped to the configurable Performance renderer.
        """

        return self.performance_visual_theme

    def theme_for(self, scene: str) -> str:
        scene = str(scene or "").strip().lower()
        if scene == "weather":
            return self.weather_visual_theme
        if scene == "dashboard":
            return self.dashboard_visual_theme
        if scene == "performance":
            return self.performance_visual_theme
        return self.dashboard_visual_theme

    def as_dict(self) -> Dict[str, object]:
        return {
            "schema": self.schema,
            "revision": self.revision,
            "routes": {
                "home": self.home_scene,
                "game": self.game_scene,
            },
            "visual_theme": self.visual_theme,
            "scene_themes": {
                "weather": self.weather_visual_theme,
                "dashboard": self.dashboard_visual_theme,
                "performance": self.performance_visual_theme,
            },
            "updated_at": self.updated_at,
            "performance_consent": self.performance_consent,
        }


_PATH_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: Dict[str, threading.RLock] = {}


def _path_lock(path: Path) -> threading.RLock:
    key = os.path.abspath(os.fspath(path))
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


class FaceplatePreferencesStore:
    """Atomic, revisioned persistence for Faceplate routes only."""

    def __init__(self, path: Optional[os.PathLike] = None, *, wall_clock=time.time, calibrated=False):
        self.path = Path(path) if path is not None else default_preferences_path()
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self.wall_clock = wall_clock
        self.calibrated = bool(calibrated)
        self._lock = _path_lock(self.path)

    def defaults(self) -> FaceplateRoutingPreferences:
        return (FaceplateRoutingPreferences(home_scene="dashboard",game_scene="artwork-dashboard")
                if self.calibrated else FaceplateRoutingPreferences())

    def _decode(self, payload: object) -> FaceplateRoutingPreferences:
        if not isinstance(payload, dict):
            raise FaceplatePreferencesError("faceplate preferences must be a JSON object")
        schema = payload.get("schema")
        if schema not in (1, PREFERENCES_SCHEMA):
            raise FaceplatePreferencesError(
                f"unsupported faceplate preferences schema {schema!r}"
            )
        revision = payload.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise FaceplatePreferencesError("faceplate preferences revision must be a non-negative integer")
        routes = payload.get("routes")
        if not isinstance(routes, dict):
            raise FaceplatePreferencesError("faceplate preferences routes must be an object")
        # A legacy saved route is migrated deterministically; a NEW request is
        # rejected by update() and cannot resurrect the retired writer.
        home_scene = _validate_scene("home", "dashboard" if routes.get("home") == "performance" else routes.get("home"))
        game_scene = _validate_scene("game", "dashboard" if routes.get("game") == "performance" else routes.get("game"))
        legacy_visual_theme = str(payload.get(
            "visual_theme", DEFAULT_VISUAL_THEME,
        )).strip().lower()
        if legacy_visual_theme not in VISUAL_THEMES:
            legacy_visual_theme = DEFAULT_VISUAL_THEME
        scene_themes = payload.get("scene_themes", {}) if schema == PREFERENCES_SCHEMA else {}
        if not isinstance(scene_themes, dict):
            raise FaceplatePreferencesError("faceplate scene_themes must be an object")
        # Historical choices migrate in memory to the sole Realistic V2 route.
        weather_visual_theme = str(scene_themes.get(
            "weather", REALISTIC_WEATHER_THEME,
        )).strip().lower()
        if weather_visual_theme not in WEATHER_VISUAL_THEMES:
            weather_visual_theme = REALISTIC_WEATHER_THEME
        dashboard_visual_theme = str(scene_themes.get(
            "dashboard", REALISTIC_WEATHER_THEME,
        )).strip().lower()
        if dashboard_visual_theme not in DASHBOARD_VISUAL_THEMES:
            dashboard_visual_theme = REALISTIC_WEATHER_THEME
        performance_visual_theme = _validate_visual_theme(
            scene_themes.get("performance", legacy_visual_theme),
        )
        updated_at = payload.get("updated_at", 0.0)
        if isinstance(updated_at, bool) or not isinstance(updated_at, (int, float)):
            raise FaceplatePreferencesError("faceplate preferences updated_at must be numeric")
        return FaceplateRoutingPreferences(
            revision=revision,
            home_scene=home_scene,
            game_scene=game_scene,
            weather_visual_theme=weather_visual_theme,
            dashboard_visual_theme=dashboard_visual_theme,
            performance_visual_theme=performance_visual_theme,
            updated_at=float(updated_at),
            performance_consent=None,
        )

    @staticmethod
    def _consent(value):
        from .performance_policy import CONSENT_REVISION
        if value not in (None, "", CONSENT_REVISION):
            raise FaceplatePreferencesError("invalid CPU/GPU consent revision")
        return value

    def _read_unlocked(self, *, strict: bool) -> FaceplateRoutingPreferences:
        try:
            if self.path.stat().st_size > 65536:
                raise FaceplatePreferencesError("faceplate preferences exceed 64 KiB")
            with self.path.open("r", encoding="utf-8") as stream:
                return self._decode(json.load(stream))
        except FileNotFoundError:
            return self.defaults()
        except (OSError, ValueError, TypeError, FaceplatePreferencesError) as caught:
            if strict:
                if isinstance(caught, FaceplatePreferencesError):
                    raise
                raise FaceplatePreferencesError(
                    f"cannot read faceplate preferences: {caught}"
                ) from caught
            return self.defaults()

    def read(self) -> FaceplateRoutingPreferences:
        """Read a snapshot; absent/corrupt files degrade to inert defaults."""

        with self._lock:
            return self._read_unlocked(strict=False)

    @contextmanager
    def _exclusive_write(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self.lock_path.open("a+b") as lock_stream:
                if fcntl is not None:
                    fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    if fcntl is not None:
                        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)

    def _write_unlocked(self, preferences: FaceplateRoutingPreferences, *, preserve_unknown=True) -> None:
        payload = preferences.as_dict()
        # Keep unknown fields from a compatible schema for forward/backward
        # editing. Never expose them via the public snapshot or interpret them.
        if preserve_unknown and self.path.exists():
            with self.path.open('r', encoding='utf-8') as stream:
                previous = json.load(stream)
            payload = {**previous, **payload}
            old_routes = previous.get("routes", {})
            if any(old_routes.get(slot) == "performance" for slot in ("home", "game")):
                payload.setdefault("retired_performance_routes", dict(old_routes))
                payload["route_migration"] = "performance-retired-v1"
            for name in ('routes', 'scene_themes'):
                payload[name] = {**previous.get(name, {}), **preferences.as_dict()[name]}
        encoded = json.dumps(payload, indent=2, sort_keys=True) + '\n'
        if len(encoded.encode('utf-8')) > 65536:
            raise FaceplatePreferencesError('faceplate preferences exceed 64 KiB')
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=self.path.name + ".",
            suffix=".tmp",
            dir=os.fspath(self.path.parent),
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary_name, 0o644)
            os.replace(temporary_name, self.path)
            try:
                flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                directory_descriptor = os.open(os.fspath(self.path.parent), flags)
                try:
                    os.fsync(directory_descriptor)
                finally:
                    os.close(directory_descriptor)
            except OSError:
                pass  # The file fsync + atomic replace remain the core guarantee.
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass

    def reset(self) -> FaceplateRoutingPreferences:
        """Restore all route/theme preferences without rewinding their revision."""
        with self._exclusive_write():
            current = self._read_unlocked(strict=self.path.exists())
            defaults = replace(self.defaults(),revision=current.revision + 1)
            self._write_unlocked(defaults, preserve_unknown=False)
            return defaults

    def update(
        self,
        *,
        home_scene: Optional[str] = None,
        game_scene: Optional[str] = None,
        visual_theme: Optional[str] = None,
        scene_kind: Optional[str] = None,
        scene_theme: Optional[str] = None,
        expected_revision: Optional[int] = None,
        performance_consent: Optional[str] = None,
    ) -> FaceplateRoutingPreferences:
        """Update either route and return the new shared snapshot.

        A real change increments the on-disk revision exactly once.  A no-op
        preserves it.  ``expected_revision`` enables optimistic concurrency
        for Decky and Pixel Studio without creating a second source of truth.
        """

        if home_scene is not None:
            home_scene = _validate_scene("home", home_scene)
        if performance_consent is not None:
            performance_consent = self._consent(performance_consent)
        if game_scene is not None:
            game_scene = _validate_scene("game", game_scene)
        if visual_theme is not None:
            visual_theme = _validate_visual_theme(visual_theme)
        if (scene_kind is None) != (scene_theme is None):
            raise ValueError("scene_kind and scene_theme must be updated together")
        if scene_kind is not None:
            scene_kind = str(scene_kind or "").strip().lower()
            scene_theme = _validate_visual_theme(scene_theme, scene_kind)
        if expected_revision is not None and (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            raise ValueError("expected_revision must be a non-negative integer")

        with self._exclusive_write():
            current = self._read_unlocked(strict=self.path.exists())
            if expected_revision is not None and current.revision != expected_revision:
                raise FaceplateRevisionConflict(
                    f"stale faceplate preferences revision {expected_revision}; "
                    f"current revision is {current.revision}"
                )
            next_home = current.home_scene if home_scene is None else home_scene
            next_game = current.game_scene if game_scene is None else game_scene
            next_consent = current.performance_consent if performance_consent is None else performance_consent
            next_weather_theme = current.weather_visual_theme
            next_dashboard_theme = current.dashboard_visual_theme
            next_performance_theme = current.performance_visual_theme
            # The legacy global setter remains Performance-only.
            if visual_theme is not None:
                next_performance_theme = visual_theme
            if scene_kind == "weather":
                next_weather_theme = scene_theme
            elif scene_kind == "dashboard":
                next_dashboard_theme = scene_theme
            elif scene_kind == "performance":
                next_performance_theme = scene_theme
            if (
                next_home == current.home_scene
                and next_game == current.game_scene
                and next_weather_theme == current.weather_visual_theme
                and next_dashboard_theme == current.dashboard_visual_theme
                and next_performance_theme == current.performance_visual_theme
                and next_consent == current.performance_consent
            ):
                return current
            updated = FaceplateRoutingPreferences(
                revision=current.revision + 1,
                home_scene=next_home,
                game_scene=next_game,
                weather_visual_theme=next_weather_theme,
                dashboard_visual_theme=next_dashboard_theme,
                performance_visual_theme=next_performance_theme,
                updated_at=float(self.wall_clock()),
                performance_consent=next_consent,
            )
            self._write_unlocked(updated)
            return updated


@dataclass(frozen=True)
class FaceplateSceneTicket:
    """Identity of one asynchronous preparation request."""

    generation: int
    scene: str
    context: str
    content_key: str
    preference_revision: int


class FaceplateSceneRouter:
    """Model desired/effective scenes and reject stale preparation results."""

    def __init__(self, preferences: Optional[FaceplatePreferencesStore] = None):
        self.preferences = preferences or FaceplatePreferencesStore()
        self._lock = threading.RLock()
        self._preferences = self.preferences.read()
        self._generation = 0
        self._desired_scene = ""
        self._desired_content_key = ""
        self._effective_scene = ""
        self._effective_content_key = ""
        self._prepared_scene = ""
        self._prepared_content_key = ""
        self._context = "home"
        self._preparation_state = PREPARATION_IDLE
        self._preparation_reason = ""
        self._preparation_error = ""
        self._active_ticket: Optional[FaceplateSceneTicket] = None
        self._superseded = 0

    def reconcile(
        self,
        *,
        game_running: bool,
        content_key: str = "",
        reason: str = "context",
        force: bool = False,
        transient_scene: str = "",
    ) -> FaceplateSceneTicket:
        """Resolve the selected route and create work only when it changed.

        ``content_key`` represents inputs within a scene (weather revision,
        game/app id, telemetry layout revision, time bucket, ...).  Changing it
        requests a new generation even when the selected scene is unchanged.
        """

        snapshot = self.preferences.read()
        context = "game" if bool(game_running) else "home"
        if transient_scene and transient_scene != "cinema":
            raise ValueError("Unknown temporary Faceplate route")
        scene = transient_scene or snapshot.scene_for(context)
        if transient_scene:
            context = "cinema"
        key = str(content_key or "")
        reason = str(reason or "")
        with self._lock:
            self._preferences = snapshot
            changed = (
                scene != self._desired_scene
                or context != self._context
                or key != self._desired_content_key
            )
            if not changed and not force and self._active_ticket is not None:
                return self._active_ticket
            if self._preparation_state in (PREPARATION_PENDING, PREPARATION_PREPARING):
                self._superseded += 1
            self._generation += 1
            self._context = context
            self._desired_scene = scene
            self._desired_content_key = key
            self._preparation_state = PREPARATION_PENDING
            self._preparation_reason = reason
            self._preparation_error = ""
            self._active_ticket = FaceplateSceneTicket(
                generation=self._generation,
                scene=scene,
                context=context,
                content_key=key,
                preference_revision=snapshot.revision,
            )
            return self._active_ticket

    def invalidate(self, reason="cancelled"):
        """Fence already prepared work before Off, shutdown or suspension."""
        with self._lock:
            self._generation += 1
            self._active_ticket = None
            self._preparation_state = PREPARATION_IDLE
            self._preparation_reason = str(reason)[:120]
            self._preparation_error = ""
            self._superseded += 1

    def mark_preparing(self, ticket: FaceplateSceneTicket) -> bool:
        with self._lock:
            if ticket != self._active_ticket:
                return False
            self._preparation_state = PREPARATION_PREPARING
            self._preparation_error = ""
            return True

    def mark_prepared(self, ticket: FaceplateSceneTicket) -> bool:
        """Prepared bytes are not a USB receipt or observable playback."""
        with self._lock:
            if ticket != self._active_ticket:
                return False
            self._prepared_scene, self._prepared_content_key = ticket.scene, ticket.content_key
            return True

    def commit(self, ticket: FaceplateSceneTicket) -> bool:
        """Make a prepared scene effective only if its generation is current."""

        with self._lock:
            if ticket != self._active_ticket:
                return False
            self._effective_scene = ticket.scene
            self._effective_content_key = ticket.content_key
            self._prepared_scene, self._prepared_content_key = ticket.scene, ticket.content_key
            self._preparation_state = PREPARATION_READY
            self._preparation_error = ""
            return True

    def fail(self, ticket: FaceplateSceneTicket, error: object) -> bool:
        """Record a current failure while preserving the last effective scene."""

        with self._lock:
            if ticket != self._active_ticket:
                return False
            self._preparation_state = PREPARATION_ERROR
            self._preparation_error = str(error or "unknown preparation error")[:240]
            return True

    def sent_unconfirmed(self, ticket: FaceplateSceneTicket, error: object) -> bool:
        """Keep desired/effective separate without re-uploading unchanged data."""
        with self._lock:
            if ticket != self._active_ticket:
                return False
            self._preparation_state = 'unconfirmed'
            self._preparation_error = str(error or 'Final USB confirmation unavailable')[:240]
            return True

    def preference_status(self) -> Dict[str, object]:
        """Saved choices are readable even while another route owns the panel.

        Do not reconcile or touch the worker here. Desired/effective state and
        its applied revision still describe the last actual reconciliation.
        """
        preferences = self.preferences.read()
        status = self.status()
        status.update({
            "applied_preference_revision": status["preference_revision"],
            "preference_revision": preferences.revision,
            "routes": {"home": preferences.home_scene, "game": preferences.game_scene},
            "visual_theme": preferences.visual_theme,
            "scene_themes": {
                "weather": preferences.weather_visual_theme,
                "dashboard": preferences.dashboard_visual_theme,
                "performance": preferences.performance_visual_theme,
            },
        })
        return status

    def status(self) -> Dict[str, object]:
        with self._lock:
            ticket = self._active_ticket
            return {
                "schema": 1,
                "preference_revision": self._preferences.revision,
                "routes": {
                    "home": self._preferences.home_scene,
                    "game": self._preferences.game_scene,
                },
                "visual_theme": self._preferences.visual_theme,
                "scene_themes": {
                    "weather": self._preferences.weather_visual_theme,
                    "dashboard": self._preferences.dashboard_visual_theme,
                    "performance": self._preferences.performance_visual_theme,
                },
                "context": self._context,
                "generation": self._generation,
                "desired_scene": self._desired_scene,
                "desired_content_key": self._desired_content_key,
                "effective_scene": self._effective_scene,
                "effective_content_key": self._effective_content_key,
                "prepared_scene": self._prepared_scene,
                "prepared_content_key": self._prepared_content_key,
                "visible_on_panel": "unknown",
                "preparation": {
                    "state": self._preparation_state,
                    "generation": ticket.generation if ticket else 0,
                    "scene": ticket.scene if ticket else "",
                    "content_key": ticket.content_key if ticket else "",
                    "reason": self._preparation_reason,
                    "error": self._preparation_error,
                },
                "superseded": self._superseded,
            }
