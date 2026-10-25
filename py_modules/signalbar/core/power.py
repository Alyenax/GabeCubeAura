"""Explicit confirmed machine power-off through logind, never restart.

No shell, forced flags, auth prompt, inhibitor removal or reboot fallback.
The caller is the existing confirmation-gated, single-request assistant path.
"""
import json
import shutil
from .cancellation import Cancelled


def poweroff(audio, cancel):
    executable = shutil.which('busctl')
    if not executable: raise RuntimeError('Arrêt système indisponible : busctl absent. Aucun redémarrage demandé.')
    args = [executable, '--system', '--timeout=3', '--auto-start=no', '--json=short', 'call',
            'org.freedesktop.login1', '/org/freedesktop/login1', 'org.freedesktop.login1.Manager']
    if cancel.is_set(): raise Cancelled()
    try:
        raw = audio.run([*args, 'CanPowerOff'], cancel, timeout=3.5)
        if len(raw)>4096: raise ValueError('Invalid capability')
        result = json.loads(raw)
        if result != {'type':'s', 'data':['yes']}:
            raise RuntimeError('SteamOS ne permet pas cet arrêt sans autorisation supplémentaire. Aucun redémarrage demandé.')
        if cancel.is_set(): raise Cancelled()
        # PowerOff is distinct from Reboot. False forbids interactive auth;
        # it is NOT a reboot flag. There is no fallback to Steam client power.
        raw = audio.run([*args, 'PowerOff', 'b', 'false'], cancel, timeout=3.5)
        if raw.strip() and json.loads(raw) != {'type':'', 'data':[]}:
            raise ValueError('Invalid power response')
        return {'backend':'logind', 'method':'PowerOff', 'accepted':True}
    except Cancelled: raise
    except RuntimeError: raise
    except Exception:
        raise RuntimeError('Arrêt SteamOS non confirmé. Aucun redémarrage ni seconde tentative forcée.')
