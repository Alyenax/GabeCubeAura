"""Bounded, text-free incident context independent of the rolling event tail.

The caller supplies sanitized journal events. Only controlled voice metadata is
retained here. Persist at session start, first incident and terminal state, not
for each audio block. Interrupted sessions are evidence, never replay authority.
"""
from collections import deque
import copy
import json
import re

IDENTITY = re.compile(r'^[a-f0-9]{16}$')
FIELDS = ('voice_session', 'turn_id', 'response_id', 'phase', 'category',
          'kind', 'success', 'cancelled', 'exception', 'exit_code', 'signal',
          'generation', 'session_elapsed_ms', 'duration_ms', 'frontend_instance')
TRIGGERS = {'gabe_session_failed', 'gabe_cleanup_failed', 'gabe_asr_failed',
            'gabe_capture_failed', 'gabe_interruption_failed'}


class VoiceIncidents:
    def __init__(self, value=None, backend='', clock=lambda: 0):
        value = value if isinstance(value, dict) else {}
        self.backend, self.clock = backend, clock
        self.history = []
        # Revalidate the on-disk structure; never trust arbitrary log content.
        for incident in value.get('incidents', [])[-3:]:
            cleaned = self._incident(incident)
            if cleaned:
                self.history.append(cleaned)
        active = self._incident(value.get('active'))
        self.recovered = None
        if active:
            active.update(outcome='interrupted', trigger='backend-restarted',
                          incident_at=int(clock()))
            self.recovered = active
            self.history = [row for row in self.history if row['id'] != active['id']]
            self.history.append(active)
            self.history = self.history[-3:]
        self.active = None
        self.before = deque(maxlen=32)
        self.after = 0

    @staticmethod
    def _event(item):
        if not isinstance(item, dict):
            return None
        fields = item.get('fields', {})
        if not isinstance(fields, dict):
            return None
        return {'time': max(0, int(item.get('time', 0))),
                'event': re.sub(r'[^A-Za-z0-9_.:-]', '_', str(item.get('event', '')))[:96],
                'fields': {key: value for key, value in fields.items() if key in FIELDS
                           and (type(value) in (bool, int) or
                                isinstance(value, str) and len(value) <= 96)}}

    @classmethod
    def _incident(cls, value):
        if not isinstance(value, dict) or not IDENTITY.fullmatch(str(value.get('id', ''))):
            return None
        events = value.get('events', [])
        if not isinstance(events, list):
            return None
        return {'id': value['id'], 'backend': str(value.get('backend', ''))[:32],
                'started_at': max(0, int(value.get('started_at', 0))),
                'incident_at': max(0, int(value.get('incident_at', 0))),
                'outcome': value.get('outcome') if value.get('outcome') in
                    ('active', 'failed', 'cancelled', 'success', 'interrupted') else 'active',
                'trigger': str(value.get('trigger', ''))[:96],
                'events': [event for row in events[:48] if (event := cls._event(row))]}

    def observe(self, item):
        event = self._event(item)
        if not event:
            return False
        name, fields = event['event'], event['fields']
        identity = str(fields.get('voice_session', ''))
        if name == 'gabe_session_started' and IDENTITY.fullmatch(identity):
            self.active = {'id': identity, 'backend': self.backend,
                           'started_at': event['time'], 'incident_at': 0,
                           'outcome': 'active', 'trigger': '', 'events': [event]}
            self.before.clear()
            self.before.append(event)
            self.after = 0
            return True
        if not self.active or identity != self.active['id']:
            return False
        trigger = name in TRIGGERS or (name == 'voice_frontend_lifecycle' and
                   fields.get('kind') in ('error', 'rejection', 'notification-failed'))
        persist = False
        if trigger and not self.active['incident_at']:
            context = self.active['events'][:8] + list(self.before)[-23:] + [event]
            self.active.update(incident_at=event['time'], trigger=name,
                               events=[row for i, row in enumerate(context) if row not in context[:i]])
            self.after = 16
            persist = True
        elif self.active['incident_at'] and self.after:
            self.active['events'].append(event)
            self.active['events'] = self.active['events'][:48]
            self.after -= 1
        elif not self.active['incident_at'] and len(self.active['events']) < 8:
            self.active['events'].append(event)
        self.before.append(event)
        if name == 'gabe_session_finished':
            if fields.get('cancelled'):
                outcome = 'cancelled'
            else:
                outcome = 'success' if fields.get('success') else 'failed'
            self.active['outcome'] = outcome
            if outcome == 'failed' and not self.active['incident_at']:
                context = self.active['events'][:8] + list(self.before)[-24:]
                self.active.update(incident_at=event['time'], trigger=name,
                                   events=[row for i, row in enumerate(context) if row not in context[:i]])
            if self.active['incident_at']:
                if event not in self.active['events']:
                    self.active['events'] = self.active['events'][:47] + [event]
                self.history = [row for row in self.history if row['id'] != identity]
                self.history.append(self.active)
                self.history = self.history[-3:]
            self.active = None
            persist = True
        return persist

    def snapshot(self):
        result = copy.deepcopy({'schema': 1, 'active': self.active,
                                'incidents': self.history[-3:]})
        # Bound both serialized persistence and in-memory report copies. Never
        # let unusually verbose metadata bypass the journal's normal rotation.
        while len(json.dumps(result,indent=2,sort_keys=True).encode()) > 48*1024:
            if result['incidents'] and (result['active'] or len(result['incidents']) > 1):
                result['incidents'].pop(0)
                continue
            rows = result['incidents'] + ([result['active']] if result['active'] else [])
            largest = max(rows, key=lambda row: len(row['events']))
            if len(largest['events']) <= 1:
                break
            largest['events'].pop(8 if len(largest['events'])>8 else 1)
        return result

    def choices(self):
        rows = self.history + ([self.active] if self.active and self.active['incident_at'] else [])
        return [{'id': row['id'], 'time': row['incident_at'], 'outcome': row['outcome']}
                for row in reversed(rows[-3:])]
