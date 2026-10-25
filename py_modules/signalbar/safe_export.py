"""Private local support/backups; no symlink traversal or fixed temporary file."""
import os
import secrets
import stat
from pathlib import Path


def write_private_bytes(path, data):
    target = Path(path).absolute()
    parent = target.parent
    # The nearest existing ancestor determines the user for newly created Documents.
    ancestor = parent
    while not ancestor.exists(): ancestor = ancestor.parent
    info = ancestor.lstat()
    if not stat.S_ISDIR(info.st_mode): raise ValueError('Unsafe export directory')
    owner = info.st_uid, info.st_gid
    # For an existing root-owned Documents prefer its user's home owner.
    home = os.environ.get('DECKY_USER_HOME')
    if home and parent == Path(home).absolute() / 'Documents':
        user = Path(home).lstat(); owner = user.st_uid, user.st_gid
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(target.anchor, flags)
    traversed = Path(target.anchor)
    try:
        for component in parent.parts[1:]:
            traversed = traversed / component
            created = False
            try: os.mkdir(component, 0o700, dir_fd=directory); created = True
            except FileExistsError: pass
            child = os.open(component, flags, dir_fd=directory)
            if os.geteuid() == 0:
                if created:
                    os.fchown(child, *owner)
                elif home and parent == Path(home).absolute()/'Documents' and traversed == parent:
                    # Repair only a former root-owned Documents leaf, never its parents.
                    existing = os.fstat(child)
                    if existing.st_uid == 0 and owner[0] != 0: os.fchown(child, *owner)
            os.close(directory); directory = child
        try:
            existing = os.stat(target.name, dir_fd=directory, follow_symlinks=False)
            if not stat.S_ISREG(existing.st_mode): raise ValueError('Unsafe export destination')
        except FileNotFoundError: pass
        name = '.' + target.name + '.' + secrets.token_hex(12) + '.tmp'
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, 'wb') as stream:
                if os.geteuid() == 0: os.fchown(stream.fileno(), *owner)
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
            os.replace(name, target.name, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            try: os.unlink(name, dir_fd=directory)
            except FileNotFoundError: pass
    finally: os.close(directory)
    return str(target)
