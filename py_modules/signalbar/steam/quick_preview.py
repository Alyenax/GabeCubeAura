"""Small read-only static Decky thumbnails; never prepare or submit LED palettes."""
import base64
from collections import OrderedDict
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from .artwork_cache import get_library_artwork, find_library_artwork
from signalbar.faceplate.scene_renderer import _renderer_environment

_cache = OrderedDict()
_lock = threading.Lock()
MAX_PREVIEW_BYTES = 128 * 1024
_last_diagnostic = {'error': '', 'worker_exit': None}


def quick_preview_diagnostic():
    return dict(_last_diagnostic)


def get_quick_artwork(appid, source='hero'):
    if type(appid) is not int or not 0 < appid < 2**32:
        return {'found': False, 'appid': 0}
    source = source if source in ('hero', 'header', 'capsule') else 'hero'
    # Another cached Steam format is preferable to an empty panel. No network
    # downloads or faceplate preparation. All format fallbacks share a single
    # four-second budget, including cache lock wait, rather than 3 x 4 seconds.
    deadline = time.monotonic() + 4
    for candidate in dict.fromkeys((source, 'hero', 'header', 'capsule')):
        metadata = get_library_artwork(appid, candidate, include_data=False)
        if metadata.get('found'):
            result = _thumbnail(appid, candidate, metadata, deadline)
            if result.get('found'):
                return result
        if time.monotonic() >= deadline:
            break
    return {'found': False, 'appid': appid, 'source': source}


def _thumbnail(appid, source, metadata, deadline):
    path = find_library_artwork(appid, source)
    if path is None: return {**metadata, 'found': False}
    key = (str(path), metadata['fingerprint'])
    # One bounded one-shot process even if two panel instances request it.
    if not _lock.acquire(timeout=max(0, deadline - time.monotonic())):
        return {**metadata, 'found': False}
    try:
        if key in _cache:
            _cache.move_to_end(key)
            return {**metadata, 'data_uri': _cache[key], 'mime': 'image/jpeg'}
        _last_diagnostic.update(error='', worker_exit=None)
        environment = _renderer_environment()
        environment['OMP_NUM_THREADS'] = '1'
        python = shutil.which('python3', path=environment.get('PATH'))
        if not python:
            _last_diagnostic['error'] = 'python-unavailable'
            return {**metadata, 'found': False}
        argv = [python, str(Path(__file__).with_name('quick_preview_process.py')), os.fspath(path)]
        nice = shutil.which('nice', path=environment.get('PATH'))
        if nice: argv = [nice, '-n', '10', *argv]
        remaining = deadline - time.monotonic()
        if remaining <= 0: return {**metadata, 'found': False}
        try:
            result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, env=environment, timeout=remaining, check=False)
        except (OSError, subprocess.TimeoutExpired):
            _last_diagnostic['error'] = 'worker-failed-or-timed-out'
            return {**metadata, 'found': False}
        if result.returncode or not 0 < len(result.stdout) <= MAX_PREVIEW_BYTES:
            _last_diagnostic.update(error='decoder-unavailable' if result.returncode == 2 else 'decode-failed',
                                    worker_exit=result.returncode)
            return {**metadata, 'found': False}
        data_uri = 'data:image/jpeg;base64,' + base64.b64encode(result.stdout).decode('ascii')
        _cache[key] = data_uri
        while len(_cache) > 4: _cache.popitem(last=False)
        return {**metadata, 'data_uri': data_uri, 'mime': 'image/jpeg'}
    finally:
        _lock.release()
