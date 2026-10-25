# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Temporary manual private creation retrieval. No automatic collection or source downloads."""
import hashlib
import io
import json
from pathlib import Path
import zipfile

from .coordinator import validate_gif
from .steamgriddb import MAX_GIF_BYTES, DASHBOARD_PACK_MAX_FRAMES, DASHBOARD_PACK_REVISION

MAX_ARCHIVE_BYTES = 4 * 1024 * 1024
FRAME_BYTES = 64 * 54 * 3
# Only portable preparation data, no URLs, credentials or local paths.
MANIFEST_KEYS = (
    'schema','matrix_policy','matrix_components','appid','asset_id','mode','ready',
    'animation_style','source_variant','animated','author','asset_kind','source_width','source_height',
    'crop_axis','crop_x','crop_y','saturation','brightness','art_style','logo_position','logo_scale',
    'loop_cleanup','loop_original_frames','loop_trimmed_frames','loop_trimmed_ms',
    'frames','peak_load','sha256','source_sha256','dashboard_pack_frames','dashboard_pack_sha256',
    'dashboard_pack_revision','dashboard_treatment','dashboard_compression','dashboard_show_clock',
    'dashboard_clock_choice','dashboard_clock_size','dashboard_show_status_rail',
    'dashboard_show_session','dashboard_show_battery','prepared_at',
)


def _read(path, root, limit):
    path, root = Path(path), Path(root)
    if any(p.is_symlink() for p in (path, *path.parents) if p == root or root in p.parents):
        raise ValueError('Cannot archive linked artwork files')
    if root.resolve() not in path.resolve(strict=True).parents:
        raise ValueError('Artwork is outside the library')
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if not data or len(data) > limit:
        raise ValueError('Artwork exceeds the creation archive limit')
    return data


def creation_archive(library, appid, mode, expected_sha):
    """Freeze the selected active variant, verify every byte, then return one ZIP."""
    appid = int(appid)
    if appid <= 0 or mode not in {'static','animated','pan'} or not expected_sha:
        raise ValueError('Choose an active saved creation')
    root = library._prepared_root(appid, mode)
    active = json.loads(_read(library.artwork_root / str(appid) / 'active.json', library.artwork_root, 65536))
    if active.get('schema') != 1 or active.get('appid') != appid or active.get('mode') != mode:
        raise ValueError('The active creation changed. Select it again.')
    manifest = json.loads(_read(root / 'manifest.json', library.artwork_root, 65536))
    data = _read(root / 'faceplate.gif', library.artwork_root, MAX_GIF_BYTES)
    if (manifest.get('schema') != 2 or manifest.get('appid') != appid or manifest.get('mode') != mode
            or manifest.get('ready') is not True or manifest.get('sha256') != expected_sha
            or hashlib.sha256(data).hexdigest() != expected_sha):
        raise ValueError('The saved creation changed. Select it again.')
    validate_gif(data)
    files = {'faceplate.gif': data}
    if manifest.get('dashboard_pack'):
        count = int(manifest.get('dashboard_pack_frames', 0))
        if (manifest.get('dashboard_pack') != 'artwork-dashboard.rgb' or not 1 <= count <= DASHBOARD_PACK_MAX_FRAMES
                or manifest.get('dashboard_pack_revision') != DASHBOARD_PACK_REVISION):
            raise ValueError('This creation needs to be prepared again for Dashboard')
        pack = _read(root / 'artwork-dashboard.rgb', library.artwork_root, FRAME_BYTES * DASHBOARD_PACK_MAX_FRAMES)
        if len(pack) != count * FRAME_BYTES or hashlib.sha256(pack).hexdigest() != manifest.get('dashboard_pack_sha256'):
            raise ValueError('The saved Dashboard background changed. Prepare it again.')
        files['artwork-dashboard.rgb'] = pack
    portable = {key: manifest[key] for key in MANIFEST_KEYS if key in manifest}
    portable.update(compiled='faceplate.gif', dashboard_pack='artwork-dashboard.rgb' if len(files) == 2 else '')
    document = dict(schema='gabecubeaura-creation-v1', active=True, applied_as_defaults=False,
                    manifest=portable, files={name:hashlib.sha256(value).hexdigest() for name,value in files.items()})
    files['creation.json'] = (json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False)+'\n').encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in files.items():
            item = zipfile.ZipInfo(name, date_time=(2026,1,1,0,0,0));item.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(item,value)
    payload = output.getvalue()
    if len(payload) > MAX_ARCHIVE_BYTES:
        raise ValueError('Creation archive exceeds 4 MB; nothing was truncated')
    return payload
