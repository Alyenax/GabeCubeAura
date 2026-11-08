### Local diagnostics

- Expand the one-action local report with bounded process/service observations, serial-port holders, available USB descriptors and runtime power-management settings, recent Linux USB events and storage/permission facts.
- Capture a small passive process/USB observation when a transfer fails, at most once per second, retaining up to eight observations until the plugin restarts. Full command lines, personal paths and raw kernel messages are excluded. Nothing is uploaded automatically.
- Distinguish newly acknowledged transfers, stored-content reuse and BEGIN refusals by size. A reused image, bridge revision or descriptor power budget is not evidence of panel capacity, actual power draw, cable quality or flash health.
- Mark inaccessible processes, partial scans, unavailable service buses and missing measurements explicitly. Events not attributable to the Faceplate stay labelled as host USB events.

### Fixed

- Keep live transfer and restoration evidence consistent between diagnostic sections. Missing observations no longer become false negative flags.
- Preserve validated kernel versions and controlled technical field names while continuing to remove credentials and personal paths.

### Testing and recovery

- Keep beta 1 weather/recovery fixes, existing settings and the current GIF transport. Fixed minute remains the default only for new clock configurations; saved Conservative settings are preserved.
- Document the optional GCA reset after saving the report and backing up data to keep. A complete reset deletes GCA settings, saved content and the SteamGridDB key; it does not reset panel firmware or stop an external service.
- Continue investigating [#14](https://github.com/Alyenax/GabeCubeAura/issues/14) and [#15](https://github.com/Alyenax/GabeCubeAura/issues/15). This beta gathers evidence and does not claim to repair flash memory or resolve every BEGIN refusal. No additional transfer is triggered by exporting the report.

Install through **Settings > Updates > Preferences > Beta**, then check, download and verify **1.6.1-beta.2**, and confirm the update. To return with current settings and media, choose **Stable** and install **1.6.0** through the same flow. See the [beta guide](https://github.com/Alyenax/GabeCubeAura/blob/v1.6.1-beta.2/docs/BETA_1.6.1.md).
