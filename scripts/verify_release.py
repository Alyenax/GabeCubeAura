"""Verify the versioned plugin archive, retained assets and staged backend."""
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
from zipfile import ZipFile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'py_modules'))
from signalbar.updates import validate_and_stage_archive,read_bundle_contract
from check_license_scope import check_license_scope
from package_plugin import FORBIDDEN

def main():
    version=json.loads((ROOT/'package.json').read_text())['version']
    expected=set(json.loads((ROOT/'scripts/runtime-files.json').read_text()))|{'update-manifest.json'}
    digests=[]
    for line in (ROOT/'out/SHA256SUMS').read_text().splitlines():
        digest,name=line.split('  ',1);archive=ROOT/'out'/name
        assert hashlib.sha256(archive.read_bytes()).hexdigest()==digest
        digests.append(digest)
        with ZipFile(archive) as z:
            names={n.split('/',1)[1] for n in z.namelist()}
            assert names==expected and z.testzip() is None
            assert not any(any(n.startswith(p) for p in FORBIDDEN) for n in names)
            assert not any('RELEASE_NOTES_' in n or 'PRIVATE_CREATION' in n for n in names)
        with tempfile.TemporaryDirectory() as tmp:
            staged=validate_and_stage_archive(archive,Path(tmp).resolve()/'stage',version)
            read_bundle_contract(staged,version);check_license_scope(ROOT,staged,public_build=True)
            for path in (staged/'assets').rglob('*'):
                if path.is_file(): assert path.read_bytes()==(ROOT/path.relative_to(staged)).read_bytes()
            code="import sys;sys.path.insert(0,sys.argv[1]);from signalbar.backend import Engine;from signalbar.settings import SettingsStore;import tempfile;from pathlib import Path; t=tempfile.TemporaryDirectory();p=Path(t.name);e=Engine(SettingsStore(str(p/'config.json')),str(p/'cache.json'));e.stop();assert not any(x.startswith('signalbar.assistant') for x in sys.modules)"
            subprocess.run([sys.executable,'-I','-B','-c',code,str(staged/'py_modules')],cwd=tmp,check=True)
    assert len(digests)==2 and len(set(digests))==1
    print('Verified plugin archive:',version,'runtime files',len(expected))
if __name__=='__main__':main()
