# GabeCubeAura 1.6.1-beta.3

### Fixed

- Reduce the GIF payload for Weather and Dashboard, including animated artwork behind Dashboard. The decoded pixels, frame timing, and loop behaviour are unchanged. Static images and frames that do not benefit from compression keep their existing encoding.
- Regenerate cached Weather and Dashboard GIFs with the new encoding.

### Local diagnostics

- Add an optional **Faceplate GIF transfer test** under **Settings > Advanced > Diagnostics**. Open it with **Test**, choose a size and send one dim pattern at a time.
- Report the actual GIF size and distinguish a new confirmation, an already stored GIF, a refusal before image data, and a missing final confirmation. The results are included in **Export a local diagnostic**. No automatic upload or private sign-in is needed.

### What to test

For [#14](https://github.com/Alyenax/GabeCubeAura/issues/14) and [#15](https://github.com/Alyenax/GabeCubeAura/issues/15), try the Weather preview or Dashboard that previously failed. If the problem returns, use the optional size test described in the [beta guide](BETA_1.6.1.md), then export one diagnostic. Do not reset your settings just to run the test. Smaller files may help, but the reports do not yet establish a panel capacity, firmware fault or flash fault.

Existing settings and prepared artwork are kept. The Stable update channel remains the way back to 1.6.0 with current settings.
