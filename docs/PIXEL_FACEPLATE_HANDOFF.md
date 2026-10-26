# Pixel Faceplate coexistence

## Contract

GabeCubeAura implements the handoff proposed by Eli Hodapp in
[PR #5](https://github.com/Alyenax/GabeCubeAura/pull/5). The existing
`faceplate-claim.json` format remains unchanged: `plugin` is `GabeCubeAura`
and `pid` identifies its backend. Pixel Faceplate reads this file in the
Decky settings hierarchy, checks the live process, closes its serial link
and stops sending when GCA claims the panel. Both transports also take a
nonblocking exclusive `flock` on the tty. The claim is cooperative signalling,
not a replacement for that kernel lock.

Support enabled and display powered on are different states. Powering the
matrix off or suspending GCA must not release the reservation and let a second
plugin wake it. Disabling Faceplate support or unloading GCA releases it.

## 2026-10-26 corrections

- Synchronize the claim after setup, configuration import, all reset paths and
  the explicit support toggle, including post-commit errors and rollback.
- Run mutation and final synchronization in the same executor job so cancellation
  of the awaiting RPC does not leave the claim stale.
- Publish before the engine starts; release if engine startup raises. An early
  RPC without an initialized settings directory defers to normal startup sync.
- Serialize synchronization with shutdown and prevent late callbacks from
  reclaiming ownership after unload.
- Publish the nonsecret plugin/PID file with mode `0644`, even under umask `077`,
  so the unprivileged Pixel Faceplate backend can read a root-written claim.
  Do not broaden settings-directory or credential permissions. Parent folders
  must already be accessible to the Decky user.
- Replace the predictable temporary pathname with a unique temporary file and
  clean it on failure. Keep atomic replacement and PID-bound release.

No brightness policy, flash budget, renderer, serial protocol, release version,
or installed release archive is changed by this source correction.

## Reproducible tests

From the repository root on Linux with Python 3.10 or newer:

```sh
PYTHONPATH=py_modules:tests/backend python -m unittest -v \
  test_faceplate_claim test_pixel_faceplate_handoff test_pixel_faceplate_serial
```

The cross-UID test requires an isolated root-capable Linux environment with the
checkout readable by UID 65534. Without root, that test is skipped and serial
actors run under one UID. No hardware is needed; tests only touch temporary
files and a newly allocated PTY. Do not run against a physical serial device.

Validation on 2026-10-26: **37 tests passed, no skips**, on Linux/Python 3.13.
This includes the three original PR tests, 27 lifecycle/claim/process tests and
seven serial/integrity tests. The serial scenarios include 20 ownership
round trips, both startup orders, kernel rejection of the competing opener,
peer silence during GCA ownership, release/resume and recovery after SIGKILL.

The peer fixture is byte-identical to `hodapp/pixel-faceplate` 0.3.1 commit
`61b4f263d28e556f3d66dfa3376fbb4f08ca2665`; the integrity test checks its Git blob
IDs. GCA was audited against `a8252dd504088dfda65279cb0af0117f25c08438` before
these corrections. See the fixture README for provenance and licensing.

### What is real and what is simulated

Real: production claim helper and Plugin RPC bodies; upstream peer handoff,
service scheduling logic and serial transport; separate Linux processes,
root/non-root permissions, `/proc`, tty opens, `termios`, kernel `flock`,
process death and DY/CRC-framed traffic on a PTY.

Simulated: engine/provider objects and settings transactions in lifecycle tests;
USB discovery, artwork providers, elapsed polling time and firmware ACKs in
serial tests. The serial GCA actor extracts the unchanged production
`Link.__init__`, `open` and `close` methods, without the ownership broker, then
writes a control frame only after acquiring that real lock. It does not run
the full GCA rendering or GIF-upload pipeline.

No physical JSAUX/CH340, installed SteamOS/Decky session, optical output,
physical sleep/resume, USB reconnect, long-duration soak, full repository test
suite or frontend/release build was validated. These tests demonstrate the
specified software handoff, not blanket hardware certification.

### Polling is not instantaneous

Pixel Faceplate's `HANDOFF_POLL = 30` does not impose a 30-second upper bound:
its clock mode can sleep until the next minute (60.5 seconds at an exact minute
in the deterministic test). Current work or system suspension may add delay.
The existing serial lock prevents the competing cooperative writer from
interleaving packets while it waits. No polling cadence was changed upstream.
