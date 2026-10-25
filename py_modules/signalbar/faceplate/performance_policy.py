# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Faceplate telemetry only; native LED telemetry is independent."""
import math

CONSENT_REVISION = "faceplate-performance-unlimited-v1"
DEFAULT_INTERVAL_SECONDS = 5


def interval_seconds(value):
    try:
        number = float(value)
        if isinstance(value, bool) or not math.isfinite(number):
            raise ValueError("Invalid interval")
        return max(1, min(60, int(round(number))))
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_INTERVAL_SECONDS
