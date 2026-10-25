# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Opt-in, RAM-only replacement; all IO stays on the existing serial worker."""
from . import timing
from .transport import LinkError, TransferCancelled

RETURN_SECONDS = 20.0

class ContinuousReturn:
    def arm_continuous_return(self, operation_id, allowed):
        if not self.lock.acquire(False):return False
        try:
            if (not self.enabled or self.powered is not True or self._screensaver_exit_blank
                    or not self._delegated_gif_activation_pending or not self.device_token
                    or self.last_transfer.get('active_profile')!='baseline'
                    or not self.last_synchronized or not self.last_asset.startswith('screensaver:')):return False
            self._continuous_return=dict(operation=operation_id,device=self.device_token,
                started=self.monotonic(),deadline=self.monotonic()+RETURN_SECONDS,allowed=allowed,stop=False)
            self._return_trace=dict(state='pending',reason='steam-inactive',budget_ms=20000,events=[])
            self._return_event('armed')
            return True
        finally:self.lock.release()

    def _return_event(self,event,**fields):
        trace=self._return_trace
        if not trace:return
        active=self._continuous_return
        item=dict(event=event,elapsed_ms=max(0,round((self.monotonic()-(active['started'] if active else self._return_trace_at))*1000)),**fields)
        trace['events']=(trace.get('events',[])+[item])[-24:]

    def _return_allowed(self):
        active=self._continuous_return
        if not active or active['stop'] or self.monotonic()>=active['deadline']:return False
        try:return bool(active['allowed']())
        except Exception:return False

    def continuous_return_needs_stop(self):
        # Nonblocking metadata used by the engine; never wait for serial lock.
        return bool(self._continuous_return and not self._return_allowed())

    def stop_continuous_return(self,reason='return-expired'):
        with self.lock:
            if not self._continuous_return:return {'superseded':True}
            active=self._continuous_return;port=self.port_finder()
            try:
                if not port or self.identity_reader(port)!=active['device']:raise LinkError('Return device changed')
                with self.link_factory(port=port,log=lambda message:self._log('debug',message)) as link:
                    self._fail_continuous_return(link,reason)
                return {'ok':True}
            except (OSError,ValueError,LinkError):
                self._end_continuous_return('unconfirmed',reason);self._screensaver_exit_blank=True
                return {'ok':False}

    def _end_continuous_return(self,state,reason):
        active=self._continuous_return
        if active:self._return_trace_at=active['started']
        self._return_event(state,reason=reason)
        self._return_trace.update(state=state,reason=reason)
        self._continuous_return=None

    def _fail_continuous_return(self,link,reason):
        if not self._continuous_return:return
        self._screensaver_exit_blank=True
        try:
            self._power_command(link,False)
            self.powered=False
            self._end_continuous_return('fallback-dark',reason)
        except (OSError,ValueError,LinkError):
            self._end_continuous_return('unconfirmed',reason)
            raise

    def _prepare_return_link(self,link,size=0):
        active=self._continuous_return
        link.preserve_running_gif=False
        if not active:return
        same=self.device_token==active['device'] and self.identity_reader(link.port)==active['device']
        remaining=max(0,(active['deadline']-self.monotonic())*1000)
        admitted=size==0 or timing.transfer_ms(size)<=remaining
        try:policy_allowed=bool(active['allowed']())
        except Exception:policy_allowed=False
        if not policy_allowed:
            self._fail_continuous_return(link,'policy-changed')
            raise TransferCancelled('Return policy changed')
        if (self._return_allowed() and same and self.powered is True
                and not self._screensaver_exit_blank and getattr(link,'transport_profile','')=='baseline' and admitted):
            link.preserve_running_gif=True
            link.return_operation=active['operation']
            self._return_event('replacement-start',bytes=size)
        else:self._fail_continuous_return(link,'admission-or-policy')

    def _return_cancelled(self,link,cancelled):
        if callable(cancelled) and cancelled():return True
        if getattr(link,'preserve_running_gif',False):
            active=self._continuous_return
            return not active or active['operation']!=link.return_operation or not self._return_allowed()
        return False

    def continuous_return_status(self):
        active=self._continuous_return
        return dict(self._return_trace,active=active is not None,
            remaining_ms=max(0,round((active['deadline']-self.monotonic())*1000)) if active else 0,
            physical_playback='not-measured')
