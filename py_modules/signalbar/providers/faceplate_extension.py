"""Cached source colour hand-off. No pixels, files or USB read on output()."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from signalbar.models import ProviderOutput, normalize_frame
from signalbar.faceplate.source_projection import REVISION, cache_key, validate_frame, saturate_colours
from signalbar.faceplate.scene_renderer import _renderer_environment

BLACK = ((0, 0, 0),) * 17

class FaceplateExtension:
    def __init__(self, directory, *, builder=None, clock=time.monotonic):
        self.directory = Path(directory)
        self.builder = builder or self._build
        self.clock = clock
        self.condition = threading.Condition()
        self.thread = None
        self.process = None
        self.stopping = False
        self.enabled = False
        self.wanted = None
        self.completed = None
        self.generation = 0
        self.colours = None
        self.adjusted = None
        self.saturation = 100
        self.pending = False
        self.previous = BLACK
        self.ready_at = 0
        self.phase = 'off'
        self.source_kind = ''
        self.configured_source = None
        self.configured_mapping = None
        self.configured_rotate = False
        self.cached_key = None
        self.cached_colours = None

    def configure(self, enabled, source, mapping='bottom', rotate=False, *, saturation=100, pending=False):
        with self.condition:
            if self.stopping:
                return
            self.pending = bool(pending and enabled and source)
            if saturation != self.saturation:
                self.saturation = saturation
                self.adjusted = saturate_colours(self.colours, saturation) if self.colours is not None else None
            if (self.enabled == bool(enabled) and source is self.configured_source
                    and mapping == self.configured_mapping and bool(rotate) == self.configured_rotate):
                return
            self.configured_source = source
            self.configured_mapping = mapping
            self.configured_rotate = bool(rotate)
            wanted = cache_key(source, mapping, rotate) if enabled and source else None
            if self.enabled == bool(enabled) and wanted == (self.wanted or {}).get('key') and self.phase != 'error':
                if source and self.colours is not None:
                    self.display_context = (source.get('context'), source.get('route_appid'))
                return
            self.enabled = bool(enabled)
            self.generation += 1
            # Keep the last displayed palette while a genuine replacement is
            # prepared. Overlay-only refreshes never change the wanted key.
            if not wanted:
                self.previous = BLACK
                self.colours = self.adjusted = None
                self.source_kind = ''
            self.wanted = {'key': wanted, 'source': dict(source), 'mapping': mapping,
                           'rotate': bool(rotate), 'generation': self.generation} if wanted else None
            self.phase = 'preparing' if wanted else 'waiting' if enabled else 'off'
            # An error while preparing another context must not indefinitely
            # display Home's palette as though it belonged to the running game.
            self.foreign_previous = bool(source and self.wanted and self.colours is not None
                and getattr(self, 'display_context', None) != (source.get('context'), source.get('route_appid')))
            if wanted and wanted == self.cached_key and self.cached_colours is not None:
                # Selecting another bar display must not discard the validated
                # original palette. Restore that exact source immediately when
                # reselected, without a decoder, USB write or fade from black.
                self.colours = self.cached_colours
                self.adjusted = saturate_colours(self.colours, self.saturation)
                self.previous = self.adjusted
                self.ready_at = self.clock() - .35
                self.source_kind = source.get('kind', '')
                self.display_context = (source.get('context'), source.get('route_appid'))
                self.foreign_previous = False
                self.completed = self.generation
                self.phase = 'ready'
                self.condition.notify_all()
                return
            if wanted and (self.thread is None or not self.thread.is_alive()):
                self.thread = threading.Thread(target=self._run, name='faceplate-source-projection', daemon=True)
                self.thread.start()
            if self.process is not None:
                try: self.process.terminate()
                except OSError: pass
            self.condition.notify_all()

    def _build(self, request):
        if request['source'].get('kind') == 'artwork-strip':
            # Already decoded on the existing Faceplate worker, not LED loop.
            name = request['mapping'] + ('-rotated' if request['rotate'] else '')
            return validate_frame(request['source']['colours'][name])
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / (request['key'] + '.json')
        try:
            if not target.is_symlink() and target.stat().st_size <= 4096:
                value = json.loads(target.read_text())
                if value.get('revision') == REVISION and value.get('key') == request['key']:
                    return validate_frame(value['colours'])
        except (OSError, ValueError, KeyError, TypeError): pass
        environment = _renderer_environment()
        python = shutil.which('python3', path=environment.get('PATH'))
        if not python: raise RuntimeError('system python3 unavailable')
        worker = Path(__file__).resolve().parents[1] / 'faceplate/projection_process.py'
        command = [python, str(worker)]
        nice = shutil.which('nice', path=environment.get('PATH'))
        if nice: command = [nice, '-n', '10', *command]
        with self.condition:
            if request['generation'] != self.generation or self.stopping: return None
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, env=environment)
            self.process = process
        try:
            output, _ = process.communicate(json.dumps({key: request[key] for key in
                ('source', 'mapping', 'rotate')}).encode(), timeout=15)
            if process.returncode or len(output) > 4096:
                raise ValueError('Source preparation failed')
            value = json.loads(output)
            if not value.get('ok'): raise ValueError('Invalid source background')
            colours = validate_frame(value['colours'])
        finally:
            if process.poll() is None:
                process.kill(); process.communicate()
            with self.condition:
                if self.process is process: self.process = None
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps({'revision': REVISION, 'key': request['key'], 'colours': colours}))
        os.replace(temporary, target)
        # Only our fixed-format generated cache, never artwork or user files.
        files = sorted(self.directory.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[8:]:
            if len(old.stem) == 64 and all(c in '0123456789abcdef' for c in old.stem):
                old.unlink(missing_ok=True)
        return colours

    def _run(self):
        while True:
            with self.condition:
                while not self.stopping and (self.wanted is None or self.completed == self.wanted['generation']):
                    self.condition.wait()
                if self.stopping: return
                request = dict(self.wanted)
            try:
                colours = self.builder(request)
                error = colours is None
                if colours is not None: colours = validate_frame(list(colours))
            except Exception:
                colours = None; error = True
            with self.condition:
                if request['generation'] != self.generation or self.stopping: continue
                if not error:
                    self.previous = self._frame(self.clock())
                    self.colours = colours
                    self.cached_key = request['key']
                    self.cached_colours = colours
                    self.adjusted = saturate_colours(colours, self.saturation)
                    self.source_kind = request['source'].get('kind', '')
                    self.display_context = (request['source'].get('context'), request['source'].get('route_appid'))
                    self.foreign_previous = False
                    self.ready_at = self.clock()
                self.completed = request['generation']
                self.phase = 'error' if error else 'ready'
                if error and getattr(self, 'foreign_previous', False):
                    self.colours = self.adjusted = None
                    self.previous = BLACK
                    self.source_kind = ''
                self.condition.notify_all()

    def _frame(self, now):
        if self.adjusted is None:
            return BLACK
        amount = min(1, max(0, (now - self.ready_at) / .35))
        return tuple(tuple(round(a + (b - a) * amount) for a, b in zip(left, right))
                     for left, right in zip(self.previous, self.adjusted))

    def output(self, now=None):
        with self.condition:
            if not self.enabled: return None
            if self.colours is None:
                return ProviderOutput('faceplate-extension:waiting', normalize_frame(BLACK), 'Original Faceplate background unavailable')
            frame = self._frame(self.clock() if now is None else now)
            return ProviderOutput('faceplate-extension:' + self.source_kind, normalize_frame(frame),
                'Holding the confirmed original background during a refresh' if self.pending
                else 'Stable projection of the original Faceplate background')

    def status(self):
        with self.condition:
            holding = bool(self.colours is not None and (self.pending or self.phase in ('preparing', 'error')))
            return {'phase': 'holding' if self.pending and self.phase == 'ready' else self.phase,
                    'source': self.source_kind, 'stable': True, 'holding': holding,
                    'colours': list(self.adjusted or BLACK)}

    def stop(self, timeout=1):
        with self.condition:
            self.stopping = True; self.enabled = False; self.colours = self.adjusted = None
            self.cached_key = self.cached_colours = None
            if self.process is not None:
                try: self.process.terminate()
                except OSError: pass
            self.condition.notify_all()
            thread = self.thread
        if thread and thread is not threading.current_thread(): thread.join(max(0.0, float(timeout)))
