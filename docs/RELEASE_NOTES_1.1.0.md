# GabeCubeAura 1.1.0

GabeCubeAura can now check, download and install future stable releases from
inside the plugin. Version 1.0.0 users still install this release once through
Decky Developer settings. After that bootstrap, the new Updates page handles
later releases.

## Direct updates

- Checks only the official `Alyenax/GabeCubeAura` GitHub releases.
- Runs an optional background check once a day.
- Shows at most one Decky notification for each available version and waits
  until Home when a game is running.
- Keeps installation manual, with a separate download step and a final
  confirmation showing the installed and target versions.
- Keeps settings and artwork caches during updates and rollbacks.

## Package safety

The updater keeps HTTPS certificate and hostname verification enabled. Before
installation it checks the GitHub metadata, expected asset name, compressed
and extracted sizes, SHA256, ZIP paths, symbolic links, duplicate files,
required manifests, plugin identity and exact target version.

Decky is not stopped during download or validation. Once the package is ready,
an independent helper stops Decky, swaps the verified directory and starts
Decky again. The new backend has 45 seconds to acknowledge a healthy startup.
If it does not, the helper restores the previous version and starts Decky once
more without entering a restart loop.

## Installation

1. Install [Decky Loader](https://decky.xyz/) if needed.
2. Download `GabeCubeAura-v1.1.0.zip` from this release.
3. In **Decky > Settings > General**, enable **Developer mode** if the
   **Developer** page is not visible.
4. Open **Decky > Settings > Developer** and choose
   **Install Plugin from ZIP File** under **Third-Party Plugins**.
5. Select the ZIP without extracting it.

The release also provides `GabeCubeAura.zip` as a fixed-name recovery download
and `SHA256SUMS` for both archives.

## Verification scope

Automated coverage includes release discovery, stable version filtering,
notification deduplication, checksum enforcement, malicious ZIP rejection,
package validation, successful swaps, health timeout, rollback and persistence
of update preferences. Build validation covers TypeScript, frontend tests,
backend tests, the production bundle, ZIP structure and checksums.

The isolated Update lab is available only in local test builds. It does not
appear in the stable v1.1.0 interface.
