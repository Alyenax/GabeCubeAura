"""Bounded passive Linux evidence. Never opens USB, stops services or uploads."""
from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time

_history = deque(maxlen=8)
_lock = threading.Lock()
_last_failure = 0.0


def _text(path, limit=4096):
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0))
    try:
        return os.read(fd, limit).decode('utf-8', 'replace')
    finally:
        os.close(fd)


def _category(command):
    value = command.lower().replace('-', '').replace('_', '')
    if 'gabecubeaura' in value or 'signalbar.jsauxbroker' in value:
        return 'gabecubeaura'
    if 'pixelclocks' in value:
        return 'pixel-clocks'
    if 'pixelfaceplate' in value:
        return 'pixel-faceplate'
    if 'jsaux' in value:
        return 'jsaux'
    if 'pluginloader' in value or 'decky' in value:
        return 'decky'
    if '/plugins/' in value and ('python' in value or 'main.py' in value):
        return 'other-plugin'
    return 'unknown'


def processes(port, *, proc_root='/proc', budget=0.18):
    """Read process metadata/fd links; export categories, never command lines."""
    started = time.monotonic()
    result = dict(available=False, complete=False, processes_scanned=0, fds_scanned=0,
                  inaccessible=0, candidates=[], port_holders=[], reason='unavailable')
    try:
        entries = sorted((p for p in Path(proc_root).iterdir() if p.name.isdigit()), key=lambda p:int(p.name))
    except OSError:
        return result
    result.update(available=True, reason='')
    target = os.path.realpath(port) if port else None
    for directory in entries[:2048]:
        if time.monotonic() - started >= budget:
            result['reason'] = 'time-budget'
            break
        result['processes_scanned'] += 1
        pid = int(directory.name)
        try:
            command = _text(directory/'cmdline', 4096)
            category = 'gabecubeaura' if pid == os.getpid() else _category(command)
        except OSError:
            category = 'unknown'
            result['inaccessible'] += 1
        item = dict(pid=pid, category=category, this_process=pid == os.getpid())
        if category != 'unknown' and len(result['candidates']) < 16:
            result['candidates'].append(item)
        if not target:
            continue
        try:
            descriptors = list((directory/'fd').iterdir())
            if len(descriptors) > 256:
                result['reason'] = result['reason'] or 'fd-limit'
            for descriptor in descriptors[:256]:
                if time.monotonic() - started >= budget:
                    result['reason'] = 'time-budget'
                    break
                result['fds_scanned'] += 1
                try:
                    linked = os.readlink(descriptor)
                    if linked == target or (linked.startswith('/dev/') and os.path.realpath(linked) == target):
                        if len(result['port_holders']) < 16:
                            result['port_holders'].append(item)
                        break
                except OSError:
                    continue
        except OSError:
            result['inaccessible'] += 1
    else:
        if len(entries) > 2048:
            result['reason'] = 'process-limit'
    result['complete'] = not result['reason'] and not result['inaccessible']
    result['elapsed_ms'] = round((time.monotonic() - started) * 1000)
    return result


def usb(port, *, sys_root='/sys'):
    result = dict(available=False, reason='device-not-observed', voltage='not-measured',
                  current='not-measured', cable_quality='not-measured', port_type='unknown',
                  panel_revision='unknown', panel_upload_limit='not-measured')
    name = os.path.basename(port or '')
    if not re.fullmatch(r'ttyUSB\d{1,3}', name):
        return result
    node = (Path(sys_root)/'class/tty'/name/'device').resolve()
    try:
        driver = (node/'driver').resolve().name
        result['serial_driver'] = driver if driver in ('ch341', 'ch341-uart', 'ch34x', 'usbserial') else 'unknown'
        for parent in (node, *node.parents):
            try:
                if _text(parent/'idVendor').strip().lower() != '1a86' or _text(parent/'idProduct').strip().lower() != '7523':
                    continue
            except OSError:
                continue
            result.update(available=True, reason='', usb_path_depth=parent.name.count('.'))
            try:
                revision = _text(parent/'bcdDevice', 16).strip()
                result['bridge_revision'] = revision if re.fullmatch(r'[0-9A-Fa-f]{4}', revision) else 'unknown'
            except OSError:
                result['bridge_revision'] = 'unknown'
            for key, filename in [('speed_mbps', 'speed'), ('bus_number', 'busnum'),
                                  ('device_number', 'devnum'), ('power_control', 'power/control'),
                                  ('runtime_status', 'power/runtime_status'),
                                  ('autosuspend_delay_ms', 'power/autosuspend_delay_ms'),
                                  ('runtime_active_ms', 'power/runtime_active_time'),
                                  ('runtime_suspended_ms', 'power/runtime_suspended_time'),
                                  ('declared_max_power_ma', 'bMaxPower')]:
                try:
                    raw = _text(parent/filename, 128).strip()
                    if key in ('power_control','runtime_status'):
                        result[key] = raw if raw in ('on','auto','active','suspended','suspending','resuming','unsupported','error') else 'unknown'
                    else:
                        match = re.fullmatch(r'(-?\d{1,10})(?:\.\d+)?(?:mA)?', raw)
                        result[key] = int(match[1]) if match else None
                except OSError:
                    result[key] = None
            result['declared_power_is_measurement'] = False
            return result
    except OSError:
        result['reason'] = 'unreadable'
    return result


def observe_failure(port, transfer, *, reason='transfer'):
    """At most one passive process/USB sample per second, on real tty failures."""
    global _last_failure
    if not re.fullmatch(r'/dev/ttyUSB\d{1,3}', str(port or '')):
        return
    now = time.monotonic()
    with _lock:
        if now - _last_failure < 1:
            return
        _last_failure = now
    try:
        allowed = ('begin_status','begin_attempts','chunks','payload_complete','end_sent',
                   'failure_stage','failure_kind','configured_profile','active_profile',
                   'expected_bytes','image_width','image_height','image_format','total_ms')
        event = dict(at_unix_s=round(time.time(), 3), reason=reason,
                     transfer={key:transfer[key] for key in allowed if key in transfer},
                     processes=processes(port, budget=0.12), usb=usb(port))
        with _lock:
            _history.append(event)
    except Exception:
        # Instrumentation must never replace the original transfer exception.
        pass


def _command(args, timeout, extra_env=None):
    env = {'PATH':'/usr/bin:/bin', 'LC_ALL':'C', 'SYSTEMD_PAGER':'cat'}
    env.update(extra_env or {})
    try:
        run = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env)
        if run.returncode:
            return None, 'unavailable-or-denied'
        return run.stdout[:262144], ''
    except subprocess.TimeoutExpired:
        return None, 'timeout'
    except OSError:
        return None, 'unavailable'


def services():
    result = []
    scopes = [('system',None)]
    try:
        sessions = sorted((p for p in Path('/run/user').iterdir() if p.name.isdigit() and (p/'bus').exists()), key=lambda p:int(p.name))[:2]
        scopes.extend(('user',p) for p in sessions)
    except OSError:
        pass
    if len(scopes) == 1:
        scopes.append(('user',None))
    for scope, session in scopes:
        extra = {'XDG_RUNTIME_DIR':str(session), 'DBUS_SESSION_BUS_ADDRESS':'unix:path='+str(session/'bus')} if session else {}
        text, error = _command(['/usr/bin/systemctl', '--'+scope, 'list-units', '--type=service',
                               '--all', '--no-pager', '--no-legend', '--plain'], 0.6, extra)
        row = dict(scope=scope, available=text is not None, reason=error, matches=[])
        if session:row['user_id'] = int(session.name)
        if text is not None:
            for line in text.splitlines():
                fields = line.split()
                if len(fields) < 4:
                    continue
                category = _category(fields[0])
                if category == 'unknown':
                    continue
                row['matches'].append(dict(category=category,
                    load=fields[1] if fields[1] in ('loaded','not-found','masked','error') else 'unknown',
                    active=fields[2] if fields[2] in ('active','inactive','failed','activating','deactivating') else 'unknown',
                    state=fields[3] if fields[3] in ('running','dead','exited','failed','start','stop','auto-restart') else 'unknown'))
                if len(row['matches']) == 16:
                    break
        result.append(row)
    return dict(scopes=result, user_scope='up-to-two-existing-session-buses',
                limitation='Access-denied sessions and unrecognized service names remain unknown.')


def size_evidence(panel):
    """Describe observed outcomes, never infer a panel's capacity from reuse."""
    try:
        journal = panel.state['observability']['journal'][-32:]
    except (TypeError,AttributeError,KeyError):
        journal = []
    written, reused, refused = [], [], []
    for event in journal:
        size = event.get('size_bytes')
        if not isinstance(size,int) or isinstance(size,bool) or not 0 < size < 1048576:
            continue
        if event.get('outcome') == 'written':written.append(size)
        elif event.get('outcome') == 'identical':reused.append(size)
        elif event.get('begin_status') == 0 or (event.get('outcome') == 'failed' and event.get('error') == 'faceplate refused GIF begin'):
            refused.append(size)
    return dict(newly_acked_bytes=written[-8:], reused_bytes=reused[-8:], begin_refused_bytes=refused[-8:],
                sample_scope='up-to-32-retained-journal-events', capacity='not-inferred',
                visible_playback='not-measured')


def kernel_events(port):
    text, error = _command(['/usr/bin/journalctl', '-k', '--since=-30min', '-n', '300',
                            '--no-pager', '-o', 'json', '--output-fields=MESSAGE,__REALTIME_TIMESTAMP'], 1.2)
    result = dict(available=text is not None, reason=error, window_minutes=30, record_limit=300,
                  complete_window=False, events=[],
                  limitation='No event is not proof of adequate USB power.')
    if text is None:
        return result
    tty = os.path.basename(port or '')
    for line in text.splitlines():
        try:
            row = json.loads(line)
            message = row.get('MESSAGE','')
            if not isinstance(message,str):
                continue
            lower = message.lower()
            category = next((name for regex,name in (
                (r'over.?current','over-current'), (r'under.?voltage|brownout','undervoltage'),
                (r'usb.*disconnect|ch34.*disconnected','usb-disconnect'),
                (r'usb.*reset','usb-reset'),
                (r'usb.*(?:error|unable to enumerate|not accepting)','usb-error'),
                (r'ch34.*attached','serial-attached')) if re.search(regex,lower)),None)
            if category:
                stamp = row.get('__REALTIME_TIMESTAMP','')
                result['events'].append(dict(kind=category,
                    at_unix_s=round(int(stamp)/1000000,3) if str(stamp).isdigit() else None,
                    association='same-tty' if tty and tty in message else 'host-event-not-attributed'))
        except (ValueError,TypeError):
            continue
    result['events'] = result['events'][-16:]
    return result


def storage(engine):
    roots = [('settings', getattr(getattr(engine,'settings',None),'path',None)),
             ('panel_state',getattr(getattr(engine,'faceplate',None),'state_path',None)),
             ('scene_cache',getattr(engine,'_faceplate_scene_cache',None))]
    rows = []
    for label, raw in roots:
        row = dict(component=label, available=False)
        if raw:
            try:
                path = Path(raw);info = path.lstat()
                import stat
                row.update(available=True, kind='symlink' if stat.S_ISLNK(info.st_mode) else
                    'file' if stat.S_ISREG(info.st_mode) else 'directory' if stat.S_ISDIR(info.st_mode) else 'other',
                    owned_by_current_user=info.st_uid == os.geteuid())
                if not stat.S_ISLNK(info.st_mode):
                    parent = path if stat.S_ISDIR(info.st_mode) else path.parent
                    fs = os.statvfs(parent)
                    row.update(free_bytes=fs.f_bavail*fs.f_frsize, writable=os.access(parent,os.W_OK))
            except FileNotFoundError:
                row['reason'] = 'absent'
            except OSError:
                row['reason'] = 'unreadable'
        rows.append(row)
    return rows


def capture(engine):
    """Export-only system collection. No USB opens, writes or state changes."""
    started = time.monotonic()
    if not Path('/proc').is_dir() or not Path('/sys/class/tty').is_dir():
        return dict(available=False, reason='linux-evidence-unavailable', voltage='not-measured', current='not-measured')
    from .faceplate.transport import find_port
    port = find_port()
    panel = getattr(engine,'faceplate',None)
    with _lock:
        history = list(_history)
    sections = {}
    for key, read in [('processes',lambda:processes(port)), ('usb',lambda:usb(port)),
                      ('services',services), ('kernel',lambda:kernel_events(port)),
                      ('storage',lambda:storage(engine))]:
        try:
            sections[key] = read()
        except Exception:
            sections[key] = dict(available=False,reason='unavailable')
    settings = getattr(engine,'settings',None)
    try:
        values = settings.all() if settings else {}
    except Exception:
        values = {}
    safe = {}
    for key, choices in [('faceplate_control_mode',('automatic','gca-priority','other-app')),
                         ('faceplate_power_mode',('auto','manual')),
                         ('faceplate_clock_cadence_home',('minute','conservative')),
                         ('faceplate_clock_cadence_game',('minute','conservative'))]:
        safe[key] = values.get(key) if values.get(key) in choices else 'unknown'
    return dict(available=True, captured_at_unix_s=round(time.time(),3), elapsed_ms=round((time.monotonic()-started)*1000),
        **sections, failures=history, failure_history_scope='current-process-session', configuration=safe,
        size_evidence=size_evidence(panel),
        voltage='not-measured', current='not-measured', flash_health='not-measured',
        collection='passive-no-device-commands')
