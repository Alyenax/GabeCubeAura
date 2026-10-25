"""Bounded, read-only personal statistics from Steam's local account caches."""
from pathlib import Path
import json
import re
import threading
import time

from .artwork_cache import steam_roots

MAX_BYTES = 4 * 1024 * 1024
TOKEN = re.compile(r'\s+|//[^\n]*|"((?:\\.|[^"\\])*)"|([{}])')


def parse_vdf(text):
    """Only Steam's quoted KeyValues grammar; reject partial/malformed input."""
    tokens, offset = [], 0
    for match in TOKEN.finditer(text):
        if match.start() != offset:
            raise ValueError('Invalid KeyValues')
        offset = match.end()
        if match.group(1) is not None:
            tokens.append(('text', re.sub(r'\\([\\"])', r'\1', match.group(1))))
        elif match.group(2):
            tokens.append((match.group(2), ''))
        if len(tokens) > 250000:
            raise ValueError('Too many KeyValues')
    if offset != len(text):
        raise ValueError('Incomplete KeyValues')
    cursor = 0

    def obj(depth=0):
        nonlocal cursor
        if depth > 32:
            raise ValueError('KeyValues nesting')
        result = {}
        while cursor < len(tokens) and tokens[cursor][0] != '}':
            kind, key = tokens[cursor]; cursor += 1
            if kind != 'text' or cursor >= len(tokens):
                raise ValueError('Invalid KeyValues pair')
            kind, value = tokens[cursor]; cursor += 1
            if kind == '{':
                value = obj(depth + 1)
                if cursor >= len(tokens) or tokens[cursor][0] != '}':
                    raise ValueError('Unclosed KeyValues')
                cursor += 1
            elif kind != 'text':
                raise ValueError('Missing KeyValues value')
            result[key.lower()] = value
        return result

    result = obj()
    if cursor != len(tokens):
        raise ValueError('Trailing KeyValues')
    return result


def _read(path, maximum=MAX_BYTES):
    with Path(path).open('rb') as handle:
        data = handle.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError('Oversized Steam cache')
    return data.decode('utf-8-sig')


def achievement_counts(text):
    rows = json.loads(text)
    if not isinstance(rows, list):
        raise ValueError('Unsupported library cache')
    entries = [row[1] for row in rows if isinstance(row, list) and len(row) == 2
               and row[0] == 'achievements' and isinstance(row[1], dict)]
    if len(entries) != 1:
        raise ValueError('Unsupported achievements cache')
    data = entries[0].get('data', {})
    if not isinstance(data, dict):
        raise ValueError('Invalid achievements')
    done, total = data.get('nAchieved'), data.get('nTotal')
    if type(done) is not int or type(total) is not int or not 0 <= done <= total <= 100000:
        raise ValueError('Invalid achievement counts')
    return done, total


class DashboardStats:
    def __init__(self, roots=steam_roots, clock=time.time, monotonic=time.monotonic):
        self.roots, self.clock, self.monotonic = roots, clock, monotonic
        self._cache = {}
        self._lock = threading.Lock()
        self._worker = None
        self._stopped = False
        self._live = None
        self._session_appid = 0
        self._total_anchor = None
        self._total_account = None
        self._revision = 0

    def select_game(self, appid):
        with self._lock:
            if appid != self._session_appid:
                self._session_appid = appid
                self._total_anchor = None
                self._total_account = None
                self._live = None

    def invalidate(self, appid):
        # A real achievement prompts the local fallback to reread now, even
        # when light-event animations are disabled. In-flight old reads cannot
        # replace that newer request. No file IO happens on the event thread.
        with self._lock:
            self._revision += 1
            self._cache = {key:(min(value[0],self.clock()-301),value[1]) if key[-1]==appid else value for key,value in self._cache.items()}

    def _with_total(self, appid, result):
        result=dict(result)
        total=result.get('total_minutes')
        if type(total) is not int:return result
        with self._lock:
            if appid!=self._session_appid or self._stopped:return result
            now=self.monotonic()
            if self._total_anchor is None:self._total_anchor=(total,now,total)
            baseline,started,previous=self._total_anchor
            # The Steam lifetime total may stay frozen until exit. Add only
            # complete observed hours to the original baseline, then take the
            # higher Steam sample: never add session time to an updated total.
            projected=baseline+max(0,int((now-started)//3600))*60
            if total>max(previous,projected):baseline,started=total,now
            result['total_minutes']=min(9999999999,max(previous,total,projected))
            self._total_anchor=(baseline,started,result['total_minutes'])
        return result

    def start(self):
        with self._lock:
            self._stopped = False

    def _identity(self):
        for root in self.roots():
            try:
                path = Path(root) / 'config/loginusers.vdf'
                if path.stat().st_size > 128 * 1024:
                    continue
                users = parse_vdf(_read(path, 128 * 1024)).get('users', {})
                accounts = {sid: row for sid, row in users.items()
                            if re.fullmatch(r'\d{16,20}', sid) and isinstance(row, dict)}
                for flag in ('mostrecent', 'autologin'):
                    active = [sid for sid,row in accounts.items() if row.get(flag) == '1']
                    if len(active) == 1:
                        return str(root), str(int(active[0]) & 0xffffffff)
                    if active:
                        return None  # Conflicting explicit identities are never guessed.
            except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
                continue
        return None

    def clear_live(self):
        with self._lock:
            self._live = None

    def update_live(self, appid, values):
        if type(appid) is not int or not 0 < appid < 2**32 or not isinstance(values, dict):
            return False
        data = {}
        total = values.get('total_minutes')
        if type(total) is int and 0 <= total <= 9999999999:
            data['total_minutes'] = total
        done, count = values.get('achieved'), values.get('achievements_total')
        if type(done) is int and type(count) is int and 0 <= done <= count <= 100000:
            data.update(achieved=done, achievements_total=count)
        with self._lock:
            if self._stopped:
                return False
            self._live = (appid, self.clock(), data)
        return True

    def _live_for(self, appid):
        with self._lock:
            live = self._live
            return dict(live[2]) if live and live[0] == appid and 0 <= self.clock()-live[1] < 45 else {}

    def snapshot(self, appid):
        if type(appid) is not int or not 0 < appid < 2**32:
            return {}
        native = self._live_for(appid)
        if len(native) == 3:
            return self._with_total(appid,native)
        account = self._identity()
        if account is None:
            return self._with_total(appid,native)
        key = (*account, appid)
        with self._lock:
            if self._total_account is not None and self._total_account!=account:self._total_anchor=None
            self._total_account=account
            cached = self._cache.get(key)
            age = self.clock() - cached[0] if cached else 301
            if not self._stopped and not (self._worker and self._worker.is_alive()) and not 0 <= age < 300:
                self._worker = threading.Thread(target=self._load, args=(appid, key, self._revision),
                                                name='dashboard-local-stats', daemon=True)
                self._worker.start()
            # A game/account switch never returns the previous player's data.
            result = dict(cached[1]) if cached and 0 <= age < 600 else {}
            result.update(native)
        return self._with_total(appid,result)

    def _load(self, appid, key, revision):
        result = self.read(appid, key[:2])
        with self._lock:
            if not self._stopped and revision==self._revision:
                self._cache = {key: (self.clock(), result)}

    def stop(self, timeout=0.5):
        with self._lock:
            self._stopped = True
            worker = self._worker
            self._cache.clear()
            self._live = None
            self._session_appid = 0
            self._total_anchor = None
            self._total_account = None
            self._revision += 1
        if worker:
            worker.join(timeout=max(0, timeout or 0))

    def read(self, appid, identity=None):
        now = self.clock()
        identity = identity or self._identity()
        if identity and type(appid) is int and 0 < appid < 2**32:
            root, account = identity
            base = Path(root) / 'userdata' / account / 'config'
            result = {}
            try:
                data = parse_vdf(_read(base / 'localconfig.vdf'))
                for part in ('userlocalconfigstore', 'software', 'valve', 'steam', 'apps', str(appid)):
                    data = data.get(part, {}) if isinstance(data, dict) else {}
                value = data.get('playtime') if isinstance(data, dict) else None
                if isinstance(value, str) and re.fullmatch(r'\d{1,10}', value):
                    # Last total recorded by Steam. Never add our observed session.
                    result['total_minutes'] = int(value)
            except (OSError, UnicodeError, ValueError, TypeError):
                pass
            try:
                path = base / 'librarycache' / f'{appid}.json'
                age = now - path.stat().st_mtime
                if age < -300:
                    raise ValueError('Future achievements cache')
                # A cache can remain valid for months when Steam has not
                # revisited that game. Retain the last known exact counters.
                done, total = achievement_counts(_read(path))
                result.update(achieved=done, achievements_total=total)
            except (OSError, UnicodeError, ValueError, TypeError):
                pass
            # Store no account identifiers in renderer facts or diagnostics.
            return dict(result)
        return {}
