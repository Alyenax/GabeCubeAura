# GabeCubeAura 1.6.1 beta

Beta 2 expands the local diagnostic for Faceplate transfer refusals. It keeps beta 1 weather and recovery fixes, existing settings and the current transfer protocol. The stable release remains **1.6.0**. A test on an affected Faceplate is still needed to confirm the result.

## Install from 1.5.1, 1.6.0 or beta 1

1. Open GabeCubeAura, then **Settings > Updates**.
2. In **Preferences**, set **Update channel** to **Beta**.
3. In **Update**, choose **Check now**, then **Download and verify** for **1.6.1-beta.2**.
4. Choose **Update and restart Decky** and confirm. After Decky restarts, reopen GCA and check that the installed version is **1.6.1-beta.2**.

The plugin downloads and verifies its archive itself. There is no manual ZIP installation or private GitHub authorization to complete. Choosing Beta alone does not confirm an installation.

## What to check

Use the display that was failing. For the weather issue, let the machine sleep and then resume normally. You do not need to run a separate diagnostic script or answer a questionnaire.

An explicit Off action in GCA remains respected at resume. Weather can refresh without turning the Faceplate on. Turn it on when you want to use it again.

A panel waiting for an image replacement can briefly be off while the replacement is checked. If restoration fails, GCA shows that it needs attention and limits repeated attempts. This is different from an intentional Off state. When **Resume stored picture** is available, it attempts only to turn the panel on with its existing content; a power acknowledgement cannot prove that the picture is visible or up to date.

This release does not prove that a firmware or flash problem has been repaired. The reason some devices reject GIF BEGIN commands is still under investigation.

## Send one local diagnostic

After reproducing the problem, open **Settings > Advanced > Diagnostics** and choose **Export a local diagnostic** once. Send **GabeCubeAura-diagnostic.json** with your GitHub issue comment by dragging it into the comment editor in your browser.

If saving the file fails, the same document remains visible. Choose **Copy diagnostic text** and paste it into the issue. If automatic copying is unavailable, select and copy the text directly. No second collection or separate test is required. You may review the document before sharing it.

The report includes version consistency, selected operating modes, OS/kernel information, power intent, restoration and transfer stages, weather scheduling, available service/process categories, serial-port holders and recent Linux USB events. Failed transfers capture a short passive process/USB observation while the failure is handled, limited to one per second and eight observations in the current plugin session. Exporting does not send an image or stop a process.

USB descriptors and runtime power-management settings are observations, not measurements of voltage, current or cable quality. Host USB events without a matching device name are marked as unattributed. Process scans are time-limited; inaccessible processes or user service buses remain explicitly incomplete or unavailable. A USB bridge revision is not the panel revision. Confirmed new transfers, stored reuse and BEGIN refusals are recorded separately; no upload capacity or flash health is inferred.

Only process categories and PIDs are exported, not full command lines, personal paths or raw kernel logs. API keys are excluded and nothing is uploaded automatically. Keep GCA running after the failure until the report is exported so the in-memory failure observations are retained.

## Optional reset after keeping the report

A reset is optional, not required to export diagnostics. First save the report and use the configuration and creation backup controls for anything you want to keep. Then open **Settings > Advanced > Data** and choose **Reset to defaults** if you want a clean GCA configuration. Read and confirm the deletion notice: it removes GCA settings, saved content and the SteamGridDB key. Keep the exported report outside GCA's data directories.

**Reset settings only** keeps keys and saved creations and is a less destructive alternative. Neither reset repairs or reflashes the panel, changes a cable, or guarantees that another background application has stopped. If you try a reset and the problem remains, export one new report afterwards. There is no need to keep retrying failing uploads.

## What happens after the report

The next step is to compare process ownership at failure, USB reset/disconnect timing, power intent, installed files and accepted/refused sizes. That determines whether to address a competing service, USB/power behaviour, stale configuration or transfer compatibility. Different panel revisions or storage conditions remain hypotheses; beta 2 does not claim a hardware repair or change the transport to test that theory.

## Return to 1.6.0

1. Open **Settings > Updates > Preferences** and change **Update channel** to **Stable**.
2. In **Update**, choose **Check now**. GCA offers the stable **1.6.0** even though its version number is lower.
3. Choose **Download and verify**, then **Update and restart Decky**, and confirm the return.
4. Check that the installed version is **1.6.0** and the channel remains **Stable**.

This route uses the stable release archive and keeps current settings, API keys and prepared media. Staying on Stable prevents the beta from being offered again. Returning to 1.6.0 also returns to its weather and recovery limitations.

**Return to the previous version** is a separate local-backup option. It restores the retained package and the settings/artwork snapshot from that backup, so choices made after the snapshot may be reverted. Use the Stable channel route above when you want to keep your current choices.

## Release contents

See the [changelog](../CHANGELOG.md). Diagnostics remain local in this beta. Private Lab media-provider experiments are not included.
