"""Share a finite join budget across nested plugin shutdown operations.

Cancellation must still be signalled when the budget is exhausted. This bounds
thread waits, not arbitrary filesystem/device calls or third-party locks.
"""
import time


class ShutdownBudget:
    def __init__(self, seconds=None, clock=time.monotonic):
        self.clock = clock
        self.deadline = None if seconds is None else clock() + max(0.0, float(seconds))

    def remaining(self, maximum=None):
        if self.deadline is None:
            return maximum
        left = max(0.0, self.deadline - self.clock())
        return left if maximum is None else min(left, maximum)

    def call(self, callback, *args, **kwargs):
        # Preserve legacy/default stop contracts outside bounded Decky unload.
        if self.deadline is not None:
            kwargs['timeout'] = self.remaining()
        return callback(*args, **kwargs)
