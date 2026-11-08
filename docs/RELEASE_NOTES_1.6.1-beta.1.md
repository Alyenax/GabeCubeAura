# GabeCubeAura 1.6.1-beta.1

This public beta improves weather refresh after system sleep and makes Faceplate recovery failures easier to understand and report. Stable remains **1.6.0**.

## Fixed

- Use sleep-aware weather freshness and request scheduling, request fresh data after resume and discard responses from an older request generation.
- Respect a Faceplate switched off explicitly in GCA while still allowing weather data to refresh.
- Stop repeating the same rejected image restoration. Show the failure and offer **Resume stored picture** when a power-only recovery is available.
- Show distinct status messages for intentional Off, restoration in progress and restoration needing attention.

## Local diagnostics

One **Export a local diagnostic** action creates a JSON document with version consistency, key installed-file checks, available OS/kernel information, power intent, transfer stages and weather timing. The same document can be copied if the file cannot be saved. No automatic upload or private GitHub authorization is involved.

## Install or return to Stable

In **Settings > Updates > Preferences**, select **Beta**. Under **Update**, choose **Check now**, **Download and verify**, then **Update and restart Decky** and confirm.

To return, select **Stable** and repeat those steps for **1.6.0**. The stable archive keeps your current settings, keys and prepared media. Returning also brings back 1.6.0's known limitations. Leave the channel on Stable to stay on that release.

[Installation, testing and diagnostic instructions](https://github.com/Alyenax/GabeCubeAura/blob/v1.6.1-beta.1/docs/BETA_1.6.1.md)

## Still under investigation

This beta does not establish the cause of GIF BEGIN refusals or flash failures. It adds evidence and recovery handling for [#14](https://github.com/Alyenax/GabeCubeAura/issues/14) and [#15](https://github.com/Alyenax/GabeCubeAura/issues/15), and a weather fix to test for [#16](https://github.com/Alyenax/GabeCubeAura/issues/16). Confirmation on the affected machines is still needed.
