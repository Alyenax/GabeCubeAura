"""Single-use consent attached to the existing personal countdown, never stored.

No deadline scheduler or system calls here. The countdown reports natural
expiry; the engine claims one request. Cancel/replacement invalidates its token.
"""
import threading
import time


VALID_ACTIONS = frozenset(('none', 'sleep', 'shutdown'))


class TimerEndAction:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.RLock()
        self.generation = 0
        self.action = 'none'
        self.phase = 'idle'
        self.deadline = 0.
        self.cancelled = threading.Event()
        self.reason = ''

    def arm(self, action, deadline):
        if not isinstance(action, str) or action not in VALID_ACTIONS:
            raise ValueError('Unsupported timer end action')
        with self.lock:
            self.cancelled.set()
            self.generation += 1
            self.cancelled = threading.Event()
            self.action, self.deadline = action, deadline
            self.phase = 'idle' if action == 'none' else 'armed'
            self.reason = ''
            return self.generation

    def extend(self, generation, deadline):
        with self.lock:
            if generation == self.generation and self.phase == 'armed':
                self.deadline = deadline

    def expire(self, generation):
        with self.lock:
            if generation == self.generation and self.phase == 'armed':
                self.phase = 'ready'

    def cancel(self, reason='cancelled'):
        with self.lock:
            self.cancelled.set()
            if self.phase in ('armed', 'ready', 'executing'):
                self.phase, self.reason = 'cancelled', reason

    def claim(self):
        with self.lock:
            if self.phase != 'ready' or self.cancelled.is_set():
                return None
            if not 0 <= self.clock()-self.deadline <= 30:
                self.phase, self.reason = 'skipped', 'late-expiry'
                self.cancelled.set()
                return None
            self.phase = 'executing'
            return self.generation, self.action, self.cancelled

    def finish(self, generation, accepted):
        with self.lock:
            if generation != self.generation or self.phase != 'executing':
                return
            self.phase = 'cancelled' if self.cancelled.is_set() else 'requested' if accepted else 'failed'
            self.reason = '' if accepted else 'power-request-not-confirmed'

    def status(self):
        with self.lock:
            return {'action': self.action, 'phase': self.phase, 'reason': self.reason}
