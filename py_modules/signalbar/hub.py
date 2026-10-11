"""Pass engine events to subscribers such as the MQTT bridge without blocking the engine.

A feature publishes with ``engine.hub.emit("<area>.<event>", {...})`` and
every subscriber receives it with no further wiring.
"""

from __future__ import annotations

import collections
import threading


class EventHub:
    def __init__(self, logger=None, limit=256):
        self.log = logger
        self._subscribers = []
        self._queue = collections.deque()
        self._limit = limit
        self._condition = threading.Condition()
        self._thread = None
        self._stopping = False
        self.dropped = 0
        self.known_kinds = set()

    def subscribe(self, callback):
        with self._condition:
            self._subscribers.append(callback)
            if self._thread is None or not self._thread.is_alive():
                self._stopping = False
                self._thread = threading.Thread(target=self._run, name="gabecubeaura-events", daemon=True)
                self._thread.start()

        def unsubscribe():
            with self._condition:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)
        return unsubscribe

    def emit(self, kind, data):
        with self._condition:
            if not self._subscribers:
                return
            self.known_kinds.add(kind)
            if len(self._queue) >= self._limit:
                self._queue.popleft()
                self.dropped += 1
            self._queue.append((kind, dict(data)))
            self._condition.notify()

    def stop(self):
        with self._condition:
            self._stopping = True
            self._condition.notify_all()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def _run(self):
        while True:
            with self._condition:
                while not self._queue and not self._stopping:
                    self._condition.wait()
                if self._stopping:
                    return
                kind, data = self._queue.popleft()
                subscribers = list(self._subscribers)
            for callback in subscribers:
                try:
                    callback(kind, data)
                except Exception as error:
                    # One failing subscriber must not starve the others.
                    if self.log:
                        self.log.warning(f"[GabeCubeAura] event subscriber failed: {error}")
