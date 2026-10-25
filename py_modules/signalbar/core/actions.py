"""Single-use bounded requests to Steam's own frontend APIs, not OS shell access."""
import secrets
import threading
import time
from .cancellation import Cancelled


class SteamActions:
    def __init__(self, get_game, shutdown=None):
        self.get_game = get_game
        self.shutdown = shutdown
        self.send = lambda payload: (_ for _ in ()).throw(RuntimeError('Interface Steam indisponible.'))
        self.lock = threading.Lock()
        self.pending = None

    def claim(self, token):
        with self.lock:
            request = self.pending
            if not request or not request.get('token') or request.get('token') != token or request['claimed'] or request['cancel'].is_set() or time.monotonic() > request['deadline']:
                return None
            if request['action'] == 'close' and int(self.get_game().get('appid', 0)) != request['appid']:
                request['done'].set(); return None
            request['claimed'] = True
            return {k: request[k] for k in ('action', 'appid')}

    def acknowledge(self, token, accepted):
        with self.lock:
            request = self.pending
            if request and request.get('token') and request.get('token') == token and request['claimed']:
                request['accepted'] = accepted is True
                request['done'].set()

    def request(self, action, appid, cancel):
        if action not in ('close', 'sleep', 'shutdown'): raise ValueError('Unsupported Steam action')
        if action == 'close' and (type(appid) is not int or not 0 < appid < 2**32): raise ValueError('Invalid AppID')
        if cancel.is_set(): raise Cancelled()
        if action == 'shutdown' and self.shutdown is not None:
            # Still single-use and cancellation-gated, but not routed through
            # the client's undocumented power-state implementation.
            with self.lock:
                if self.pending is not None: raise RuntimeError('Une action Steam est déjà en cours.')
                self.pending = {'action':'shutdown'}
            try: return self.shutdown(cancel)
            finally:
                with self.lock: self.pending = None
        request = {'token': secrets.token_hex(16), 'action': action, 'appid': appid,
                   'cancel': cancel, 'claimed': False, 'accepted': False,
                   'done': threading.Event(), 'deadline': time.monotonic()+5}
        with self.lock:
            if self.pending is not None: raise RuntimeError('Une action Steam est déjà en cours.')
            self.pending = request
        try:
            self.send({'token': request['token']})
            while not request['done'].wait(.05):
                if cancel.is_set(): raise Cancelled()
                if time.monotonic() > request['deadline']: raise RuntimeError('Steam ne confirme pas la commande. Aucune action de secours forcée.')
            if cancel.is_set(): raise Cancelled()
            if not request['accepted']: raise RuntimeError('Steam n’a pas accepté la commande.')
        finally:
            with self.lock: self.pending = None
