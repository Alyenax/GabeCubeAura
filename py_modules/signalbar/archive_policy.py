"""Local, non-negotiable install limits (stdlib only, no remote overrides)."""

from pathlib import Path
import shutil
import struct

MIB = 1024 * 1024
MAX_ARCHIVE_BYTES = 1024 * MIB
MAX_UNCOMPRESSED_BYTES = 4096 * MIB
MAX_ARCHIVE_ENTRIES = 32768
MAX_CENTRAL_DIRECTORY_BYTES = 16 * MIB
MAX_MANIFEST_BYTES = 16 * MIB
CHUNK_BYTES = 64 * 1024
DISK_RESERVE_BYTES = 256 * MIB


def check_zip_envelope(path):
    """Bound ZIP metadata before ZipFile allocates its complete entry list.

    Our 1-GiB ZIP / 4-GiB extraction and 32768-entry policy needs neither ZIP64 nor split ZIPs.
    Permit comments, but no opaque trailing payload after the end record.
    """
    size = Path(path).stat().st_size
    with Path(path).open('rb') as stream:
        stream.seek(max(0, size - 65557))
        tail = stream.read(65557)
    offset = tail.rfind(b'PK\x05\x06')
    if offset < 0 or len(tail) - offset < 22:
        raise ValueError('ZIP end record missing')
    _, disk, cd_disk, disk_entries, entries, cd_size, cd_offset, comment = struct.unpack_from('<4s4H2LH',tail,offset)
    if (offset + 22 + comment != len(tail) or disk or cd_disk
            or not 0 < entries <= MAX_ARCHIVE_ENTRIES or disk_entries != entries
            or cd_size > MAX_CENTRAL_DIRECTORY_BYTES or cd_offset + cd_size > size - 22
            or b'PK\x06\x07' == tail[max(0,offset-20):max(0,offset-16)]):
        raise ValueError('ZIP metadata exceeds local bounds or uses unsupported ZIP64/split layout')


def require_space(path, needed):
    """Check the actual destination filesystem, before creating large files.

    Existing archive/active code already consume space. `needed` counts only
    additional allocations, including copies/snapshots, not rename backups.
    This is a preflight, not a reservation; ENOSPC must still roll back safely.
    """
    parent = Path(path)
    while not parent.exists():
        parent = parent.parent
    if shutil.disk_usage(parent).free < needed + DISK_RESERVE_BYTES:
        raise OSError("Insufficient free disk space for staging and recovery")
