"""Source-only spatial projection. Never accepts a composed Dashboard GIF."""
import hashlib
import json
from pathlib import Path

WIDTH, HEIGHT, LEDS = 64, 54, 17
REVISION = 'source-projection-stable-v2'


def project_backgrounds(frames, mapping='bottom', rotate=False, *, height=HEIGHT):
    """Area-weighted 64/17 bins, averaged over the original animation cycle.

    Integer bin overlaps cover every column exactly, including fractional
    boundaries. No black exclusion, saturation boost or output gain here.
    """
    if height not in (45, HEIGHT) or mapping not in ('bottom', 'whole') or not 1 <= len(frames) <= (192 if height == 45 else 80):
        raise ValueError('Invalid source projection')
    # City supplies only its 45 artwork rows: the counter rail is never sampled.
    rows = range(height - 8, height) if mapping == 'bottom' else range(height)
    totals = [[0, 0, 0] for _ in range(LEDS)]
    for frame in frames:
        if len(frame) != WIDTH * height * 3:
            raise ValueError('Projection requires original RGB frames at the declared height')
        for led in range(LEDS):
            left, right = led * WIDTH, (led + 1) * WIDTH
            for x in range(left // LEDS, min(WIDTH, (right + LEDS - 1) // LEDS)):
                weight = min(right, (x + 1) * LEDS) - max(left, x * LEDS)
                for y in rows:
                    pixel = (height - 1 - y) * WIDTH + WIDTH - 1 - x if rotate else y * WIDTH + x
                    offset = pixel * 3
                    for channel in range(3):
                        totals[led][channel] += frame[offset + channel] * weight
    divisor = WIDTH * len(rows) * len(frames)
    return [tuple((value + divisor // 2) // divisor for value in colour) for colour in totals]


def load_source(source):
    if source.get('kind') == 'weather':
        from .weather_artwork import _backgrounds, _preset, WEATHER_ARTWORK_THEMES
        if source.get('theme') not in WEATHER_ARTWORK_THEMES:
            raise ValueError('Unsupported Weather source')
        metadata = _preset(source['preset_id'], source['theme'], source.get('phase'))
        if metadata.get('background_raw_sha256') != source.get('sha256'):
            raise ValueError('Weather source checksum changed')
        return _backgrounds(source['theme'], source['preset_id'], source.get('phase'))
    if source.get('kind') == 'player-city':
        from .player_city_animation import animated_rgb, projection_source
        expected = projection_source(source['weather'], source['phase'], source['tier'])
        if any(source.get(key) != value for key, value in expected.items()):
            raise ValueError('Player City source identity changed')
        return animated_rgb(source['weather'], source['phase'], source['tier'])
    if source.get('kind') != 'artwork':
        raise ValueError('Source image unavailable')
    path = Path(source['path'])
    root = Path(source['root'])
    if path.name != 'artwork-dashboard.rgb' or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Unsafe source background path')
    if not root.is_dir() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Source background escapes artwork library')
    count = int(source['frames'])
    if not 1 <= count <= 80 or path.stat().st_size != count * WIDTH * HEIGHT * 3:
        raise ValueError('Source background has invalid size')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != source.get('sha256'):
        raise ValueError('Source background checksum mismatch')
    size = WIDTH * HEIGHT * 3
    return tuple(raw[offset:offset + size] for offset in range(0, len(raw), size))


def cache_key(source, mapping, rotate):
    # Overlay minute, controllers and Faceplate ACK identities are not sources.
    identity = {key: value for key, value in source.items() if key not in (
        'asset', 'context', 'appid', 'delivery_signature', 'background_key', 'background_generation',
        'prepared', 'route_appid')}
    return hashlib.sha256(json.dumps([REVISION, identity, mapping, bool(rotate)],
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def background_key(payload, context, game_appid, fingerprint='', layout=None):
    """Upstream original-image identity, never a complete GIF or overlay key.

    This uses the route's existing lightweight metadata. No pixels, filesystem,
    palette preparation or USB work here. Context and the running app identify
    real Home/game transitions even when both routes share a weather background.
    """
    kind = payload.get('kind')
    if kind in ('artwork', 'artwork-dashboard') and payload.get('appid'):
        original = ['artwork', payload['appid'], payload.get('source', 'hero'), fingerprint, layout]
    elif kind in ('weather', 'dashboard') and payload.get('condition') and payload.get('phase'):
        original = ['weather', payload.get('visual_theme'), payload['condition'],
                    payload.get('variant', 0), payload['phase'], fingerprint]
    elif kind == 'player-city':
        from .player_city import population_tier, REVISION as CITY_REVISION
        tier = population_tier(payload.get('players'))
        if tier is None:
            return None
        original = ['player-city', payload.get('weather'), payload.get('phase'), tier, CITY_REVISION]
    else:
        return None
    return hashlib.sha256(json.dumps([1, context, game_appid, original],
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def saturate_colours(colours, percentage=100):
    """HSV-equivalent saturation, with unchanged hue and maximum RGB channel.

    Applied to only the retained 17-colour palette, not source frames. Neutral
    grey/white stays neutral; black stays black; there is no brightness boost.
    """
    gain = max(0, min(250, percentage)) / 100
    if gain == 1:
        return tuple(tuple(rgb) for rgb in colours)
    result = []
    for rgb in colours:
        high, low = max(rgb), min(rgb)
        if high == low:
            result.append(tuple(rgb))
            continue
        scale = min(high / (high - low), gain)
        result.append(tuple(max(0, min(255, round(high - (high - c) * scale))) for c in rgb))
    return tuple(result)


def validate_frame(value):
    if not isinstance(value, list) or len(value) != LEDS:
        raise ValueError('Projection must contain exactly 17 RGB colours')
    if any(not isinstance(rgb, (list, tuple)) or len(rgb) != 3 or
           any(type(c) is not int or not 0 <= c <= 255 for c in rgb) for rgb in value):
        raise ValueError('Invalid source projection colours')
    return tuple(tuple(rgb) for rgb in value)
