"""Conservative host admission envelope, not optical or firmware proof.

Identical policy vendored in both plugins. Derived from the Lab148 traces:
297 chunks / 147518 bytes exceeded 17.5s; 68931 bytes took 8.2s.
No cached-CRC shortcut may relax admission. TV readiness remains bounded.
"""
import math

MODEL = "jsaux-measured-envelope-v2"
SYNC_MAX_BYTES = 80 * 1024
SETUP_MS = 500
REVEAL_MARGIN_MS = 250
CHUNK_ALLOWANCE_MS = 45
END_BASE_SECONDS = 1.25
END_PER_4K_SECONDS = .20
END_MIN_SECONDS = 1.50
END_MAX_SECONDS = 10.0


def end_timeout(size):
    blocks = max(1, (max(0, int(size)) + 4095) // 4096)
    return min(END_MAX_SECONDS, max(END_MIN_SECONDS,
               END_BASE_SECONDS + blocks * END_PER_4K_SECONDS))


def transfer_ms(size):
    size = int(size)
    if size <= 0:
        raise ValueError("invalid GIF transfer size")
    chunks = math.ceil(size / 498)
    return math.ceil(SETUP_MS + REVEAL_MARGIN_MS
                     + (size + chunks * 10 + 40) * .01
                     + chunks * CHUNK_ALLOWANCE_MS + end_timeout(size) * 1000)


def admits(size, remaining_ms):
    return (0 < int(size) <= SYNC_MAX_BYTES
            and transfer_ms(size) <= max(0, float(remaining_ms)))
