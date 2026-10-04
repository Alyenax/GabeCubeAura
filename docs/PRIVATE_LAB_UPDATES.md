# Private Lab updates

Private Lab lets Alyenax install unpublished GabeCubeAura hardware builds from
the Steam Machine without copying each ZIP through a USB drive.

## Repository and permissions

- Repository: `Alyenax/GabeCubeAura-Lab`
- Visibility: private
- GitHub App installation: only this repository
- Repository permission: Contents, read-only
- Authentication: GitHub device flow
- Embedded credential: public GitHub App client ID only
- Client secret: none

The device flow also sends the numeric repository ID when exchanging the code.
This requests a single-repository token scope in addition to the GitHub App
installation boundary.

## On-device flow

1. Open **GabeCubeAura > Updates**.
2. Select **Private Lab** as the update channel.
3. Choose **Connect GitHub**.
4. Open `https://github.com/login/device` and enter the displayed code.
5. Return to GabeCubeAura. It detects the authorization automatically. Choose
   **Finish connection** only to check immediately.
6. Review, download, verify and explicitly install an available Lab build.

GabeCubeAura does not receive the GitHub password. Access tokens expire and are
refreshed through GitHub's supported refresh-token flow. **Disconnect Private
Lab** deletes the local authorization file.

## Local storage boundary

Authorization data is stored at:

```text
<Decky plugin runtime>/updates/private-auth.json
```

The file is created with mode `0600`. It is separate from `config.json`,
artwork caches and configuration exports. Public Stable and Beta checks do not
use it.

## Release contract

Private releases must:

- use a `vX.Y.Z-lab.N` tag;
- be marked as a GitHub prerelease;
- include `GabeCubeAura-vX.Y.Z-lab.N.zip`;
- include `SHA256SUMS` for that exact archive;
- contain matching package and backend versions.

Private assets are fetched through GitHub's authenticated release-assets API.
The bearer token is removed before following GitHub's signed cross-host asset
redirect. The existing HTTPS allowlist, size limits, ZIP path checks, manifest
checks, explicit confirmation and automatic rollback remain active.

## Bootstrap boundary

The installed GabeCubeAura build must already contain the GitHub App client ID
and Private Lab interface. This requires one final manual installation of that
bootstrap build. Later Lab builds can be delivered directly through the
private channel.
