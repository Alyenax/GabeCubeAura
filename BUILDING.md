# Building GabeCubeAura 1.5.1

Use Node.js with pnpm 9 and Python 3. Install Pillow for the image tests.

```sh
pnpm install --frozen-lockfile
pnpm typecheck
pnpm test:frontend
pnpm build
pnpm package
pnpm verify:release
```

Packaging writes `out/GabeCubeAura-v1.5.1.zip`, `out/GabeCubeAura.zip` and `out/SHA256SUMS`. Only `scripts/runtime-files.json` enters the installable ZIP; tests, build tools, source-only files and documentation demonstrations remain outside it. The update manifest identifies every runtime file by size and SHA-256. No user configuration, artwork library, credentials or caches are bundled.

The publication review in `licenses/faceplate-scope.json` records the approval for 1.5.0. Normal packaging and release verification require its cleared status; file-scope, provenance, legal-text and checksum checks remain enforced. Packaging itself never publishes a release.

`@decky/api` source and licence snapshots identify the wrapper incorporated into the frontend. The pnpm lockfile pins the dependencies; edit or replace the dependency before rebuilding to produce a modified wrapper. Host React and Decky UI implementations remain external.

Code uses GPL-3.0-only, with third-party terms preserved. The 197 identified original Faceplate graphics use CC BY-NC-SA 4.0. See `LICENSING.md`, `THIRD_PARTY_NOTICES.md` and `licenses/faceplate-assets.json`.
