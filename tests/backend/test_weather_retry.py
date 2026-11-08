"""Exercise the real weather worker with a monotonic clock and no network waits."""

import unittest

from signalbar.providers.weather import WeatherProvider
from signalbar.settings.store import DEFAULTS


CITY = {"name": "Paris", "latitude": 48.85, "longitude": 2.35}
OTHER_CITY = {"name": "Lyon", "latitude": 45.76, "longitude": 4.84}
SAMPLE = {"condition": "rain", "is_day": True, "weather_code": 61,
          "observed_at": "2026-10-26T12:00", "temperature_c": 12.0}


class WorkerHarness:
    """Run _run synchronously, advancing only while the worker would wait."""

    def __init__(self, outcomes, *, start=1000.0, until=1001.0,
                 during_fetch=None, events=()):
        self.now = start
        self.until = until
        self.calls = []
        self.outcomes = outcomes
        self.during_fetch = during_fetch
        self.events = list(events)
        self.provider = WeatherProvider(clock=lambda: self.now, fetch=self.fetch)
        self.provider.configure(CITY, "home")
        self.provider._wake = self

    def fetch(self, location):
        index = len(self.calls)
        self.calls.append((self.now, dict(location)))
        result = self.outcomes[min(index, len(self.outcomes) - 1)]
        if self.during_fetch:
            self.during_fetch(self, index)
        if isinstance(result, Exception):
            raise result
        return dict(result) if result is not None else None

    def wait(self, timeout):
        target = min(self.now + timeout, self.until)
        if self.events and self.events[0][0] <= target:
            self.now, callback = self.events.pop(0)
            callback(self.provider)
            return True
        self.now = target
        if self.now >= self.until:
            self.provider._stop.set()
        return False

    def set(self):
        pass

    def clear(self):
        pass

    def run(self):
        self.provider._run()
        return [at for at, _location in self.calls]


class WeatherRetryTests(unittest.TestCase):
    def test_persistent_outage_retries_for_five_minutes_then_stays_at_fifteen(self):
        worker = WorkerHarness([RuntimeError("offline")], until=3101)
        self.assertEqual(worker.run(),
                         [1000 + offset for offset in range(0, 301, 30)]
                         + [2200, 3100])
        self.assertEqual(worker.provider._error, "offline")

    def test_empty_response_at_zero_starts_only_one_recovery_window(self):
        worker = WorkerHarness([None], start=0, until=1201)
        self.assertEqual(worker.run(), list(range(0, 301, 30)) + [1200])
        self.assertEqual(worker.provider._error, "weather unavailable")

    def test_success_ends_fast_retries_and_returns_to_the_normal_schedule(self):
        worker = WorkerHarness([RuntimeError("offline"), None, SAMPLE], until=1961)
        self.assertEqual(worker.run(), [1000, 1030, 1060, 1960])
        self.assertEqual(worker.provider._sample, SAMPLE)
        self.assertEqual(worker.provider._error, "")
        self.assertIsNone(worker.provider._retry_deadline)

    def test_a_new_outage_after_success_gets_a_new_five_minute_window(self):
        worker = WorkerHarness([None, SAMPLE, None], until=2231)
        self.assertEqual(worker.run(), [1000, 1030]
                         + list(range(1930, 2231, 30)))

    def test_success_keeps_the_existing_earlier_solar_transition_refresh(self):
        worker = WorkerHarness([None, dict(SAMPLE, seconds_until_solar_transition=45),
                                SAMPLE], until=1077)
        self.assertEqual(worker.run(), [1000, 1030, 1076])
        self.assertEqual(worker.provider._next_fetch, 1976)

    def test_slow_failure_does_not_extend_the_fast_retry_deadline(self):
        def slow_retry(worker, index):
            if index == 1:
                worker.now += 280

        worker = WorkerHarness([None], until=2211, during_fetch=slow_retry)
        self.assertEqual(worker.run(), [1000, 1030, 2210])

    def test_failure_preserves_the_previous_sample_and_its_original_age(self):
        worker = WorkerHarness([None], until=1031)
        worker.provider._sample = dict(SAMPLE)
        worker.provider._fetched_at = 990
        self.assertEqual(worker.run(), [1000, 1030])
        self.assertEqual(worker.provider._sample, SAMPLE)
        self.assertEqual(worker.provider._fetched_at, 990)
        status = worker.provider.status(dict(DEFAULTS, weather_display="home"))
        self.assertEqual(status["temperature_c"], 12.0)
        self.assertEqual(status["error"], "weather unavailable")

    def test_unchanged_configuration_does_not_restart_an_exhausted_window(self):
        worker = WorkerHarness([None], until=2201, events=[
            (1350, lambda provider: provider.configure(CITY, "home")),
        ])
        self.assertEqual(worker.run(), list(range(1000, 1301, 30)) + [2200])

    def test_changed_city_starts_its_own_recovery_window_immediately(self):
        worker = WorkerHarness([None], until=1681, events=[
            (1350, lambda provider: provider.configure(OTHER_CITY, "home")),
        ])
        self.assertEqual(worker.run(), list(range(1000, 1301, 30))
                         + list(range(1350, 1651, 30)))
        self.assertEqual(worker.calls[-1][1], OTHER_CITY)

    def test_disabling_weather_cancels_retries_and_reenabling_starts_fresh(self):
        worker = WorkerHarness([None], until=1111, events=[
            (1010, lambda provider: provider.configure(None, "off")),
            (1080, lambda provider: provider.configure(CITY, "home")),
        ])
        self.assertEqual(worker.run(), [1000, 1080, 1110])

    def test_inflight_result_for_an_old_city_cannot_schedule_its_retry(self):
        def change_city(worker, index):
            if index == 0:
                worker.provider.configure(OTHER_CITY, "home")

        worker = WorkerHarness([None, SAMPLE], until=1001, during_fetch=change_city)
        self.assertEqual(worker.run(), [1000, 1000])
        self.assertEqual(worker.calls[1][1], OTHER_CITY)
        self.assertEqual(worker.provider._sample, SAMPLE)
        self.assertEqual(worker.provider._next_fetch, 1900)
        self.assertIsNone(worker.provider._retry_deadline)

    def test_stop_during_request_does_not_schedule_another_attempt(self):
        worker = WorkerHarness([None], during_fetch=lambda h, _i: h.provider._stop.set())
        self.assertEqual(worker.run(), [1000])
        self.assertIsNone(worker.provider._retry_deadline)


if __name__ == "__main__":
    unittest.main()
