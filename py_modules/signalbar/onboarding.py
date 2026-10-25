"""Bounded setup draft, never an alternative active configuration or secret store."""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile
import threading
import stat
import errno

STEPS = {'ambiance', 'brightness', 'assistant', 'voice', 'faceplate', 'services', 'review'}
KEYS = {'step', 'preset', 'brightness', 'night', 'night_percentage', 'city',
        'assistant_requested', 'assistant_confirmed', 'faceplate_requested', 'home', 'game'}


class DraftError(ValueError):
    """Finite, non-sensitive reason; never expose draft contents or paths."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def draft_error_code(error):
    if isinstance(error, DraftError):
        return error.code
    if isinstance(error, OSError):
        if error.errno in {errno.EACCES, errno.EPERM, errno.EROFS}:
            return 'draft_permissions'
        return 'draft_io'
    if isinstance(error.__cause__, OSError):
        return draft_error_code(error.__cause__)
    return 'draft_invalid'


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate setup field')
        result[key] = value
    return result


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

def clean_draft(value):
    if not isinstance(value, dict) or set(value) - KEYS:
        raise ValueError('Unsupported setup fields')
    if len(json.dumps(value, allow_nan=False).encode()) > 8192:
        raise ValueError('Setup draft too large')
    result = {}
    for key, item in value.items():
        if key in {'step', 'preset', 'home', 'game'} and not isinstance(item, str):
            raise ValueError('Invalid setup selection')
        if key == 'step':
            if item not in STEPS: raise ValueError('Invalid setup step')
        elif key == 'preset':
            if item not in {'custom', 'moderate', 'atmosphere', 'signals', 'immersive'}: raise ValueError('Invalid experience')
        elif key in {'brightness', 'night_percentage'}:
            if type(item) is not int or not 1 <= item <= (255 if key == 'brightness' else 100):
                raise ValueError('Invalid brightness')
        elif key in {'night', 'assistant_requested', 'assistant_confirmed', 'faceplate_requested'}:
            if type(item) is not bool and not (item is None and key.endswith('_requested')):
                raise ValueError('Invalid setup choice')
        elif key == 'home':
            if item not in {'dashboard', 'weather', 'native-clock', 'artwork', 'artwork-dashboard'}: raise ValueError('Invalid Home display')
        elif key == 'game':
            if item not in {'artwork', 'dashboard', 'artwork-dashboard', 'weather', 'player-city', 'keep'}: raise ValueError('Invalid game display')
        elif key == 'city':
            if item is not None:
                from signalbar.settings.store import _valid_weather_location
                item = _valid_weather_location(item)
                if item is None: raise ValueError('Choose a valid city')
        result[key] = item
    return result

class OnboardingDraft:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self._transient = None
        self.storage_error = ''
        self.recovery_code = ''

    def resume(self):
        """A disposable progress file must never veto first-time setup.

        Strict reads still reject foreign files, links and special objects. On
        failure start fresh, then try an atomic replacement of the directory
        entry (never its target). If storage cannot be repaired, keep progress
        in memory until the backend exits. Active settings use their separate
        validated commit transaction and are never affected by this recovery.
        """
        with self.lock:
            if self._transient is not None:
                return dict(self._transient)
            try:
                return self.read()
            except (OSError, ValueError) as error:
                code = draft_error_code(error)
                self.restart()
                self.recovery_code = code
                return {}

    def remember(self, changes):
        with self.lock:
            value = clean_draft({**self.resume(), **clean_draft(changes)})
            self._persist_or_remember(value)
            return dict(value)

    def _persist_or_remember(self, value):
        self._transient = dict(value)
        try:
            self._write(value)
        except (OSError, ValueError) as error:
            self.storage_error = draft_error_code(error)
        else:
            self._transient = None
            self.storage_error = ''

    def restart(self):
        with self.lock:
            # Archives are useful, but neither their capacity nor an unexpected
            # owner/type may turn this disposable draft into a recovery gate.
            try:
                self.reset()
            except (OSError, ValueError) as error:
                self.storage_error = draft_error_code(error)
            self._persist_or_remember({})

    def discard(self):
        with self.lock:
            try:
                self.clear()
            except (OSError, ValueError):
                # Persist the empty draft where possible. Otherwise shadow the
                # inaccessible entry; never recurse into a foreign directory.
                self._persist_or_remember({})
            else:
                self._transient = None
                self.storage_error = ''
            self.recovery_code = ''

    def read(self):
        with self.lock:
            try:
                descriptor = os.open(self.path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
                                     | getattr(os, 'O_NONBLOCK', 0))
            except FileNotFoundError:
                if self.path.is_symlink(): raise DraftError('draft_unsafe')
                return {}
            except OSError as error:
                if error.errno == errno.ELOOP: raise DraftError('draft_unsafe') from error
                raise ValueError('Setup draft unavailable') from error
            try:
                with os.fdopen(descriptor, 'rb') as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
                        raise DraftError('draft_unsafe')
                    if info.st_size > 12288: raise DraftError('draft_too_large')
                    raw = stream.read(12289)
                if len(raw) > 12288:
                    raise DraftError('draft_too_large')
                stored = json.loads(raw, object_pairs_hook=_unique_pairs,
                    parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid setup number')))
                if not isinstance(stored, dict) or type(stored.get('schema')) is not int or stored['schema'] != 1:
                    raise DraftError('draft_schema')
                return clean_draft(stored.get('draft', {}))
            except (OSError, TypeError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
                raise ValueError('Setup draft unavailable') from error

    def save(self, changes):
        with self.lock:
            value = clean_draft({**self.read(), **clean_draft(changes)})
            self._write(value)
            return value

    def _write(self, value):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # replace operates on the entry itself, including a stale symlink.
            # A directory or unwritable parent fails into the memory draft.
            descriptor, name = tempfile.mkstemp(prefix='.setup-', suffix='.tmp', dir=self.path.parent)
            try:
                with os.fdopen(descriptor, 'w') as target:
                    json.dump({'schema': 1, 'draft': value}, target, allow_nan=False)
                    target.flush(); os.fsync(target.fileno())
                os.replace(name, self.path)
                _sync_directory(self.path.parent)
            finally:
                Path(name).unlink(missing_ok=True)

    def clear(self):
        with self.lock:
            if self.path.is_symlink(): raise ValueError('Unsafe setup draft')
            self.path.unlink(missing_ok=True)
            if self.path.parent.is_dir(): _sync_directory(self.path.parent)

    def reset(self):
        """Explicit, non-overwriting recovery of one owned draft.

        Keep 64 bounded backup slots. A prior backup must not block the second
        recovery. If a crash left source and our archive hard-linked, finish
        that same archive rather than rejecting its expected second link.
        """
        with self.lock:
            try:
                info = self.path.lstat()
            except FileNotFoundError:
                return False
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_nlink not in {1, 2}):
                raise DraftError('draft_unsafe')
            identity = (info.st_ino, info.st_dev)
            for slot in range(64):
                archive = self.path.with_name(self.path.name + '.invalid' + (f'.{slot}' if slot else ''))
                try:
                    archived = archive.lstat()
                except FileNotFoundError:
                    # Do not archive an unexpected hard-linked source.
                    if info.st_nlink != 1: continue
                    try:
                        os.link(self.path, archive, follow_symlinks=False)
                    except FileExistsError:
                        continue  # An exclusive destination raced us; never replace it.
                    archived = archive.lstat()
                else:
                    if (archived.st_ino, archived.st_dev) != identity: continue
                if (not stat.S_ISREG(archived.st_mode) or archived.st_uid != os.geteuid()
                        or (archived.st_ino, archived.st_dev) != identity):
                    raise DraftError('draft_unsafe')
                break
            else:
                raise DraftError('draft_unsafe' if info.st_nlink != 1 else 'draft_archive_full')
            # Persist the backup before unlinking the source. A failed fsync
            # leaves a recoverable same-inode pair for the next explicit retry.
            _sync_directory(self.path.parent)
            current = self.path.lstat()
            if (current.st_ino, current.st_dev) != identity or current.st_nlink != 2:
                raise DraftError('draft_unsafe')
            self.path.unlink()
            _sync_directory(self.path.parent)
            return True


class OnboardingTransaction:
    """Small write-ahead journal for two existing preference stores, no secrets.

    Only changed, schema-approved SettingsStore fields are retained. Nothing
    copies update credentials, API keys, media or the whole configuration.
    """
    MAX_BYTES = 262144

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()

    def _read(self):
        try:
            descriptor = os.open(self.path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        except FileNotFoundError:
            if self.path.is_symlink(): raise ValueError('Unsafe setup transaction')
            return None
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_size > self.MAX_BYTES:
                raise ValueError('Setup transaction unavailable')
            raw = stream.read(self.MAX_BYTES+1)
        if len(raw) > self.MAX_BYTES: raise ValueError('Setup transaction too large')
        try:
            value = json.loads(raw, object_pairs_hook=_unique_pairs,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid setup number')))
        except (UnicodeError, RecursionError, TypeError) as error:
            raise ValueError('Setup transaction unavailable') from error
        fields = {'schema', 'stage', 'before_settings', 'after_settings', 'before_routes', 'after_routes'}
        if (not isinstance(value, dict) or set(value) != fields
                or type(value['schema']) is not int or value['schema'] != 1
                or value['stage'] not in {'prepared', 'committed'}):
            raise ValueError('Invalid setup transaction')
        from signalbar.settings.store import DEFAULTS
        before, after = value['before_settings'], value['after_settings']
        if (not isinstance(before, dict) or not isinstance(after, dict)
                or set(before) != set(after) or set(before)-set(DEFAULTS)):
            raise ValueError('Unsupported setup transaction fields')
        for name in ('before_routes', 'after_routes'):
            routes = value[name]
            if not isinstance(routes, dict) or set(routes) != {'home', 'game'}:
                raise ValueError('Invalid setup routes')
            clean_draft({'home': routes['home'], 'game': routes['game']})
        return value

    def _write(self, value):
        encoded = json.dumps(value, allow_nan=False, separators=(',', ':')).encode()
        if len(encoded) > self.MAX_BYTES: raise ValueError('Setup transaction too large')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink(): raise ValueError('Unsafe setup transaction')
        descriptor, name = tempfile.mkstemp(prefix='.setup-transaction-', dir=self.path.parent)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(encoded); stream.flush(); os.fsync(stream.fileno())
            os.replace(name, self.path)
            _sync_directory(self.path.parent)
        finally:
            Path(name).unlink(missing_ok=True)

    def prepare(self, before_settings, after_settings, before_routes, after_routes):
        with self.lock:
            if self._read() is not None: raise ValueError('A setup recovery is pending')
            value = dict(schema=1, stage='prepared', before_settings=before_settings,
                         after_settings=after_settings, before_routes=before_routes, after_routes=after_routes)
            self._write(value)
            return value

    def committed(self):
        with self.lock:
            value = self._read()
            if value is None: raise ValueError('Setup transaction missing')
            value['stage'] = 'committed'
            self._write(value)

    def clear(self):
        with self.lock:
            if self.path.is_symlink(): raise ValueError('Unsafe setup transaction')
            self.path.unlink(missing_ok=True)
            if self.path.parent.is_dir(): _sync_directory(self.path.parent)

    def recover(self, settings, preferences):
        with self.lock, settings._lock:
            value = self._read()
            if value is None: return False
            if value['stage'] == 'prepared':
                current = preferences.read()
                routes = {'home': current.home_scene, 'game': current.game_scene}
                if routes not in (value['before_routes'], value['after_routes']):
                    raise ValueError('Setup recovery conflicts with newer display routes')
                settings.restore_transaction_fields(value['before_settings'], value['after_settings'])
                if routes != value['before_routes']:
                    preferences.update(home_scene=value['before_routes']['home'],
                        game_scene=value['before_routes']['game'], expected_revision=current.revision)
            self.clear()
            return value['stage']
