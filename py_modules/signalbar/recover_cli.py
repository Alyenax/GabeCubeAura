"""Explicit, pinned ZIP recovery using the plugin's real installer, not unzip.

Offline and prepare-only by default. It never downloads credentials, executes
archive code, edits preferences, or deletes modules. --apply deliberately
restarts Decky via an independent systemd worker; never invoked by the plugin.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .updates import (EXPECTED_ROOT, MAX_ARCHIVE_BYTES, _sha256_file, validate_and_stage_archive,
                      read_bundle_contract, UpdateError)
from .update_helper import _no_symlink_ancestors, _atomic_json, _read_json, snapshot_user_state, _validate_transaction


def prepare(archive, digest, version, active, runtime_dir, settings_path, user_root):
    paths = [Path(p).absolute() for p in (archive, active, runtime_dir, settings_path, user_root)]
    for path in paths: _no_symlink_ancestors(path)
    archive, active, runtime_dir, settings_path, user_root = paths
    if active.name != EXPECTED_ROOT or active.parent.name != 'plugins':
        raise UpdateError('recovery', 'Choose the existing homebrew/plugins/GabeCubeAura directory')
    if (settings_path.name != 'config.json' or settings_path.parent.name != EXPECTED_ROOT
            or user_root.name != 'gabecubeaura' or user_root.parent.name != 'share'):
        raise UpdateError('recovery', 'Use the actual GabeCubeAura config.json and share/gabecubeaura user-data directory')
    if (not archive.is_file() or archive.stat().st_size > MAX_ARCHIVE_BYTES
            or len(digest) != 64 or _sha256_file(archive) != digest.lower()):
        raise UpdateError('checksum', 'ZIP differs from the explicitly supplied SHA256SUMS digest')
    old = _read_json(active / 'package.json')
    plugin = _read_json(active / 'plugin.json')
    if old.get('name') != 'gabecubeaura' or plugin.get('name') != EXPECTED_ROOT:
        raise UpdateError('recovery', 'The existing installation is not GabeCubeAura')
    runtime = runtime_dir / 'updates'
    if (runtime / 'update-state.json').exists():
        state = _read_json(runtime / 'update-state.json')
        if state.get('pending_token'):
            raise UpdateError('busy', 'Finish or recover the existing installation transaction first')
    token = os.urandom(16).hex()
    stage_parent = runtime / 'staged' / token
    staged = validate_and_stage_archive(archive, stage_parent, version)
    snapshot = runtime / 'recovery' / token / 'snapshot'
    try:
        contract = read_bundle_contract(staged, version)
        snapshot_user_state(settings_path, user_root, snapshot)
        raw = {'schema': 1 if contract['legacy_plugin_only'] else 2, 'token':token,
            'from_version':old['version'], 'to_version':version, 'digest':digest.lower(),
            'active_dir':str(active), 'staged_dir':str(staged), 'runtime_root':str(runtime),
            'state_path':str(runtime/'update-state.json'), 'health_path':str(runtime/'health'/f'{token}.json'),
            'service':'plugin_loader.service', 'health_timeout':45}
        if raw['schema'] == 2:
            raw.update(components=[c['id'] for c in contract['components']], companion_root=str(user_root/'components'))
        # Code-only reinstall: user data stays live and is not restored over
        # edits made after preparation. Snapshot is retained for explicit recovery.
        _validate_transaction(raw)
        if active.stat().st_dev != staged.stat().st_dev:
            raise UpdateError('recovery', 'Active and staged code must be on the same filesystem for atomic exchange')
        transaction = runtime/'transactions'/f'{token}.json'
        _atomic_json(transaction, raw)
        return raw, transaction
    except Exception:
        shutil.rmtree(stage_parent, ignore_errors=True)
        # Snapshot belongs to this random token only. Keep completed backups.
        if snapshot.exists(): shutil.rmtree(snapshot)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--active-dir', required=True, type=Path)
    parser.add_argument('--runtime-dir', required=True, type=Path, help="Actual DECKY_PLUGIN_RUNTIME_DIR for GabeCubeAura")
    parser.add_argument('--settings-file', required=True, type=Path)
    parser.add_argument('--user-root', required=True, type=Path)
    parser.add_argument('--apply', action='store_true', help='Explicitly replace code and restart Decky; default only prepares')
    args = parser.parse_args(argv)
    try:
        raw, transaction = prepare(args.archive, args.sha256, args.version, args.active_dir,
                                    args.runtime_dir, args.settings_file, args.user_root)
        print(json.dumps({'prepared_transaction':str(transaction),'version':args.version,
                          'sha256':args.sha256,'data':'unchanged','installed':False}))
        if args.apply:
            runner = shutil.which('systemd-run')
            if not runner: raise UpdateError('helper_unavailable','systemd-run is required to apply on SteamOS')
            # zipapps cannot be copied as .py. Copy the trusted helper source
            # from this tool's package, never from unverified archive code.
            import pkgutil
            helper = Path(raw['runtime_root'])/'helpers'/f"update-helper-{raw['token']}.py"
            helper.parent.mkdir(parents=True, exist_ok=True)
            helper.write_bytes(pkgutil.get_data('signalbar','update_helper.py'))
            subprocess.run([runner, '--collect', '--no-block', '--property=Type=exec',
                            '--property=TimeoutStartSec=180', f"--unit=gabecubeaura-recovery-{raw['token'][:12]}",
                            sys.executable, str(helper), str(transaction)], check=True, timeout=15)
            print('Independent recovery started. Check update-state.json; a healthy-start failure restores the previous code.')
        return 0
    except (UpdateError, OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__': raise SystemExit(main())
