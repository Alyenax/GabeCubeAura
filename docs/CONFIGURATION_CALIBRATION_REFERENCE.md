# Local configuration exports and calibration references

Open **Settings → Advanced → Data → Export configuration JSON**. The export is written locally, with progress, a saved path or a retryable error. On a standard SteamOS installation the file is `Documents/GabeCubeAura-configuration.json`; the UI displays the actual path. Exporting again replaces that JSON. No account, private connection or upload is required.

The compatible `schema_version: 1` configuration block contains supported global settings and per-game display, artwork and launch profiles. Its portable presentation flattens an active display preset into custom settings. The additional `calibration_reference` preserves the saved preset, all supported settings and independent-store metadata so a later calibration review can distinguish the original choices from that import block.

| Source | Included reference |
| --- | --- |
| Settings | Every supported saved setting, nested value and per-game profile |
| Faceplate preferences | Home/game routes and renderer choices |
| Ambience profiles | Named recipes, including inactive profiles |
| Artwork library | Selections and portable preparation controls, without media bytes |
| Support | The compatibility support preference; this build does not upload diagnostics |

Coverage names each collected source and supported settings key. A missing source, corrupt metadata or an oversized reference fails explicitly. Credentials, API keys, live weather, running timers, caches and connected-device telemetry are excluded. A chosen weather location and other personal configuration choices may be present; review the file before sharing it.

The reference schema is `gabecubeaura-configuration-baseline-v1`, with purpose `future-public-calibration-reference` and `applied_as_defaults: false`. It is evidence for consultation. Exporting does not change defaults, complete setup, prepare new artwork or apply a new configuration. The standard JSON importer restores its documented global settings and per-game profiles; it does not automatically restore the extra independent stores from the reference.

To keep media separately, use **Export a saved creation** in Advanced → Data with a connected Faceplate and an active saved creation. Select it, then **Export creation locally**. The ZIP contains the prepared GIF, available native Dashboard background and portable creation metadata. The JSON settings importer accepts configuration JSON, not a creation ZIP.

For support, use **Export a local diagnostic** in Advanced → Diagnostics. This produces a separate redacted local report. Sharing a configuration or creation export is a deliberate action and has different privacy implications. Automatic private delivery is unavailable in this build.
