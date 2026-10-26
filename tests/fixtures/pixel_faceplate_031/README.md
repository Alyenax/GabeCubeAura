# Pinned Pixel Faceplate test fixture

Copyright (c) 2026, Eli Hodapp. BSD-3-Clause; see the accompanying `LICENSE`.
These are test-only copies, not runtime modules and not a forked plugin.

Source: https://github.com/hodapp/pixel-faceplate/tree/61b4f263d28e556f3d66dfa3376fbb4f08ca2665/py_modules/pixelface

Version: 0.3.1. The four Python files are unchanged byte-for-byte:

| File | Upstream Git blob SHA |
| --- | --- |
| handoff.py | d741d497a566edfbbbdbf30a033d8a3e08a89045 |
| protocol.py | 14103953759977f2b29298fe7dc95d08d67c52db |
| transport.py | e7cb91171bd37193e12b087fa72bc3b07fe703ca |
| service.py | e31dd2b05566ce59c67d4ba6e76a92894659e3c4 |

`test_pixel_faceplate_serial.py` enforces these hashes. Test harnesses replace
artwork providers, USB discovery and polling time explicitly; they do not
rewrite the upstream ownership or tty-locking implementations. See
`docs/PIXEL_FACEPLATE_HANDOFF.md` for test commands and validation limits.
