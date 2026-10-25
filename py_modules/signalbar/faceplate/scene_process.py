# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
#!/usr/bin/env python3
"""Low-priority, one-shot renderer for generated Faceplate scenes.

The Decky process only decides which semantic scene is wanted. Pixel work and
GIF quantisation happen here, in a short-lived process, so a malformed or
expensive render cannot stall Aura Core or Decky's RPC thread.
"""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import sys


PY_MODULES = Path(__file__).resolve().parents[2]
if str(PY_MODULES) not in sys.path:
    sys.path.insert(0, str(PY_MODULES))

from signalbar.faceplate.scenes import (  # noqa: E402
    HEIGHT, PIXELS, WIDTH, build_dashboard_snapshot,
    build_weather_scene,
)
from signalbar.faceplate.artwork_dashboard import build_artwork_dashboard  # noqa: E402
from signalbar.faceplate.v2_scenes import (  # noqa: E402
    build_v2_dashboard_snapshot,
    build_v2_weather_scene,
)
from signalbar.faceplate.v3_scenes import (  # noqa: E402
    V3_THEME, build_v3_dashboard_snapshot, build_v3_weather_scene,
)
from signalbar.faceplate.weather_artwork import (  # noqa: E402
    WEATHER_ARTWORK_THEMES, build_weather_artwork_dashboard_snapshot,
    build_weather_artwork_scene,
)
from signalbar.faceplate.player_city import build_player_city
from signalbar.faceplate.player_city_animation import animation_manifest
from signalbar.faceplate.render_lock import (  # noqa: E402
    FaceplateRenderBusy, exclusive_render_lock,
)


def _write_bytes(path: Path, value: bytes) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(value)
    os.replace(temporary, path)


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, path)


def main(argv) -> int:
    if len(argv) != 4:
        return 64
    request_path, gif_path, result_path = map(Path, argv[1:])
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        kind = str(request.get("kind", ""))
        visual_theme = str(request.get("visual_theme", "integrated"))
        render_metadata = {}
        with exclusive_render_lock(timeout=20.0):
            if kind == "player-city":
                result = build_player_city(request['weather'], request['phase'], request['players'], row=request.get('row'))
                city = animation_manifest()
                render_metadata = {'players': request['players'], 'appid': request['appid'],
                                   'weather': request['weather'], 'phase': request['phase'],
                                   'frames': len(result.frames), 'duration_ms': sum(result.delays_cs) * 10,
                                   'animation_speed': city['speed'], 'rain_style': city['rain_style'],
                                   'style': city['style'], 'source_revision': city['source_revision']}
            elif kind == "weather":
                if visual_theme == "integrated":
                    result = build_weather_scene(
                        request["condition"], int(request["variant"]),
                        request["temperature_c"], request["unit"], request["phase"],
                        city=request.get("city", ""),
                    )
                elif visual_theme == V3_THEME:
                    result = build_v3_weather_scene(
                        visual_theme, request["condition"], int(request["variant"]),
                        request["temperature_c"], request["unit"], request["phase"],
                        city=request.get("city", ""),
                    )
                elif visual_theme in WEATHER_ARTWORK_THEMES:
                    result, render_metadata = build_weather_artwork_scene(
                        request["condition"], int(request["variant"]),
                        request["temperature_c"], request["unit"], request["phase"],
                        city=request.get("city", ""),
                        weather_code=request.get("weather_code"),
                        wind_speed_kmh=request.get("wind_speed_kmh"),
                        visual_theme=visual_theme,
                        countdown=request.get("countdown"),
                    )
                else:
                    result = build_v2_weather_scene(
                        visual_theme, request["condition"], int(request["variant"]),
                        request["temperature_c"], request["unit"], request["phase"],
                        city=request.get("city", ""),
                    )
            elif kind == "performance":
                raise ValueError("CPU/GPU display has been removed from the Faceplate")
            elif kind == "dashboard":
                arguments = (
                    request.get("display_at", request.get("hour")),
                    request["condition"], int(request["variant"]),
                    request["temperature_c"], request["unit"],
                    request["sunrise"], request["sunset"],
                )
                keywords = {
                    "city": request.get("city", ""),
                    "precipitation_probability": request.get("precipitation_probability"),
                    "clock_24h": bool(request.get("clock_24h", True)),
                    "status": request.get("status"),
                    "battery": request.get("battery"),
                }
                if visual_theme == "integrated":
                    result = build_dashboard_snapshot(*arguments, **keywords)
                elif visual_theme in WEATHER_ARTWORK_THEMES:
                    result, render_metadata = build_weather_artwork_dashboard_snapshot(
                        *arguments, **keywords, visual_theme=visual_theme,
                        bottom_mode=request.get("bottom_mode", "next_hour"),
                        controllers=request.get("controllers", ()),
                        battery_style=request.get("battery_style", "percent"),
                        show_p2=request.get("show_p2", False),
                        forecast=request.get("forecast"),
                        show_weather_notch=request.get("show_weather_notch", True),
                        ux_enabled=request.get("ux_enabled", False),
                        clock_position=request.get("clock_position", "left"),
                        weather_position=request.get("weather_position", "right"),
                        game_running=request.get("game_running", False),
                        show_game_session=request.get("show_game_session", False),
                        session_minutes=request.get("session_minutes", 0),
                        connected_controller_count=request.get("connected_controller_count"),
                        countdown=request.get("countdown"),
                        game_row=request.get("game_row", "existing"),
                        game_stats=request.get("game_stats"),
                        show_clock=request.get("dashboard_show_clock", False),
                        show_status_rail=request.get("dashboard_show_status_rail", True),
                    )
                elif visual_theme == V3_THEME:
                    result = build_v3_dashboard_snapshot(visual_theme, *arguments, **keywords)
                else:
                    result = build_v2_dashboard_snapshot(visual_theme, *arguments, **keywords)
            elif kind == "artwork-dashboard":
                frame_count = int(request.get("dashboard_pack_frames", 0) or 0)
                if not 1 <= frame_count <= 80:
                    raise ValueError("invalid Artwork Dashboard frame count")
                expected_bytes = PIXELS * 3 * frame_count
                if "dashboard_background_rgb" in request:
                    encoded = request["dashboard_background_rgb"]
                    if frame_count != 1 or not isinstance(encoded, str) or len(encoded) != expected_bytes * 2:
                        raise ValueError("Invalid automatic Dashboard background")
                    pack = bytes.fromhex(encoded)
                else:
                    pack_path = Path(str(request.get("dashboard_pack_path", "")))
                    if pack_path.stat().st_size != expected_bytes:
                        raise ValueError("Artwork Dashboard background pack size changed")
                    pack = pack_path.read_bytes()
                expected_sha256 = str(request.get("dashboard_pack_sha256", ""))
                if (len(pack) != expected_bytes or not expected_sha256
                        or hashlib.sha256(pack).hexdigest() != expected_sha256):
                    raise ValueError("Artwork Dashboard background pack failed validation")
                frame_bytes = WIDTH * HEIGHT * 3
                backgrounds = tuple(
                    pack[offset:offset + frame_bytes]
                    for offset in range(0, len(pack), frame_bytes)
                )
                result = build_artwork_dashboard(
                    backgrounds, request["display_at"],
                    request.get("session_minutes", 0), request.get("battery"),
                    treatment=request.get("dashboard_treatment", "none"),
                    show_clock=request.get("dashboard_show_clock", False),
                    clock_size=request.get("dashboard_clock_size", "large"),
                    show_status_rail=request.get("dashboard_show_status_rail", True),
                    show_session=request.get("dashboard_show_session", True),
                    show_battery=request.get("dashboard_show_battery", True),
                    background_signature=expected_sha256,
                    source_frame_count=request.get("source_frame_count", frame_count),
                    status=request.get("status"), weather=request.get("weather"),
                    bottom_mode=request.get("bottom_mode", "next_hour"),
                    controllers=request.get("controllers", ()),
                    battery_style=request.get("battery_style", "percent"),
                    show_p2=request.get("show_p2", False),
                    forecast=request.get("forecast"),
                    unit=request.get("unit", "celsius"),
                    show_weather_notch=request.get("show_weather_notch", True),
                    ux_enabled=request.get("ux_enabled", False),
                    clock_24h=request.get("clock_24h", True),
                    clock_position=request.get("clock_position", "left"),
                    weather_position=request.get("weather_position", "right"),
                    game_running=request.get("game_running", False),
                    show_game_session=request.get("show_game_session", False),
                    connected_controller_count=request.get("connected_controller_count"),
                    countdown=request.get("countdown"),
                    game_row=request.get("game_row", "existing"),
                    game_stats=request.get("game_stats"),
                    compression=request.get(
                        "dashboard_compression", "compatible",
                    ),
                )
                render_metadata = {
                    "frames": len(backgrounds),
                    "delay_cs": result.delay_cs,
                }
            else:
                raise ValueError("unknown generated Faceplate scene")
            payload = result.gif()
        _write_bytes(gif_path, payload)
        _write_json(result_path, {
            "ok": True, "kind": kind, "signature": result.signature,
            "size_bytes": len(payload),
            **render_metadata,
        })
        return 0
    except (FaceplateRenderBusy, KeyError, TypeError, ValueError, OSError) as error:
        try:
            _write_json(result_path, {"ok": False, "error": str(error)[:240]})
        except OSError:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
