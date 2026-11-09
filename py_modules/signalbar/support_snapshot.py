"""Read-only, bounded support facts. No network, command execution or USB IO."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat

_VERSION = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+() /:-]{0,95}$')

def version(value):
    return value if isinstance(value,str) and _VERSION.fullmatch(value) else 'unknown'

def _read(path, limit=1048576):
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size>limit:raise ValueError('unavailable')
        data=os.read(fd,limit+1)
        if len(data)>limit:raise ValueError('unavailable')
        return data
    finally:os.close(fd)

def _json(path):
    try:
        value=json.loads(_read(path));return value if isinstance(value,dict) else {}
    except (OSError,ValueError,TypeError):return {}

def system_facts(decky_version=None):
    facts={'os':version(platform.system()),'kernel':version(platform.release()),
           'architecture':version(platform.machine()),'python':platform.python_version(),
           'decky_version':version(decky_version),'steam_version':'unknown',
           'firmware_version':'not-readable','flash_health':'not-measured'}
    try:
        for line in _read(Path('/etc/os-release'),8192).decode('utf-8','replace').splitlines():
            key,sep,value=line.partition('=')
            if sep and key in ('NAME','VERSION_ID','BUILD_ID','VARIANT_ID'):
                facts['os_'+key.lower()]=version(value.strip('"\''))
    except (OSError,ValueError):pass
    return facts

def installation(root, backend_version, frontend_version=''):
    root=Path(root);package=_json(root/'package.json');manifest=_json(root/'update-manifest.json')
    expected={}
    for component in manifest.get('components',[]) if isinstance(manifest.get('components'),list) else []:
        if isinstance(component,dict) and component.get('id')=='plugin':
            for item in component.get('files',[]):
                if isinstance(item,dict):expected[item.get('path')]=item.get('sha256')
    files=[]
    for name in ('main.py','dist/index.js','py_modules/signalbar/backend/engine.py',
                 'py_modules/signalbar/providers/weather.py','py_modules/signalbar/faceplate/coordinator.py',
                 'py_modules/signalbar/faceplate/transport.py'):
        try:
            digest=hashlib.sha256(_read(root/name,8388608)).hexdigest()
            files.append({'component':name,'readable':True,'matches_manifest':digest==expected[name] if name in expected else None})
        except (OSError,ValueError):files.append({'component':name,'readable':False,'matches_manifest':None})
    backend=version(backend_version);front=version(frontend_version);pack=version(package.get('version'))
    return {'backend_version':backend,'frontend_version':front,'package_version':pack,
        'manifest_version':version(manifest.get('version')),
        'frontend_backend_match':front==backend if front!='unknown' else None,
        'backend_package_match':backend==pack if pack!='unknown' else None,
        'checked_files':files,'all_checked_files_match':all(row['matches_manifest'] is True for row in files) if expected else None}

def runtime(engine):
    """Do not call status/probe methods which could open a device or change state."""
    settings=getattr(engine,'settings',None)
    values=settings.all() if settings is not None else {}
    allowed=('signalbar_enabled','faceplate_lab_enabled','faceplate_power_mode','faceplate_control_mode','faceplate_allow_das','faceplate_allow_dva')
    result={'settings':{key:values.get(key) for key in allowed},
        'power_intent':{'manual_off':bool(getattr(engine,'_faceplate_manual_off',False)),
            'system_suspended':bool(getattr(engine,'_assistant_system_suspended',False)),
            'scene_suspended':bool(getattr(engine,'_faceplate_suspended',False))},
        'display_observation':'not-measured'}
    panel=getattr(engine,'faceplate',None)
    if panel is not None:
        capture=getattr(panel,'passive_diagnostic_snapshot',None)
        if callable(capture):
            state=capture()
        else:
            snapshot=getattr(panel,'restoration_status',None)
            state={'available':True,'powered':getattr(panel,'powered',None),
                'restoration':snapshot() if callable(snapshot) else {},
                'last_transfer':getattr(panel,'last_transfer',{})}
        result['snapshot']={key:state[key] for key in ('available','reason','captured_at_unix_s') if key in state}
        result['power_intent']['last_confirmed_power']=state.get('powered')
        if 'restoration' in state:result['restoration']=state['restoration']
        transfer=state.get('last_transfer',{})
        if isinstance(transfer,dict):
            allowed=('begin_attempted','begin_status','begin_attempts','chunks','payload_complete','end_sent',
                'configured_profile','active_profile','attempt_profiles','failure_stage','failure_kind',
                'begin_ms','begin_ack_ms','end_ack_ms','total_ms','already_stored','sent_unconfirmed',
                'body_reserved','expected_bytes','image_format','image_width','image_height')
            result['last_transfer']={name:transfer[name] for name in allowed if name in transfer}
    result["gif_size_tests"] = list(getattr(engine, "_faceplate_gif_tests", ()))
    weather=getattr(engine,'weather',None);snapshot=getattr(weather,'diagnostic_status',None)
    if callable(snapshot):result['weather']=snapshot()
    return result
