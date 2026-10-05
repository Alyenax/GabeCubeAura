"""Local CPU/GPU metrics and compact 17-pixel meter layouts."""

from __future__ import annotations

import glob
import math
import os
import time

from signalbar.models import LED_COUNT, PerformanceSample, ProviderOutput, normalize_frame

PALETTES = {
    "thermal": ((30, 180, 230), (245, 180, 45), (235, 45, 55)),
    "classic": ((35, 205, 95), (245, 205, 45), (235, 45, 55)),
    "icefire": ((45, 105, 245), (170, 75, 220), (245, 55, 95)),
}

# alpha-up, alpha-down, lower samples required, max rise %/s, max fall %/s
SMOOTHING_PROFILES = {
    "responsive": (0.70, 0.45, 1, 60.0, 45.0),
    "balanced": (0.45, 0.20, 2, 25.0, 16.0),
    "smooth": (0.25, 0.12, 3, 12.5, 8.0),
}


def _coherent_temperature(value):
    """Reject unavailable, non-finite or physically incoherent sensor data."""
    if value is None or isinstance(value, bool):
        return None
    try:
        clean = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(clean) or clean < -40.0 or clean > 150.0:
        return None
    return clean


def _lerp(left, right, amount):
    return int(round(left + (right - left) * amount))


def temperature_color(temp_c, cool_c=50.0, hot_c=90.0, palette="thermal",
                      custom_palette=None):
    colors = custom_palette if palette == "custom" else PALETTES.get(palette)
    if not isinstance(colors, (list, tuple)) or len(colors) != 3:
        colors = PALETTES["thermal"]
    cool, middle, hot = colors
    span = max(1.0, float(hot_c) - float(cool_c))
    heat = max(0.0, min(1.0, (float(temp_c) - float(cool_c)) / span))
    if heat <= 0.5:
        amount = heat * 2.0
        return tuple(_lerp(cool[index], middle[index], amount) for index in range(3))
    amount = (heat - 0.5) * 2.0
    return tuple(_lerp(middle[index], hot[index], amount) for index in range(3))


def _meter_lit_count(load_percent, count):
    load = max(0.0, min(100.0, float(load_percent)))
    return max(0, min(count, int(round(count * load / 100.0))))


def _compensated_lit_counts(lit_counts, dark_edge_compensation):
    """Remove a total number of edge pixels while retaining active meters.

    Mixed mode shares the requested compensation across both halves instead of
    subtracting it twice. The fuller half is reduced first, which keeps the
    split display balanced while leaving one physical pixel for each non-empty
    logical meter.
    """
    result = [max(0, int(value)) for value in lit_counts]
    compensation = max(0, min(LED_COUNT - 1, int(dark_edge_compensation)))
    for _ in range(compensation):
        candidates = [index for index, value in enumerate(result) if value > 1]
        if not candidates:
            break
        selected = max(candidates, key=lambda index: (result[index], -index))
        result[selected] -= 1
    return result


def _meter(load_percent, temp_c, count, cool_c, hot_c, palette, lit_count=None,
           custom_palette=None):
    lit = _meter_lit_count(load_percent, count) if lit_count is None else int(lit_count)
    lit = max(0, min(count, lit))
    color = temperature_color(temp_c, cool_c, hot_c, palette, custom_palette)
    return [color] * lit + [(0, 0, 0)] * (count - lit)


def performance_frame(
    load_percent, temp_c, cool_c=50.0, hot_c=90.0, palette="thermal",
    dark_edge_compensation=0, custom_palette=None,
):
    logical_lit = _meter_lit_count(load_percent, LED_COUNT)
    physical_lit = _compensated_lit_counts(
        [logical_lit], dark_edge_compensation,
    )[0]
    return normalize_frame(_meter(
        load_percent, temp_c, LED_COUNT, cool_c, hot_c, palette,
        lit_count=physical_lit, custom_palette=custom_palette,
    ))


def mixed_performance_frame(
    sample, cool_c=50.0, hot_c=90.0, palette="thermal",
    direction="mirrored", dark_edge_compensation=0, custom_palette=None,
):
    """CPU left, black separator, GPU right with selectable direction."""
    cpu_load = sample.cpu_load or 0.0
    gpu_load = sample.gpu_load or 0.0
    cpu_lit, gpu_lit = _compensated_lit_counts(
        [_meter_lit_count(cpu_load, 8), _meter_lit_count(gpu_load, 8)],
        dark_edge_compensation,
    )
    cpu = _meter(
        cpu_load, sample.cpu_temp_c or cool_c, 8, cool_c, hot_c, palette,
        lit_count=cpu_lit, custom_palette=custom_palette,
    )
    gpu = _meter(
        gpu_load, sample.gpu_temp_c or cool_c, 8, cool_c, hot_c, palette,
        lit_count=gpu_lit, custom_palette=custom_palette,
    )
    if direction == "mirrored":
        gpu = list(reversed(gpu))
    return normalize_frame(cpu + [(0, 0, 0)] + gpu)


class LinuxSystemMetrics:
    def __init__(self, sys_root="/sys", proc_root="/proc"):
        self.sys_root = sys_root.rstrip("/")
        self.proc_root = proc_root.rstrip("/")
        self._previous_cpu = None

    @staticmethod
    def _read_number(path):
        try:
            with open(path, encoding="ascii") as handle:
                return float(handle.read().strip())
        except (OSError, ValueError):
            return None

    @staticmethod
    def _read_text(path):
        try:
            with open(path, encoding="ascii") as handle:
                return handle.read().strip()
        except OSError:
            return ""

    def _gpu_load(self):
        pattern = os.path.join(self.sys_root, "class/drm/card*/device/gpu_busy_percent")
        for path in sorted(glob.glob(pattern)):
            value = self._read_number(path)
            if value is not None:
                return max(0.0, min(100.0, value))
        return None

    def _gpu_temp(self):
        pattern = os.path.join(self.sys_root, "class/drm/card*/device/hwmon/hwmon*")
        for hwmon in sorted(glob.glob(pattern)):
            name = self._read_text(os.path.join(hwmon, "name")).lower()
            if name and "amd" not in name and "gpu" not in name:
                continue
            for path in sorted(glob.glob(os.path.join(hwmon, "temp*_input"))):
                value = self._read_number(path)
                if value is not None:
                    return value / 1000.0 if value > 500.0 else value
        return None

    def _cpu_load(self):
        try:
            first = self._read_text(os.path.join(self.proc_root, "stat")).splitlines()[0].split()
            if not first or first[0] != "cpu":
                return None
            values = [float(value) for value in first[1:]]
        except (IndexError, ValueError):
            return None
        total = sum(values)
        idle = (values[3] if len(values) > 3 else 0.0) + (values[4] if len(values) > 4 else 0.0)
        previous = self._previous_cpu
        self._previous_cpu = (total, idle)
        if previous is None:
            return None
        total_delta = total - previous[0]
        idle_delta = idle - previous[1]
        if total_delta <= 0:
            return None
        return max(0.0, min(100.0, 100.0 * (1.0 - idle_delta / total_delta)))

    def _cpu_temp(self):
        preferred = ("k10temp", "coretemp", "zenpower", "cpu_thermal", "acpitz")
        for hwmon in sorted(glob.glob(os.path.join(self.sys_root, "class/hwmon/hwmon*"))):
            name = self._read_text(os.path.join(hwmon, "name")).lower()
            if name and not any(token in name for token in preferred):
                continue
            candidates = []
            for path in sorted(glob.glob(os.path.join(hwmon, "temp*_input"))):
                label = self._read_text(path.replace("_input", "_label")).lower()
                priority = 0 if any(token in label for token in ("tctl", "tdie", "package")) else 1
                candidates.append((priority, path))
            for _, path in sorted(candidates):
                value = self._read_number(path)
                if value is not None:
                    return value / 1000.0 if value > 500.0 else value
        for path in sorted(glob.glob(os.path.join(self.sys_root, "class/thermal/thermal_zone*/temp"))):
            value = self._read_number(path)
            if value is not None:
                return value / 1000.0 if value > 500.0 else value
        return None

    def sample(self):
        return PerformanceSample(
            gpu_load=self._gpu_load(),
            gpu_temp_c=self._gpu_temp(),
            cpu_load=self._cpu_load(),
            cpu_temp_c=self._cpu_temp(),
            sampled_at=time.monotonic(),
        )


LinuxGpuMetrics = LinuxSystemMetrics


class PerformanceProvider:
    name = "performance"

    def __init__(self, metrics=None, interval_s=0.5, clock=time.monotonic):
        self.metrics = metrics or LinuxSystemMetrics()
        self.interval_s = max(0.5, float(interval_s))
        self._clock = clock
        self._last = PerformanceSample()
        self._next_sample_at = 0.0
        self._last_sample_at = 0.0
        self._fall_streak = {"cpu": 0, "gpu": 0}
        self._smoothing_name = "balanced"
        self.error = ""

    @property
    def sample(self):
        if self._last.sampled_at and self._clock() - self._last.sampled_at > 2.5:
            return PerformanceSample()
        return self._last

    def refresh(self, smoothing="balanced"):
        """Collect independently from display selection, at most twice a second."""
        now = self._clock()
        if now < self._next_sample_at:
            return
        self._next_sample_at = now + self.interval_s
        smoothing = str(smoothing) if str(smoothing) in SMOOTHING_PROFILES else "balanced"
        if smoothing != self._smoothing_name:
            self._fall_streak = {"cpu": 0, "gpu": 0}
            self._smoothing_name = smoothing
        try:
            raw = self.metrics.sample()
            self._last = self._smooth_sample(raw, smoothing, now)
            self.error = ""
        except Exception as error:
            self._last = PerformanceSample(sampled_at=now)
            self._fall_streak = {"cpu": 0, "gpu": 0}
            self.error = str(error)[:160]

    def _smooth_load(self, name, raw, previous, profile, elapsed):
        if raw is None:
            self._fall_streak[name] = 0
            return None
        raw = max(0.0, min(100.0, float(raw)))
        if previous is None:
            self._fall_streak[name] = 0
            return raw
        previous = max(0.0, min(100.0, float(previous)))
        rise_alpha, fall_alpha, fall_samples, rise_rate, fall_rate = profile
        if raw >= previous:
            self._fall_streak[name] = 0
            alpha = rise_alpha
            rate = rise_rate
        else:
            self._fall_streak[name] += 1
            if self._fall_streak[name] < fall_samples:
                return previous
            alpha = fall_alpha
            rate = fall_rate
        candidate = previous + alpha * (raw - previous)
        limit = max(0.1, rate * max(0.05, elapsed))
        delta = max(-limit, min(limit, candidate - previous))
        return max(0.0, min(100.0, previous + delta))

    def _smooth_sample(self, raw, smoothing, now):
        profile = SMOOTHING_PROFILES.get(
            str(smoothing), SMOOTHING_PROFILES["balanced"],
        )
        elapsed = (
            self.interval_s if self._last_sample_at <= 0
            else max(0.05, min(2.0, now - self._last_sample_at))
        )
        previous = self.sample
        self._last_sample_at = now
        return PerformanceSample(
            gpu_load=self._smooth_load(
                "gpu", raw.gpu_load, previous.gpu_load, profile, elapsed,
            ),
            gpu_temp_c=_coherent_temperature(raw.gpu_temp_c),
            cpu_load=self._smooth_load(
                "cpu", raw.cpu_load, previous.cpu_load, profile, elapsed,
            ),
            cpu_temp_c=_coherent_temperature(raw.cpu_temp_c),
            sampled_at=raw.sampled_at or now,
        )

    def frame(
        self, metric="gpu", cool_c=50.0, hot_c=90.0, palette="thermal",
        direction="mirrored", dark_edge_compensation=0, custom_palette=None,
    ):
        sample = self.sample
        if metric == "cpu":
            return performance_frame(
                sample.cpu_load or 0.0, sample.cpu_temp_c or cool_c,
                cool_c, hot_c, palette, dark_edge_compensation, custom_palette,
            )
        if metric == "mixed":
            return mixed_performance_frame(
                sample, cool_c, hot_c, palette, direction,
                dark_edge_compensation, custom_palette,
            )
        return performance_frame(
            sample.gpu_load or 0.0, sample.gpu_temp_c or cool_c,
            cool_c, hot_c, palette, dark_edge_compensation, custom_palette,
        )

    def output(
        self, metric="gpu", cool_c=50.0, hot_c=90.0, palette="thermal",
        direction="mirrored", dark_edge_compensation=0,
        smoothing="balanced", enabled=True, custom_palette=None,
    ):
        self.refresh(smoothing)
        if not enabled:
            return ProviderOutput(self.name, None, "performance disabled")
        if metric == "cpu":
            if not self.sample.cpu_available:
                return ProviderOutput(self.name, None, "CPU metrics unavailable")
            frame = self.frame(
                metric, cool_c, hot_c, palette, direction,
                dark_edge_compensation, custom_palette,
            )
            return ProviderOutput(self.name, frame, "CPU load and temperature")
        if metric == "mixed":
            if not (self.sample.cpu_available or self.sample.gpu_available):
                return ProviderOutput(self.name, None, "CPU/GPU metrics unavailable")
            frame = self.frame(
                metric, cool_c, hot_c, palette, direction,
                dark_edge_compensation, custom_palette,
            )
            return ProviderOutput(self.name, frame, "CPU left, GPU right")
        if not self.sample.gpu_available:
            return ProviderOutput(self.name, None, "GPU metrics unavailable")
        frame = self.frame(
            metric, cool_c, hot_c, palette, direction,
            dark_edge_compensation, custom_palette,
        )
        return ProviderOutput(self.name, frame, "GPU load and temperature")
