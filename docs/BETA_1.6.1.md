# GabeCubeAura 1.6.1 beta

This is a public test release for weather after sleep and Faceplate image recovery. The stable release remains **1.6.0**. A test on an affected Faceplate is still needed to confirm the result.

## Install from 1.6.0

1. Open GabeCubeAura, then **Settings > Updates**.
2. In **Preferences**, set **Update channel** to **Beta**.
3. In **Update**, choose **Check now**, then **Download and verify** for **1.6.1-beta.1**.
4. Choose **Update and restart Decky** and confirm. After Decky restarts, reopen GCA and check that the installed version is **1.6.1-beta.1**.

The plugin downloads and verifies its archive itself. There is no manual ZIP installation or private GitHub authorization to complete. Choosing Beta alone does not confirm an installation.

## What to check

Use the display that was failing. For the weather issue, let the machine sleep and then resume normally. You do not need to run a separate diagnostic script or answer a questionnaire.

An explicit Off action in GCA remains respected at resume. Weather can refresh without turning the Faceplate on. Turn it on when you want to use it again.

A panel waiting for an image replacement can briefly be off while the replacement is checked. If restoration fails, GCA shows that it needs attention and limits repeated attempts. This is different from an intentional Off state. When **Resume stored picture** is available, it attempts only to turn the panel on with its existing content; a power acknowledgement cannot prove that the picture is visible or up to date.

This release does not prove that a firmware or flash problem has been repaired. The reason some devices reject GIF BEGIN commands is still under investigation.

## Send one local diagnostic

After reproducing the problem, open **Settings > Advanced > Diagnostics** and choose **Export a local diagnostic** once. Send **GabeCubeAura-diagnostic.json** with your GitHub issue comment by dragging it into the comment editor in your browser.

If saving the file fails, the same document remains visible. Choose **Copy diagnostic text** and paste it into the issue. If automatic copying is unavailable, select and copy the text directly. No second collection or separate test is required. You may review the document before sharing it.

The report includes installed version consistency, selected operating modes, available OS/kernel information, power intent, restoration and transfer stages, and weather scheduling facts. It does not include API keys or perform an automatic upload. Unknown firmware or flash health is labelled as unknown or unmeasured, rather than inferred from a black display.

## Return to 1.6.0

1. Open **Settings > Updates > Preferences** and change **Update channel** to **Stable**.
2. In **Update**, choose **Check now**. GCA offers the stable **1.6.0** even though its version number is lower.
3. Choose **Download and verify**, then **Update and restart Decky**, and confirm the return.
4. Check that the installed version is **1.6.0** and the channel remains **Stable**.

This route uses the stable release archive and keeps current settings, API keys and prepared media. Staying on Stable prevents the beta from being offered again. Returning to 1.6.0 also returns to its weather and recovery limitations.

**Return to the previous version** is a separate local-backup option. It restores the retained package and the settings/artwork snapshot from that backup, so choices made after the snapshot may be reverted. Use the Stable channel route above when you want to keep your current choices.

## Release contents

See the [changelog](../CHANGELOG.md). Diagnostics remain local in this beta. Private Lab media-provider experiments are not included.
