# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Private JSAUX runtime provisioning shared by endpoint and physical owner.

Only the canonical, backend-owned legacy 0755 leaf can be tightened. No
recursive repair, ownership change, endpoint deletion or device access occurs.
This is a same-backend trust boundary, not isolation between root plugins.
"""
from __future__ import annotations

import errno
import os
from pathlib import Path
import stat

CANONICAL_RUNTIME = Path('/run/decky/jsaux-broker/v1')
_DIRECTORY_FLAGS = (os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0)
                    | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0))


class RuntimeSecurityError(PermissionError):
    """Bounded metadata only; no source exception text or credential paths."""
    def __init__(self, reason, component, uid, info=None, expected_mode=None, native_errno=None):
        super().__init__(native_errno or errno.EACCES, 'JSAUX runtime unavailable')
        self.diagnostic = {'reason': reason, 'component': component,
                           'effective_uid': uid, 'errno': native_errno}
        if info is not None:
            self.diagnostic.update(owner_uid=info.st_uid, owner_gid=info.st_gid,
                                   mode=format(stat.S_IMODE(info.st_mode), '04o'))
        if expected_mode is not None:
            self.diagnostic['expected_mode'] = format(expected_mode, '04o')


def _identity(expected_uid):
    uid = os.geteuid()
    if expected_uid is not None and int(expected_uid) != uid:
        raise RuntimeSecurityError('identity-mismatch', 'backend', uid)
    return uid


def _no_symlinks(path, uid):
    for component in (path, *path.parents):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise RuntimeSecurityError('symlink', 'runtime-hierarchy', uid, info)


def _directory_info(fd, uid, component, private=False):
    info = os.fstat(fd)
    mode = stat.S_IMODE(info.st_mode)
    if not stat.S_ISDIR(info.st_mode):
        raise RuntimeSecurityError('not-directory', component, uid, info)
    if info.st_uid != uid:
        raise RuntimeSecurityError('owner-mismatch', component, uid, info)
    if (mode != 0o700 if private else bool(mode & 0o022)):
        raise RuntimeSecurityError('mode-mismatch', component, uid, info,
                                   0o700 if private else None)
    return info


def _same_path(path, fd, uid, component):
    current, opened = path.lstat(), os.fstat(fd)
    if (not stat.S_ISDIR(current.st_mode)
            or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)):
        raise RuntimeSecurityError('directory-replaced', component, uid, current)


def _canonical(target, uid):
    # /run already exists on SteamOS. Derive the anchor to permit real-UID
    # isolated fixtures without ever creating or changing /run in tests.
    anchor = CANONICAL_RUNTIME.parents[2]
    _no_symlinks(anchor, uid)
    opened = []
    component = 'runtime-anchor'
    try:
        fd = os.open(anchor, _DIRECTORY_FLAGS)
        opened.append((anchor, fd, component))
        _directory_info(fd, uid, component)
        for name in ('decky', 'jsaux-broker', 'v1'):
            component = {'decky': 'decky-directory', 'jsaux-broker': 'broker-directory',
                         'v1': 'runtime-directory'}[name]
            parent_path, parent_fd, _ = opened[-1]
            try:
                os.mkdir(name, 0o700, dir_fd=parent_fd)
            except FileExistsError:
                pass
            fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
            path = parent_path / name
            opened.append((path, fd, component))
            info = _directory_info(fd, uid, component)
            _same_path(path, fd, uid, component)
            if name == 'v1':
                mode = stat.S_IMODE(info.st_mode)
                if mode == 0o755:
                    # Narrow migration for Lab138 mkdir(parents=True): only
                    # this inode, verified by descriptor, becomes more private.
                    for entry_path, entry_fd, label in opened:
                        _same_path(entry_path, entry_fd, uid, label)
                    try:
                        os.fchmod(fd, 0o700)
                    except OSError as error:
                        raise RuntimeSecurityError('filesystem-error', component, uid,
                                                   info, 0o700, error.errno) from None
                _directory_info(fd, uid, component, private=True)
        for path, fd, label in opened:
            _same_path(path, fd, uid, label)
        return target
    except RuntimeSecurityError:
        raise
    except OSError as error:
        raise RuntimeSecurityError('filesystem-error', component, uid,
                                   native_errno=error.errno) from None
    finally:
        for _, fd, _ in reversed(opened):
            os.close(fd)


def _private(target, uid, component):
    if not target.is_absolute():
        raise RuntimeSecurityError('absolute-path-required', component, uid)
    _no_symlinks(target, uid)
    fd = None
    try:
        target.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(target, _DIRECTORY_FLAGS)
        _directory_info(fd, uid, component, private=True)
        _same_path(target, fd, uid, component)
        _no_symlinks(target, uid)
        return target
    except RuntimeSecurityError:
        raise
    except OSError as error:
        raise RuntimeSecurityError('filesystem-error', component, uid,
                                   native_errno=error.errno) from None
    finally:
        if fd is not None:
            os.close(fd)


def provision_runtime(runtime_dir=None, expected_uid=None):
    """Provision before any ownership claim; repair only the safe legacy leaf."""
    uid = _identity(expected_uid)
    target = CANONICAL_RUNTIME if runtime_dir is None else Path(runtime_dir)
    if not target.is_absolute():
        raise RuntimeSecurityError('absolute-path-required', 'runtime-directory', uid)
    if target == CANONICAL_RUNTIME:
        return _canonical(target, uid)
    return _private(target, uid, 'runtime-directory')


def provision_ownership(root):
    uid = _identity(None)
    target = Path(root)
    if target == CANONICAL_RUNTIME / 'ownership':
        provision_runtime()
    return _private(target, uid, 'ownership-directory')
