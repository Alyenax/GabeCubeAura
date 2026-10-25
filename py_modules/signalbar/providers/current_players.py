"""Opt-in official Steam player counts. One bounded network worker, no USB."""
from __future__ import annotations

import json
import socket
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from uuid import uuid4

REFRESH_SECONDS = 300
MAX_AGE_SECONDS = 900
MAX_COUNT = 0xffffffff


class PlayerCountError(ValueError):
    def __init__(self, state, code=''):
        self.state = state
        self.code = code or state
        super().__init__(state)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def validate_response(payload):
    result = payload.get('response') if isinstance(payload, dict) else None
    if (not isinstance(result, dict) or type(result.get('result')) is not int
            or result['result'] != 1 or type(result.get('player_count')) is not int
            or not 0 <= result['player_count'] <= MAX_COUNT):
        raise PlayerCountError('unavailable')
    return result['player_count']


def fetch_current_players(appid):
    if type(appid) is not int or not 0 < appid <= MAX_COUNT:
        raise PlayerCountError('unavailable')
    url = f'https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid={appid}'
    try:
        with build_opener(NoRedirect()).open(Request(url, headers={
                'Accept': 'application/json', 'User-Agent': 'GabeCubeAura Player City'}), timeout=6) as response:
            data = response.read(8193)
        if len(data) > 8192:
            raise PlayerCountError('unavailable')
        return validate_response(json.loads(data))
    except PlayerCountError:
        raise
    except HTTPError as error:
        raise PlayerCountError('unavailable', f'http_{error.code}') from None
    except (URLError, TimeoutError, OSError) as error:
        reason = getattr(error, 'reason', error)
        code = 'dns' if isinstance(reason, socket.gaierror) else 'timeout' if isinstance(reason, (TimeoutError, socket.timeout)) else 'connection'
        raise PlayerCountError('network_error', code) from None
    except (ValueError, TypeError):
        raise PlayerCountError('unavailable') from None


class CurrentPlayers:
    def __init__(self, fetch=fetch_current_players, *, clock=time.monotonic, wall_clock=time.time, transport='python'):
        self.fetch, self.clock, self.wall_clock = fetch, clock, wall_clock
        self.condition = threading.Condition()
        self.appid = 0
        self.generation = 0
        self.closed = False
        self.thread = None
        self.in_flight = False
        self.cache = {}
        self.next_at = 0.
        self.state = 'inactive'
        self.error_code = ''
        self.transport = transport
        self.native_request = None

    def configure(self, appid, *, start=True):
        appid = appid if type(appid) is int and 0 < appid <= MAX_COUNT else 0
        with self.condition:
            if self.closed:
                return
            if appid != self.appid:
                self.appid, self.generation = appid, self.generation + 1
                cached = self.cache.get(appid)
                fresh = cached and 0 <= self.clock() - cached['sampled_mono'] < REFRESH_SECONDS
                self.next_at = cached['sampled_mono'] + REFRESH_SECONDS if fresh else self.clock()
                self.state = ('zero' if cached['players'] == 0 else 'ready') if fresh else 'waiting' if appid else 'inactive'
                self.error_code = ''
                self.condition.notify_all()
            if self.transport == 'python' and appid and start and self.thread is None:
                self.thread = threading.Thread(target=self._run, name='gca-current-players', daemon=True)
                self.thread.start()

    def claim(self):
        """Lease one Decky fetch; the backend remains the sole polling owner."""
        with self.condition:
            now = self.clock()
            if self.native_request and now >= self.native_request['expires_at']:
                expired = self.native_request
                self.native_request = None
                self.in_flight = False
                if expired['appid'] == self.appid and expired['generation'] == self.generation:
                    self.state, self.error_code = 'network_error', 'timeout'
            if self.closed or self.transport != 'decky' or not self.appid or self.in_flight or now < self.next_at:
                return None
            request = dict(request_id=uuid4().hex, appid=self.appid, generation=self.generation, expires_at=now+30)
            self.native_request = request
            self.in_flight = True
            # Reserve the polling interval before returning the lease. A lost
            # frontend/RPC cannot turn every two-second runtime tick into HTTP.
            self.next_at = now + REFRESH_SECONDS
            return {k:request[k] for k in ('request_id', 'appid')}

    def complete(self, request_id, appid, payload=None, error_code=''):
        with self.condition:
            request = self.native_request
            if not request or type(appid) is not int or request_id != request['request_id'] or appid != request['appid']:
                return False
            self.native_request = None
            self.in_flight = False
            self.condition.notify_all()
            if (self.closed or self.appid != appid or request['generation'] != self.generation
                    or self.clock() >= request['expires_at']):
                return False
            if error_code:
                if not isinstance(error_code, str):
                    error_code = 'connection'
                safe = error_code if error_code in {'timeout','connection','cancelled','response_invalid','response_too_large'} or (error_code.startswith('http_') and error_code[5:].isdigit() and 100 <= int(error_code[5:]) <= 599) else 'connection'
                self.error_code = safe
                self.state = 'network_error' if safe in {'timeout','connection','cancelled'} else 'unavailable'
                return True
            try:
                value = validate_response(payload)
            except PlayerCountError:
                self.state, self.error_code = 'unavailable', 'response_invalid'
                return True
            self.cache[appid] = dict(players=value, sampled_at=self.wall_clock(), sampled_mono=self.clock())
            if len(self.cache) > 16:
                self.cache.pop(next(iter(self.cache)))
            self.state, self.error_code = ('zero' if value == 0 else 'ready'), ''
            return True

    def poll(self):
        """A single generation-fenced poll; also used by deterministic tests."""
        with self.condition:
            if self.closed or self.transport != 'python' or not self.appid or self.in_flight or self.clock() < self.next_at:
                return False
            appid, generation = self.appid, self.generation
            self.in_flight = True
        value, error, code = None, '', ''
        try:
            value = self.fetch(appid)
            if type(value) is not int or not 0 <= value <= MAX_COUNT:
                raise PlayerCountError('unavailable')
        except PlayerCountError as caught:
            error = caught.state
            code = caught.code
        except Exception:
            error = 'unavailable'  # Never expose network exception text/URLs.
            code = 'unexpected_response'
        with self.condition:
            self.in_flight = False
            if not self.closed and self.appid == appid and self.generation == generation:
                self.next_at = self.clock() + REFRESH_SECONDS
                self.state = error or ('zero' if value == 0 else 'ready')
                self.error_code = code
                if not error:
                    self.cache[appid] = dict(players=value, sampled_at=self.wall_clock(), sampled_mono=self.clock())
                    if len(self.cache) > 16:
                        self.cache.pop(next(iter(self.cache)))
            self.condition.notify_all()
        return True

    def _run(self):
        while True:
            with self.condition:
                if self.closed:
                    return
                delay = self.next_at - self.clock() if self.appid else 300
                if not self.appid or self.in_flight or delay > 0:
                    self.condition.wait(timeout=max(.05, min(300, delay if self.appid else 300)))
                    continue
            self.poll()

    def status(self):
        with self.condition:
            value = self.cache.get(self.appid, {}) if self.appid else {}
            age = max(0., self.clock() - value['sampled_mono']) if value else None
            state = self.state
            if state in ('ready', 'zero') and (age is None or age > MAX_AGE_SECONDS):
                state = 'stale'
            return dict(appid=self.appid, state=state, players=value.get('players'),
                        transport=self.transport,
                        error_code=self.error_code,
                        sampled_at=value.get('sampled_at'), sample_age_s=round(age, 1) if age is not None else None,
                        usable=state in ('ready', 'zero'), in_flight=self.in_flight,
                        next_poll_s=round(max(0., self.next_at-self.clock()), 1) if self.appid else None)

    def stop(self, timeout=.5):
        with self.condition:
            self.closed = True
            self.appid, self.state = 0, 'inactive'
            self.error_code = ''
            self.native_request = None
            self.in_flight = False
            self.generation += 1
            self.condition.notify_all()
        if self.thread:
            self.thread.join(timeout=timeout)
