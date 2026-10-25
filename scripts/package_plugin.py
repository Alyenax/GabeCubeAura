"""Build the versioned plugin archive; packaging never publishes a release."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo
from check_license_scope import check_license_scope

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = json.loads((ROOT/'package.json').read_text())
OUTPUT = ROOT/'out'/f"GabeCubeAura-v{PACKAGE['version']}.zip"
FIXED_OUTPUT = ROOT/'out/GabeCubeAura.zip'
CHECKSUMS = ROOT/'out/SHA256SUMS'
COMPONENT_PATHS = {}
BUNDLE_MANIFEST = 'update-manifest.json'
FILES = ['main.py','plugin.json','package.json','dist/index.js','LICENSE','LICENSING.md',
         'THIRD_PARTY_NOTICES.md','integration-contract.json','vocal-contract.json',
         'docs/JSAUX_BROKER_V1_CONTRACT.md','docs/CONFIGURATION_CALIBRATION_REFERENCE.md',
         'docs/PUBLIC_HELP.md']
FORBIDDEN = ('py_modules/signalbar/assistant/', 'py_modules/signalbar/studio/',
             'py_modules/signalbar/cinema/', 'assets/gabe-', 'assets/companion-',
             'assets/glados-', 'assets/playful-', 'assets/assistant-',
             'tools/', 'tests/', 'node_modules/', '.github/', 'docs/RELEASE_NOTES_',
             'py_modules/signalbar/automatic_incidents.py', 'py_modules/signalbar/voice_diagnostics.py')


def iter_files(*, require_build=True):
    entries = json.loads((ROOT/'scripts/runtime-files.json').read_text())
    for relative in entries:
        if not require_build and relative == 'dist/index.js': continue
        path = ROOT/relative
        if path.is_symlink() or not path.is_file(): raise ValueError('Missing/unsafe runtime file: '+relative)
        if any(relative.startswith(x) for x in FORBIDDEN): raise ValueError('Forbidden runtime file: '+relative)
        yield path


def write_runtime_entry(archive, name, data):
    info = ZipInfo(str(name), date_time=(2026,10,25,0,0,0))
    info.create_system = 3; info.external_attr = 0o100644 << 16
    archive.writestr(info, data, compress_type=ZIP_DEFLATED, compresslevel=9)


def build_update_manifest(files, components=()):
    assert not components
    return {'schema':1,'product':'GabeCubeAura','version':PACKAGE['version'],
            'components':[{'id':'plugin','version':PACKAGE['version'],'required':True,'executables':[],
             'files':[{'path':p.relative_to(ROOT).as_posix(),'size':p.stat().st_size,
                       'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]}]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-candidate', action='store_true', help='Local private delivery only; does not clear public publication')
    args = parser.parse_args(argv)
    # A normal packaging invocation continues to enforce the public-publication gate.
    check_license_scope(ROOT, public_build=not args.private_candidate)
    if '-lab' in PACKAGE['version'] or '-test' in PACKAGE['version']: raise ValueError('Candidate must not enter Lab/test channels')
    import refresh_vocal_contract
    files = list(iter_files()); manifest = build_update_manifest(files)
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(OUTPUT,'w') as archive:
        for path in files: write_runtime_entry(archive,Path('GabeCubeAura')/path.relative_to(ROOT),path.read_bytes())
        write_runtime_entry(archive,Path('GabeCubeAura')/BUNDLE_MANIFEST,(json.dumps(manifest,indent=2,sort_keys=True)+'\n').encode())
    shutil.copy2(OUTPUT,FIXED_OUTPUT)
    digest=hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    CHECKSUMS.write_text(f'{digest}  {OUTPUT.name}\n{digest}  {FIXED_OUTPUT.name}\n')
    print(OUTPUT)

if __name__ == '__main__': main()
