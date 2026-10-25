"""Small saved ambience recipes, applied as a reversible in-memory layer."""
import json
import os
import threading
import tempfile
import uuid
from pathlib import Path
from .text import normalized

PROFILE_KEYS = frozenset({
    'light_bar_day_brightness', 'faceplate_brightness', 'night_mode_enabled',
    'home_display', 'game_display', 'customization_pattern', 'customization_speed',
    'customization_colour_count', 'customization_colour_1', 'customization_colour_2',
    'customization_colour_3', 'audio_sync_home_style', 'audio_sync_game_style',
})


class ProfilesCommittedError(OSError):
    committed=True


class Profiles:
    def __init__(self, directory, settings, apply):
        self.path = Path(directory) / 'ambience-profiles.json'
        self.settings, self.apply = settings, apply
        self.lock = threading.RLock()
        self.items, self.active = {}, ''
        try:
            if not self.path.is_symlink() and self.path.stat().st_size < 65536:
                raw = json.loads(self.path.read_text())
                for key, item in raw.get('profiles', {}).items():
                    if len(self.items) >= 20: break
                    if isinstance(item, dict):
                        self.items[str(key)[:36]] = self._clean(item)
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def _clean(self, item):
        name = str(item.get('name', '')).strip()[:32]
        if not name: raise ValueError('Give the profile a name')
        values = item.get('values', {})
        if not isinstance(values, dict) or not values or set(values)-PROFILE_KEYS:
            raise ValueError('Unsupported ambience settings')
        clean = self.settings.validate_overlay(values)
        return {'name': name, 'values': {key: clean[key] for key in values}}

    def _save(self,items):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor,temporary = tempfile.mkstemp(prefix='.ambience-',dir=self.path.parent)
        committed=False
        try:
            with os.fdopen(descriptor, 'w') as stream:
                json.dump({'revision': 1, 'profiles': items}, stream)
                stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,self.path)
            # No fallible operation between the durable commit and RAM adoption.
            self.items=items;committed=True
        finally:
            try:os.unlink(temporary)
            except FileNotFoundError:pass
            except OSError as error:
                if committed:raise ProfilesCommittedError("Profile committed; temporary cleanup failed") from error

    def status(self):
        with self.lock:
            if not self.settings.overlay_active(): self.active = ''
            baseline = self.settings.base_all()
            return {'active': self.active, 'profiles': [{'id': key, **value} for key, value in self.items.items()],
                    'current': {key: baseline[key] for key in PROFILE_KEYS if key in baseline},
                    'temporary': bool(self.active)}

    def save(self, name, values, identifier=''):
        with self.lock:
            if identifier and identifier not in self.items: raise ValueError('Profile not found')
            if not identifier and len(self.items) >= 20: raise ValueError('Up to 20 profiles')
            identifier = identifier or str(uuid.uuid4())
            item = self._clean({'name': name, 'values': values})
            candidate={**self.items,identifier:item}
            self._save(candidate)
            return self.status()

    def delete(self, identifier):
        with self.lock:
            if identifier not in self.items: raise ValueError('Profile not found')
            was_active=identifier == self.active
            if was_active:self.activate('')
            candidate=dict(self.items);del candidate[identifier]
            try:self._save(candidate)
            except BaseException:
                if was_active and identifier in self.items:self.activate(identifier)
                raise
            return self.status()

    def reset(self):
        with self.lock:
            self._save({})
            self.active = ''

    def activate(self, identifier):
        with self.lock:
            if identifier and identifier not in self.items: raise ValueError('Profile not found')
            self.apply(self.items[identifier]['values'] if identifier else {})
            self.active = identifier
            return self.status()

    def named(self, name):
        aliases = {'evening': {'evening', 'night', 'soir', 'soiree', 'nuit'},
                   'day': {'day', 'daytime', 'jour', 'journee'}}
        names = aliases.get(name, {normalized(name)})
        with self.lock:
            matches = [key for key, item in self.items.items() if normalized(item['name']) in names]
            return matches[0] if len(matches) == 1 else None
