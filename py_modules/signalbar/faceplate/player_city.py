# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Animated Player City artwork, exact 9-row rail and durable upload cadence."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time
import zlib

from . import gif, protocol
from .player_city_animation import animated_rgb, DELAYS_CS
from signalbar.providers.current_players import MAX_COUNT

REVISION = 'player-city-us-count-smile-10'
ASSET_MANIFEST_SHA256 = '079693a078fc03ccc508b7cd4481aca434d2080414b67ce86f35bb9b13c3fdf0'
ROOT = Path(__file__).resolve().parents[3] / 'assets/faceplate/player-city'
TIERS = ('01_09', '10_99', '100_999', '1000_9999', '10000_99999', '100000_plus')
WEATHER = {'breaks': 'CLR', 'breaks_night': 'CLR', 'cloud': 'CLD', 'cloud_night': 'CLD',
           'rain': 'RAN', 'snow': 'SNW', 'storm': 'STR', 'clear_day': 'SUN', 'clear_night': 'SUN'}
DIGITS = dict(zip('0123456789', (
    ('111','101','101','101','111'), ('010','110','010','010','111'),
    ('111','001','111','100','111'), ('111','001','111','001','111'),
    ('101','101','111','001','001'), ('111','100','111','001','111'),
    ('111','100','111','101','111'), ('111','001','010','010','010'),
    ('111','101','111','101','111'), ('111','101','111','001','111'))))
DIGITS[','] = ('00','00','00','00','01','10')
SMILE = ('0011100','0111110','1101011','1111111','1011101','0100010','0011100')
COUNT_REFRESH_SECONDS = 3600


def population_tier(players):
    if type(players) is not int or not 0 <= players <= MAX_COUNT:
        raise ValueError('Invalid Steam player count')
    if players == 0:
        return None
    return TIERS[min(5, len(str(players))-1)]


def phase_for_weather(weather):
    """Use actual solar boundaries inside the existing dawn/dusk intervals."""
    phase = weather['phase']
    if phase in ('day', 'night'):
        return phase
    if phase not in ('dawn', 'dusk'):
        raise ValueError('Unknown solar phase')
    now, sunrise, sunset = (datetime.fromisoformat(weather[k]) for k in ('now', 'sunrise', 'sunset'))
    return 'day' if sunrise <= now < sunset else 'night'


@lru_cache(maxsize=72)
def native_rgb(code, phase, tier):
    if code not in set(WEATHER.values()) or phase not in ('day','night') or tier not in TIERS:
        raise ValueError('Invalid Player City variant')
    manifest_data = (ROOT/'manifest.json').read_bytes()
    if len(manifest_data) > 131072 or hashlib.sha256(manifest_data).hexdigest() != ASSET_MANIFEST_SHA256:
        raise ValueError('Player City native manifest integrity failure')
    manifest = json.loads(manifest_data)
    row = next(r for r in manifest['image_files'] if (r['weather'],r['phase'],r['tier']) == (code,phase,tier))
    compressed = (ROOT/row['file']).with_suffix('.rgbz').read_bytes()
    if len(compressed) > 65536:
        raise ValueError('Oversized Player City artwork')
    decoder = zlib.decompressobj()
    data = decoder.decompress(compressed, 64*54*3+1)
    if len(data) != 64*54*3 or not decoder.eof or decoder.unused_data or hashlib.sha256(data).hexdigest() != row['rgb_sha256']:
        raise ValueError('Player City artwork integrity failure')
    return data


def rail_layout(players):
    population_tier(players)
    # Explicit US grouping, independent of the SteamOS language/locale.
    text = f'{players:,}'
    # The native comma has two columns and a one-row descender. The shared
    # 3x5 font has no comma; counting its fallback '?' would mis-centre this.
    width = sum(len(DIGITS[c][0]) for c in text) + len(text) - 1
    if width > 64:
        raise ValueError('Player count rail exceeds 64 columns')
    return text, width


@dataclass(frozen=True)
class PlayerCityResult:
    frames: tuple
    signature: str
    delays_cs: tuple = DELAYS_CS

    def gif(self):
        palette, lookup, indexed = [], {}, []
        for frame in self.frames:
            indices = bytearray(64 * 54)
            for pixel, offset in enumerate(range(0, len(frame), 3)):
                colour = frame[offset:offset + 3]
                index = lookup.get(colour)
                if index is None:
                    index = len(palette)
                    if index >= 256:
                        raise ValueError('Player City requires lossless GIF colours')
                    lookup[colour] = index
                    palette.append(tuple(colour))
                indices[pixel] = index
            indexed.append(indices)
        # A full first frame resets every loop. Later full-size frames reuse
        # unchanged pixels through a reserved or unused transparency index.
        # This is lossless: retain every authored frame, colour and delay.
        transparent = len(palette)
        delta = [indexed[0]]
        if transparent < 256:
            palette.append((0, 0, 0))
            delta.extend(bytes(transparent if current == previous else current
                               for current, previous in zip(frame, indexed[n-1]))
                         for n, frame in enumerate(indexed[1:], 1))
        else:
            # All 256 colours remain exact. Each delta can borrow an index
            # absent from its changed pixels; the full first frame is opaque.
            transparency = [None]
            for n, frame in enumerate(indexed[1:], 1):
                changed = {current for current, previous in zip(frame, indexed[n-1]) if current != previous}
                available = next((index for index in range(256) if index not in changed), None)
                transparency.append(available)
                delta.append(frame if available is None else bytes(
                    available if current == previous else current
                    for current, previous in zip(frame, indexed[n-1])))
            transparent = transparency
        payload = gif.encode(64,54,palette,delta,delay_cs=self.delays_cs,loop=True,
                             transparent_index=transparent)
        if len(payload) > protocol.MAX_GIF_BYTES:
            raise ValueError('Player City exceeds the 192 KiB transfer limit')
        return payload


def build_player_city(code, phase, players, *, row=None):
    tier = population_tier(players)
    if tier is None:
        raise ValueError('Zero has no population artwork; preserve the current display')
    from .player_city_row import build_rail, fit_rail_palette
    art = animated_rgb(code,phase,tier)
    rail = fit_rail_palette(art, build_rail(players, row))
    frames = tuple(frame + rail for frame in art)
    digest = hashlib.sha256(REVISION.encode())
    for frame in frames:
        digest.update(frame)
    return PlayerCityResult(frames, digest.hexdigest())


def content_key(payload):
    return ':'.join(str(payload[k]) for k in ('appid','weather','phase','players'))


class PlayerCityCadence:
    """One hourly refresh, with immediate first display, game changes and returns."""
    def __init__(self, path, *, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.lock = threading.RLock()
        self.confirmed = None
        self.attempt = None
        self.row_attempt = None
        self.error = ''
        self.reason = 'waiting'
        self.context = {}
        self._status_cache = {}
        self.next_refresh_at = None
        self.screensaver_refresh_appid = None
        try:
            if self.path.is_symlink() or self.path.stat().st_size > 16384:
                raise ValueError('Invalid Player City journal')
            saved = json.loads(self.path.read_text())
            if not isinstance(saved, dict) or saved.get('schema') != 1:
                raise ValueError('Invalid Player City journal')
            for key in ('confirmed','attempt'):
                row = saved.get(key)
                if row is not None:
                    self._validate(row)
                    setattr(self,key,row)
            if self.attempt and self.attempt.get('outcome') == 'pending':
                self.attempt['outcome'] = 'unconfirmed'
        except FileNotFoundError:
            pass
        except (OSError,ValueError,TypeError,KeyError):
            self.confirmed = self.attempt = None
            self.error = 'journal_unavailable'

    @staticmethod
    def _validate(row):
        if not isinstance(row,dict) or type(row.get('appid')) is not int or not 0 < row['appid'] <= MAX_COUNT:
            raise ValueError('Invalid City identity')
        if row.get('weather') not in set(WEATHER.values()) or row.get('phase') not in ('day','night') or not population_tier(row.get('players')):
            raise ValueError('Invalid City variant')
        for key in ('at','sampled_at'):
            if type(row.get(key)) not in (int,float) or not math.isfinite(row[key]) or row[key] < 0:
                raise ValueError('Invalid City time')

    def _save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,name = tempfile.mkstemp(prefix='.player-city-',dir=self.path.parent)
        try:
            with os.fdopen(fd,'w') as stream:
                json.dump(dict(schema=1,confirmed=self.confirmed,attempt=self.attempt),stream)
                stream.flush();os.fsync(stream.fileno())
            os.replace(name,self.path)
        finally:
            if os.path.exists(name):os.unlink(name)

    def _save_optional(self):
        try:
            self._save()
            self.error = ''
        except OSError:
            # Storage telemetry must never prevent a City image from appearing.
            self.error = 'journal_unavailable'

    def allow_screensaver_refresh(self, appid):
        with self.lock:
            if type(appid) is int and appid > 0:
                self.screensaver_refresh_appid = appid

    def plan(self, appid, sample, weather, *, restore=False):
        with self.lock:
            now = self.clock()
            self.context = dict(appid=appid, sample=dict(sample))
            self.next_refresh_at = None
            if self.screensaver_refresh_appid != appid:
                self.screensaver_refresh_appid = None
            screensaver_refresh = self.screensaver_refresh_appid == appid
            candidate = None
            if sample.get('appid') == appid and sample.get('usable') and sample.get('players',0) > 0 and weather:
                code = WEATHER.get(weather.get('condition'))
                if code:
                    candidate = dict(appid=appid,weather=code,phase=phase_for_weather(weather),
                                     players=sample['players'],sampled_at=sample['sampled_at'])
                    self.context.update(weather=code,phase=candidate['phase'],tier=population_tier(candidate['players']))
            confirmed = self.confirmed
            # Upgrade the already acknowledged picture to the new renderer once,
            # without slipping a newer measurement past the hourly schedule.
            rebuild = bool(confirmed and confirmed['appid'] == appid
                           and confirmed.get('render_revision') != REVISION)
            if rebuild and not restore and not (screensaver_refresh and candidate):
                attempt = self.attempt
                if (attempt and attempt['appid'] == appid and attempt.get('render_revision') == REVISION
                        and attempt.get('outcome') != 'confirmed' and now < attempt['at'] + COUNT_REFRESH_SECONDS):
                    self.next_refresh_at = attempt['at'] + COUNT_REFRESH_SECONDS
                    self.reason = 'cadence'
                    return None
                if candidate and now >= confirmed['at'] + COUNT_REFRESH_SECONDS:
                    # Combine an already-due measurement and the format upgrade
                    # into one GIF rather than restoring then uploading again.
                    self.reason = 'ready'
                    return candidate
            # Restore the last acknowledged City, never a fresh number through a cadence bypass.
            if (restore or rebuild) and confirmed and confirmed['appid'] == appid and not (screensaver_refresh and candidate):
                self.reason = 'restore'
                return {**{k:confirmed[k] for k in ('appid','weather','phase','players','sampled_at')}, '_confirmed_restore': True}
            if candidate:
                same_game = bool(confirmed and confirmed['appid'] == appid)
                changed = not same_game or content_key(candidate) != content_key(confirmed)
                anchor = confirmed['at'] if same_game else None
                attempt = self.attempt
                # Old Lab215/216 quotas/deferred attempts must not survive as
                # a new hourly wait. Only this hourly policy schedules retries.
                if (attempt and attempt['appid'] == appid and attempt.get('policy') == 'hourly-v1'
                        and attempt.get('render_revision') == REVISION
                        and attempt.get('outcome') != 'confirmed' and not restore):
                    anchor = max(anchor or 0, attempt['at'])
                self.next_refresh_at = anchor + COUNT_REFRESH_SECONDS if anchor is not None else None
                due = screensaver_refresh or changed and (self.next_refresh_at is None or now >= self.next_refresh_at)
                if due:
                    self.reason = 'ready'
                    if screensaver_refresh:
                        candidate['_screensaver_refresh'] = True
                    return candidate
                self.reason = 'unchanged' if not changed else 'cadence'
            else:
                self.reason = 'zero' if sample.get('state') == 'zero' else 'weather_unavailable' if sample.get('usable') else sample.get('state','waiting')
            return None

    def plan_row(self, appid, row, *, replace=False):
        """Refresh visible rail facts against ACKed content, never a fresh count."""
        with self.lock:
            confirmed = self.confirmed
            if not confirmed or confirmed['appid'] != appid or confirmed.get('render_revision') != REVISION:
                return None
            pending = self.row_attempt
            same_attempt = bool(pending and pending['row'] == row and pending['appid'] == appid)
            if not replace:
                if same_attempt and (pending['outcome'] == 'pending' or self.clock() < pending['at'] + 60):
                    return None
                retrying = same_attempt and pending['outcome'] != 'confirmed'
                if confirmed.get('row') == row and not retrying:
                    return None
            return {**{k:confirmed[k] for k in ('appid','weather','phase','players','sampled_at')},
                    'row':copy.deepcopy(row), '_row_refresh':True}

    def reserve(self, payload):
        with self.lock:
            if payload.get('_row_refresh'):
                self.row_attempt = dict(appid=payload['appid'], key=content_key(payload),
                    row=copy.deepcopy(payload.get('row', {})), at=self.clock(), outcome='pending')
                return
            self.row_attempt = None
            row = {k:payload[k] for k in ('appid','weather','phase','players','sampled_at')}
            row['row'] = copy.deepcopy(payload.get('row', {}))
            row.update(at=self.clock(),outcome='pending',policy='hourly-v1',render_revision=REVISION)
            self._validate(row)
            self.attempt = row
            if payload.get('_screensaver_refresh'):
                self.screensaver_refresh_appid = None
            self._save_optional()

    def receipt(self, payload, result):
        with self.lock:
            if payload.get('_row_refresh'):
                attempt = self.row_attempt
                if not attempt or attempt['key'] != content_key(payload) or attempt['row'] != payload.get('row'):
                    return
                success = bool(result.get('synchronized') and not result.get('error') and not result.get('superseded'))
                attempt['outcome'] = 'confirmed' if success else 'failed'
                if success and self.confirmed and content_key(self.confirmed) == attempt['key']:
                    self.confirmed.update(row=copy.deepcopy(payload['row']), last_ack_at=self.clock())
                    self._save_optional()
                return
            if not self.attempt or content_key(self.attempt) != content_key(payload):
                return
            outcome = ('confirmed' if result.get('synchronized') and not result.get('error')
                       else 'deferred' if result.get('deferred') else 'unconfirmed' if result.get('sent_unconfirmed') else 'failed')
            self.attempt['outcome'] = outcome
            if outcome == 'confirmed':
                # Re-acknowledging the same picture must not postpone the next
                # numeric update after every screensaver/assistant interruption.
                prior = self.confirmed
                self.attempt['restoration'] = bool(prior and content_key(prior) == content_key(payload))
                content_at = prior['at'] if prior and content_key(prior) == content_key(payload) else self.clock()
                self.confirmed = {**self.attempt,'at':content_at,'last_ack_at':self.clock()}
            self.reason = outcome
            self._save_optional()

    def status(self, sample=None):
        # A UI status read never waits for cadence-journal fsync in the worker.
        if not self.lock.acquire(blocking=False):
            value = copy.deepcopy(self._status_cache)
            if sample is not None:value['sample'] = sample
            return value
        try:
            value = dict(self.context)
            if sample is not None:value['sample'] = sample
            result = {**value,'reason':self.reason, 'storage_error':self.error,
                    'next_refresh_s':round(max(0.,self.next_refresh_at-self.clock())) if self.next_refresh_at is not None else None,
                    'displayed':dict(self.confirmed) if self.confirmed else None,
                    'display_age_s':round(max(0.,self.clock()-self.confirmed['at'])) if self.confirmed else None,
                    'last_attempt':dict(self.attempt) if self.attempt else None,
                    'count_refresh_seconds':COUNT_REFRESH_SECONDS}
            self._status_cache = result
            return copy.deepcopy(result)
        finally:
            self.lock.release()
