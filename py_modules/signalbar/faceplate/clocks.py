# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Shared clock catalogue, absolute deadlines and finite packet contract.

No serial I/O and no private game data here. Standard clocks can register in
assets/clocks/catalog.json and implement build_packet in clock_standard.py.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import threading
import time
from datetime import datetime
from signalbar import __version__
from .gif import encode
from .timing import SYNC_MAX_BYTES, transfer_ms

ROOT = Path(__file__).resolve().parents[3]
PERIOD = 240
GUARD = 10
RENDER_LEAD = 8
MAX_CLOCK_FRAMES = 1024
CADENCES = ('conservative', 'minute')


def clock_period(cadence):
    if cadence not in CADENCES: raise ValueError('Choose a supported clock transfer mode')
    return 60 if cadence == 'minute' else PERIOD


def catalog(version=__version__, root=ROOT):
    result = []
    paths = [(Path(root)/'assets/clocks/catalog.json', False)]
    if (re.fullmatch(r'v?\d+\.\d+\.\d+-lab\.\d+', str(version))
            and str(version).removeprefix('v') not in {'1.5.1-lab.287', '1.5.1-lab.288'}):
        paths.append((Path(root)/'assets/clocks-lab/catalog.json', True))
    for path, private in paths:
        if not path.is_file(): continue
        if path.is_symlink() or path.stat().st_size > 16384: raise ValueError('Invalid clock catalogue')
        entries = json.loads(path.read_text())
        if not isinstance(entries, list) or len(entries) > 32: raise ValueError('Invalid clock catalogue')
        for entry in entries:
            key = entry.get('id', '')
            if not re.fullmatch(r'[a-z][a-z0-9-]{0,39}', key): raise ValueError('Invalid clock identifier')
            if any(x['id'] == key for x in result): raise ValueError('Duplicate clock identifier')
            result.append({'id': key, 'label': str(entry['label'])[:100], 'private': private, 'family': entry.get('family', ''),
                           'movement_seconds': entry.get('movement_seconds', 60), 'packet_seconds': PERIOD})
    return result


def require_clock(key, version=__version__, root=ROOT):
    for entry in catalog(version, root):
        if entry['id'] == key: return entry
    raise ValueError('Choose an available clock')


def is_night(epoch, solar=None):
    """Use GCA's actual solar selector; unprogrammed installs use 20–07."""
    solar = solar or {}
    if solar.get('enabled') and solar.get('available') and type(solar.get('is_night')) is bool:
        return solar['is_night']
    hour = datetime.fromtimestamp(epoch).hour
    return hour >= 20 or hour < 7


@dataclass
class ClockPacket:
    frames: tuple
    delays_cs: tuple
    signature: str

    def gif(self):
        if not self.frames or len(self.frames) > MAX_CLOCK_FRAMES: raise ValueError('Clock frame budget exceeded')
        if (len(self.frames) != len(self.delays_cs)
                or any(len(frame) != 64*54*3 for frame in self.frames)
                or any(type(delay) is not int or not 1 <= delay <= 65535 for delay in self.delays_cs)
                or not 0 < sum(self.delays_cs) <= 25000):
            raise ValueError('Invalid native clock timeline')
        colors = list(dict.fromkeys(tuple(frame[i:i+3]) for frame in self.frames for i in range(0,len(frame),3)))
        if len(colors) > 255: raise ValueError('Clock palette budget exceeded')
        lookup = {bytes(color): i for i,color in enumerate(colors)}
        indexed = [bytes(lookup[frame[i:i+3]] for i in range(0,len(frame),3)) for frame in self.frames]
        transparent = len(colors); colors.append((0,0,0))
        delta = [indexed[0]] + [bytes(transparent if a == b else b for a,b in zip(p,c)) for p,c in zip(indexed,indexed[1:])]
        result = encode(64,54,colors,delta,delay_cs=self.delays_cs,loop=False,
                        transparent_index=[None]+[transparent]*(len(delta)-1))
        if len(result) > SYNC_MAX_BYTES: raise ValueError('Clock exceeds the 80 KiB synchronized transfer budget')
        return result


def build_packet(request):
    entry = require_clock(request['clock_id'])
    if entry['private']:
        from .clock_art_lab import build_packet as build
    else:
        from .clock_standard import build_packet as build
    return build(request)


class ClockRuntime:
    """Deadlines are epochs, never chained upload-completion timers."""
    def __init__(self):
        self.lock = threading.RLock()
        self.key = None
        self.pending = None
        self.active = None
        self.state = 'idle'
        self.error = ''
        self.transfer_seconds = 10.0
        self.bytes = 0
        self.retry_at = 0
        self.residual_ms = None
        self.anchor = None
        self.private_timeline = None
        self.session_started = False

    def invalidate(self, reason='context changed'):
        with self.lock:
            self.pending = self.active = self.key = None
            self.state, self.error = 'idle', reason
            self.retry_at = 0
            self.anchor = None
            self.private_timeline = None
            self.session_started = False

    def plan(self, key, context, now, night, *, force=False, monotonic=None, options=None, cadence='conservative'):
        entry = require_clock(key)
        period = clock_period(cadence)
        appearance = None
        if not entry.get('private') and options is not None:
            from .clock_standard import normalize_options
            appearance = normalize_options(options)
        with self.lock:
            mono = time.monotonic() if monotonic is None else monotonic
            if self.anchor and abs((now-self.anchor[0])-(mono-self.anchor[1])) > .5:
                force = True
            identity = (key, context, bool(night), tuple(sorted((appearance or {}).items())), cadence)
            if identity != self.key or force:
                # A render/transport refresh is not a new story session.
                # Keep the absolute visit even across day/night or NTP recovery.
                same_selection = bool(self.key and self.key[:2] == (key, context))
                timeline = self.private_timeline if same_selection else None
                started = self.session_started if same_selection else False
                self.invalidate('')
                self.key = identity
                self.private_timeline, self.session_started = timeline, started
            self.anchor = (now,mono)
            if self.pending or now < self.retry_at: return None
            lead = self.transfer_seconds + RENDER_LEAD
            target = self.active['renew_at'] if self.active else now + lead
            if self.active and now < target - lead: return None
            if target < now + self.transfer_seconds + 1:
                target = now + lead
            target = math.ceil(target*100)/100
            boundary = (math.floor(target/period)+1)*period
            self.pending = {'kind':'clock', 'clock_id':key, 'context':context, 'cadence':cadence,
                            'display_at':target, 'end_at':boundary+GUARD,
                            'renew_at':boundary, 'night':bool(night)}
            if entry.get('private'):
                from .clock_art_lab import initial_timeline
                if self.private_timeline is None or not self.session_started:
                    self.private_timeline = initial_timeline(key, target)
                if self.private_timeline:
                    self.pending['timeline'] = dict(self.private_timeline)
            if appearance is not None: self.pending['options'] = appearance
            self.state, self.error = 'preparing', ''
            return dict(self.pending)

    def receipt(self, packet, result, now):
        with self.lock:
            # A completed old job cannot acknowledge a replacement selection.
            if not self.pending: return
            if any(packet.get(k) != v for k,v in self.pending.items()): return
            if result.get('synchronized') and not result.get('error') and not result.get('superseded'):
                self.active = dict(self.pending)
                self.session_started = True
                self.state, self.error = 'acknowledged', ''
                observed = (result.get('transfer') or {}).get('total_ms') or result.get('ack_ms') or result.get('upload_ms')
                if observed and math.isfinite(float(observed)) and 0 < float(observed) < 30000:
                    # Most recent actual transfer, not render/queue/wait duration.
                    self.transfer_seconds = float(observed)/1000
                self.bytes = int(result.get('clock_bytes', self.bytes))
                self.residual_ms = round((now-self.active['display_at'])*1000)
            else:
                self.state = 'unconfirmed' if result.get('sent_unconfirmed') else 'delayed'
                self.error = str(result.get('error') or 'Clock refresh delayed')[:180]
                self.retry_at = now + max(2, min(60,float(result.get('retry_after',5))))
            self.pending = None

    def diagnostic_snapshot(self):
        """Small playback/packet identities, no pixels, paths or catalogue."""
        with self.lock:
            def packet(value):
                return {k:value[k] for k in ('display_at','end_at','renew_at') if k in value} if value else {}
            return {'selected':self.key[0] if self.key else '',
                    'context':self.key[1] if self.key else '', 'state':self.state,
                    'cadence':self.key[4] if self.key else 'conservative',
                    'session_started':self.session_started,
                    'active':packet(self.active), 'pending':packet(self.pending),
                    'visit':dict(self.private_timeline or {})}

    def snapshot(self, selected, context, now, *, eligible=True):
        with self.lock:
            entry = next((x for x in catalog() if x['id']==selected), None)
            live = self.active if self.key and self.key[:2] == (selected,context) else None
            state = self.state if eligible else 'paused'
            if live and now >= live['end_at']: state = 'expired'
            cadence = entry['movement_seconds'] if entry else 60
            next_move = (math.floor(now/cadence)+1)*cadence if live and state in {'acknowledged','preparing','waiting','transferring'} else None
            if next_move and entry and entry['private']:
                from .clock_art_lab import next_movement
                next_move = next_movement(selected,now,next_move,live.get('timeline'))
            next_gif = (self.pending['display_at']-self.transfer_seconds if self.pending else
                        live['renew_at']-self.transfer_seconds if live else None)
            if state in {'delayed','unconfirmed'}: next_gif = self.retry_at
            transitions = {}
            scheduled = self.pending or live
            if scheduled and eligible and entry and entry['private'] and state in {'acknowledged','preparing','waiting','transferring'}:
                from .clock_art_lab import transition_status
                transitions = transition_status(selected, now, scheduled.get('timeline'))
            cadence = self.key[4] if self.key and self.key[:2] == (selected,context) else 'conservative'
            return {**transitions, 'cadence':cadence, 'packet_seconds':clock_period(cadence),
                    'nominal_transfers_per_hour':3600//clock_period(cadence), 'catalog':catalog(), 'selected':selected, 'context':context, 'state':state,
                    'server_now':now, 'next_gif_at':next_gif if eligible else None,
                    'next_movement_at':next_move if eligible else None,
                    'estimated_display_at':self.pending['display_at'] if self.pending else None,
                    'valid_until':live['end_at'] if live else None, 'bytes':self.bytes,
                    'transfer_seconds':round(self.transfer_seconds,3), 'ack_offset_ms':self.residual_ms,
                    'optical_verified':False, 'error':self.error}
