"""Refresh integrity receipts for the generic external integration API."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
files={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('main.py','py_modules/signalbar/backend/engine.py')}
(ROOT/'integration-contract.json').write_text(json.dumps({'protocol':1,'service':'gca.integrations','capture_owner':False,'files':files},indent=2)+'\n')
# Compatibility receipt only: no client identity, interface or recording code.
(ROOT/'vocal-contract.json').write_text(json.dumps({'protocol':1,'legacy_voice':False,'files':files},indent=2)+'\n')
