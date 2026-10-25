# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""JSAUX broker hardware boundary: the existing worker is the only writer.

Lock order: broker state -> adapter state -> worker queue.  Serial/coordinator
locks are taken only by the worker after releasing adapter state.  A report or
the core's validity callback MUST never run while adapter state is locked.
"""
from __future__ import annotations

import hashlib
import copy
from collections import deque
import os
import threading
import time
import uuid
from pathlib import Path

from .transport import PhysicalOwnership, install_ownership_manager, timing_admission
from .flash import UploadDeferred, SCREENSAVER_CONTINUITY_SECONDS
from .screensaver_projection import ScreensaverProjection
from .priority_evidence import clean as clean_priority_evidence


class FaceplateBrokerAdapter:
    def __init__(self, engine, ownership_root=None, clock=time.monotonic):
        self.engine = engine
        self.clock = clock
        self.lock = threading.RLock()
        self.ownership = PhysicalOwnership(ownership_root or "/run/decky/jsaux-broker/v1/ownership")
        install_ownership_manager(self.ownership)
        self._observation_at = None
        self._observation_health = "waiting"
        self._observation_error_at = None
        self._observed = "unknown"
        self._baseline = False
        self._activation = None
        self._closed = True
        self._job = None
        self._report = None
        self._executing = False
        self._stopped = False
        self._last_attempt = None
        self._last_receipt = {}
        self._restore = None
        self._restore_pending = None
        self._restore_trace = {}
        self._exit_stop = None
        self._display_operation = None
        self._return_candidate = None
        self._return_stop_at = None
        self._return_policy_allowed = False
        self.projection=ScreensaverProjection()
        self._lightbar=None
        self._observations=deque(maxlen=24)
        self._policy_observations=deque(maxlen=24)
        self._policy_latest=None
        self._policy_signature=None
        self._policy_revocations=deque(maxlen=8)
        self._reservation_failure='none'

    def _continuity_window(self):
        # Only an existing uncancelled delegation gets the short recovery window.
        return 8.0 if (self._job and not self._job.get('cancelled') and not self._closed
                       and self._job.get('activation_id') == self._activation) else 5.0

    def observe_steam(self, active, state="available", source="unknown"):
        now = self.clock()
        with self.lock:
            observed='active' if active and state=='available' else 'inactive' if state=='available' else 'unknown'
            source=source if source in ('poll','notification','startup','stopped','resume') else 'unknown'
            if observed!=self._observed or state!=self._observation_health or not self._observations:
                self._observations.append(dict(at=now,observed=observed,source=source,
                    state=state if state in ('available','waiting','error','unavailable') else 'unknown',
                    previous_age_ms=None if self._observation_at is None else max(0,round((now-self._observation_at)*1000))))
            self._observation_health = state if state in ('available','waiting','error','unavailable') else 'unknown'
            if state != "available" and source not in ('stopped','startup','resume') and not self._stopped:
                # A failed query is not an inactive Steam observation. Never
                # refresh its timestamp; _steam still expires the actual proof.
                if self._observation_error_at is None:self._observation_error_at = now
                return
            if self._stopped or source in ('stopped','startup','resume'):
                self._observed = "unknown"
                self._observation_at = None
                self._baseline = False
                self._closed = True
                return
            self._observation_error_at = None
            if self._observation_at is not None and now-self._observation_at > self._continuity_window():
                self._baseline = False
                self._closed = True
            self._observation_at = now
            if not active:
                self._observed = "inactive"
                self._baseline = True
                self._closed = True
            else:
                if self._observed == "inactive" and self._baseline:
                    self._activation = uuid.uuid4().hex
                    self._closed = False
                self._observed = "active"

    def _steam(self):
        with self.lock:
            age = None if self._observation_at is None else max(0, int((self.clock()-self._observation_at)*1000))
            if age is None or age > self._continuity_window()*1000 or self.engine._faceplate_suspended or self._stopped:
                self._baseline = False
                self._closed = True
                observed = "unknown"
            else:
                observed = self._observed
            return {"observed": observed, "observation_age_ms": age,
                    "activation_id": self._activation, "activation_closed": self._closed}

    def _policy(self):
        engine = self.engine
        values = engine.settings.all()
        enabled = bool(values.get("faceplate_lab_enabled"))
        display_on = not engine._display_panel_off(values) and getattr(engine.faceplate, "powered", None) is not False and engine._faceplate_power_target is not False
        suspended = bool(engine._faceplate_suspended or engine._stop.is_set() or self._stopped)
        thermal = bool(engine.thermal_protection.active)
        decision=getattr(engine,'_broker_decision',None)
        if callable(decision):allowed,evidence=decision(values)
        else:allowed=engine._broker_allowed(values);evidence={}
        priority = bool(not allowed and enabled and display_on and not suspended and not thermal)
        reason = ("FACEPLATE_DISABLED" if not enabled else "DISPLAY_OFF" if not display_on else
                  "SUSPENDED" if suspended else "PRIORITY_ACTIVE" if thermal or priority else None)
        policy={"faceplate_enabled": enabled, "display_on": display_on,
                "suspended": suspended, "thermal_blocked": thermal,
                "priority_active": priority, "reason": reason}
        # This must never change admission or start an extra provider/USB read.
        try:self._remember_policy(policy,evidence,values)
        except Exception:pass
        return policy

    def _remember_policy(self,policy,evidence,values):
        safe=clean_priority_evidence(evidence)
        economy=bool(values.get('faceplate_flash_protection_enabled',True))
        refresh='economy' if economy else 'minute'
        refresh=refresh if refresh in ('economy','minute') else 'unknown'
        # Cooldown is an observation only, never reserve/flush/admit a write.
        flash=getattr(self.engine.faceplate,'flash',None)
        delay=getattr(flash,'screensaver_delay',None)
        remaining=max(0,min(600000,round(delay()*1000))) if callable(delay) else None
        item=dict(at=self.clock(),**safe,policy=dict(policy),economy_refresh=economy,
            dashboard_refresh=refresh,flash_continuity_ms=remaining)
        signature=(tuple(policy.values()),safe['first_blocker'],tuple(safe['evaluated'].items()),
            tuple(sorted(safe['steam_inputs'].items())),safe.get('light_event',{}).get('kind'),safe.get('countdown_source'),economy,refresh)
        with self.lock:
            item['projection_active']=self._lightbar is not None
            self._policy_latest=item
            if signature!=self._policy_signature:
                self._policy_signature=signature
                self._policy_observations.append(copy.deepcopy(item))

    def record_revocation(self,operation_id,reason,state,source='lease-revocation'):
        """Freeze the last *evaluated* decision before cancel/restore changes it."""
        if reason not in ('PRIORITY_ACTIVE','STEAM_INACTIVE','STEAM_STATE_STALE','LEASE_EXPIRED',
                'ALIGNMENT_EXPIRED','ACTIVATION_CLOSED','FACEPLATE_DISABLED','DISPLAY_OFF','SUSPENDED'):return
        with self.lock:
            evidence=copy.deepcopy(self._policy_latest or {})
            sampled=evidence.pop('at',None)
            self._policy_revocations.append(dict(at=self.clock(),
                correlation_id=hashlib.sha256(operation_id.encode()).hexdigest()[:16],
                reason=reason,state=state if state in ('rejected','preempted','expired','released') else 'other',
                source=source if source in ('lease-revocation','reservation-failed') else 'other',
                policy_sample_age_ms=None if sampled is None else max(0,round((self.clock()-sampled)*1000)),
                decision=evidence,reservation_failure=self._reservation_failure))

    def snapshot(self):
        # device_status is metadata/sysfs only; never scan /proc or open USB here.
        device = self.engine.faceplate.device_status()
        port = device.get("port") or ""
        owned = bool(port and self.ownership.claim(port))
        policy = self._policy()
        flash = getattr(self.engine.faceplate, "flash", None)
        flash_status = flash.status() if flash is not None else {}
        delay = flash.delay("background") if flash is not None else 0.0
        if flash is not None and hasattr(flash, "screensaver_delay"):
            delay = max(delay, flash.screensaver_delay())
        with self.lock:
            executing = self._executing
            if self._last_attempt is not None:
                delay = max(delay, SCREENSAVER_CONTINUITY_SECONDS-(self.clock()-self._last_attempt))
        return {"hardware": "absent" if not port else "ownership-unavailable" if not owned else "busy" if device.get("busy") else "available",
                "policy": policy, "steam": self._steam(),
                "ownership": {"logical_owner": "GabeCubeAura" if owned else "other" if port else "none",
                              "serial_busy": bool(device.get("busy") or executing),
                              "device_key": self.ownership.key(port) if port else None},
                "flash": {"allowed": delay <= 0, "retry_after_ms": max(0, int(delay*1000)),
                          "policy_revision": str(flash_status.get("policy", "precaution-v1")),
                          "receipt_state": "known" if flash_status.get("hardware_state") == "acknowledged" else "uncertain"}}

    def diagnostic_snapshot(self):
        with self.lock:
            receipt=dict(self._last_receipt)
            observations=[{**item,'age_ms':max(0,round((self.clock()-item['at'])*1000))} for item in self._observations]
            for item in observations:item.pop('at',None)
            age=None if self._observation_at is None else max(0,round((self.clock()-self._observation_at)*1000))
            last_observation=dict(observed=self._observed,age_ms=age,fresh=age is not None and age<=5000,activation_closed=self._closed,
                query_health=self._observation_health,continuity_window_ms=round(self._continuity_window()*1000),
                degraded_age_ms=None if self._observation_error_at is None else max(0,round((self.clock()-self._observation_error_at)*1000)))
            playing=self._lightbar
            restoration=dict(self._restore_trace)
            policy_observations=copy.deepcopy(list(self._policy_observations))
            policy_revocations=copy.deepcopy(list(self._policy_revocations))
            for item in policy_observations+policy_revocations:
                item['age_ms']=max(0,round((self.clock()-item.pop('at'))*1000))
            if restoration:
                started=restoration.pop('started_at');updated=restoration.pop('updated_at')
                restoration.update(age_ms=max(0,round((self.clock()-updated)*1000)),
                    elapsed_ms=max(0,round(((self.clock() if restoration['state'] in ('pending','deferred','waiting-transaction') else updated)-started)*1000)),
                    physical_playback='not-measured')
        values=self.engine.settings.all()
        coordinator_status=getattr(self.engine.faceplate,'restoration_status',None)
        if callable(coordinator_status):
            panel_state=coordinator_status()
            if isinstance(panel_state,dict):restoration['coordinator']=panel_state
        projection={**self.projection.snapshot(),'mapping':values.get('faceplate_extension_mapping','bottom'),
            'selected':values.get('screensaver_light_bar_mode')=='faceplate_extension',
            'source_state':'not-active' if not playing else 'playing' if self.projection.contains(playing[0]) else 'awaiting-projection',
            'content_id':playing[0][:16] if playing else None}
        return dict(receipt=receipt,steam_observation=last_observation,steam_observations=observations,
            priority_evidence=dict(revision=1,observations=policy_observations,revocations=policy_revocations,
                semantics='first-short-circuit-blocker; omitted predicates not evaluated',physical_cause='not-established'),
            normal_route_restoration=restoration,light_bar_projection=projection,configuration=dict(engine_enabled=bool(values.get('signalbar_enabled')),
            faceplate_enabled=bool(values.get('faceplate_lab_enabled')),mode_disabled=values.get('mode')=='disabled',
            setup_blocked=bool(getattr(self.engine,'_onboarding_recovery_blocked',False)
                               or getattr(self.engine,'_onboarding_applying',False)),
            suspended=bool(self.engine._faceplate_suspended)))

    def prepare_extension(self,content_id,path):
        self.projection.prepare(content_id,path)

    def extension_frame(self,now,mapping='whole'):
        with self.lock:
            playing=self._lightbar
            valid=bool(self._job and not self._job.get('cancelled') and not self._stopped)
        steam=self._steam()
        if not valid or playing is None or steam['observed']!='active' or steam['activation_closed']:return None
        content_id,epoch=playing
        return self.projection.output(content_id,max(0,now-epoch),mapping)

    def _valid(self, job):
        steam = self._steam()
        if (steam["observed"] != "active" or steam["activation_closed"] or
                steam["activation_id"] != job.get("activation_id") or self._policy()["reason"]):
            return False
        deadline = job.get("deadline_mono_ms")
        if deadline is not None and int(self.clock()*1000) >= deadline:
            return False
        check = job.get("valid")
        return not callable(check) or bool(check())

    def reserve(self, job):
        if getattr(self.engine.faceplate,'_continuous_return',None) is not None:return False
        if not self._valid(job):
            with self.lock:self._reservation_failure='invalid-job-or-policy'
            return False
        with self.lock:
            if self._stopped or self._job is not None or self._executing:
                self._reservation_failure=('adapter-stopped' if self._stopped else 'operation-owned' if self._job is not None else 'worker-executing')
                return False
            self._reservation_failure='none'
            self._job = dict(job)
            self._lightbar=None
        # Cancel queued normal refreshes without disturbing a power request.
        worker = self.engine.faceplate_worker
        with worker.condition:
            pending = worker.pending
            if pending and worker._scene_class(pending["scene"], pending["metadata"]) != "control":
                worker.pending = None
                worker.dropped += 1
        return True

    def submit(self, job, report):
        if not self._valid(job):
            return False
        with self.lock:
            if self._job is None or self._job["operation_id"] != job["operation_id"]:
                return False
            if self._job.get("submitted"):
                return False
            self._job = {**job, "submitted": True}
            self._report = report
        generation = self.engine.faceplate_worker.submit("broker:"+job["operation_id"],
            {"kind": "broker", "operation_id": job["operation_id"]},
            {"scene_class": "broker", "reason": "Delegated screensaver"})
        if not generation:
            report(job["operation_id"], transfer_state="failed", reason="DEVICE_BUSY")
        return bool(generation)

    def replace(self,job,report):
        """Advance an owned playlist without releasing/restoring Home."""
        if not self._valid(job):return False
        with self.lock:
            if (self._stopped or self._executing or self._job is None
                or self._job['operation_id']!=job['operation_id'] or self._job.get('cancelled')):return False
            self._job=dict(job)
        return self.submit(job,report)

    def holds_display(self):
        with self.lock:
            # A replacement higher-priority request may supersede the queued
            # exit control. Do not retain a permanent logical barrier for it.
            if self._exit_stop and not self._exit_stop.get('executing') and self.clock()-self._exit_stop['at']>2:
                self._restore_trace.update(exit_stop='queue-expired')
                self._exit_stop=None
            # While revoking, keep the route until the old transaction reaches
            # a safe boundary. Normal refreshes then use the very same worker.
            return self._job is not None or self._executing or self._exit_stop is not None

    def requires_exit_blank(self):
        with self.lock:return self._display_operation is not None

    def execute(self, request):
        operation_id = request["payload"]["operation_id"]
        with self.lock:
            if self._job is None or self._job["operation_id"] != operation_id:
                return {"attempted": False, "superseded": True}
            job, report = dict(self._job), self._report
            self._executing = True
        terminal_receipt = None
        def notify(**receipt):
            nonlocal terminal_receipt
            correlation=hashlib.sha256(operation_id.encode()).hexdigest()[:16]
            with self.lock:
                previous=self._last_receipt if self._last_receipt.get('correlation_id')==correlation else {}
                self._last_receipt=dict(previous,correlation_id=correlation,
                    **{key:value for key,value in receipt.items() if key in ('transfer_state','reason','retry_after_ms','fresh_ack')})
            if receipt.get("transfer_state") in {"confirmed", "unconfirmed", "failed", "cancelled", "deferred"}:
                # Report terminal hardware receipt only after our finalizer has
                # made cancel() quiescent. Otherwise core revocation could wait
                # forever for an operation whose USB commit already finished.
                terminal_receipt = receipt
            elif report:
                report(operation_id, **receipt)
        try:
            if not self._valid(job):
                result = {"attempted": False, "superseded": True}
            else:
                # Check the REMAINING deadline before claiming a cooldown or
                # touching USB. Queue/IPC delay cannot extend player_ready.
                size = Path(job["content_path"]).stat().st_size
                remaining = (job["deadline_mono_ms"]-self.clock()*1000
                             if job.get("deadline_mono_ms") is not None else None)
                if getattr(self.engine.faceplate, "rotate_180", False):
                    notify(transfer_state="failed", reason="CONTENT_PROFILE_UNSUPPORTED")
                    return {"attempted": False, "error": "Prepared orientation incompatible", "orientation_refused": True}
                if remaining is not None and not timing_admission(size, remaining):
                    notify(transfer_state="cancelled", reason="ALIGNMENT_EXPIRED")
                    return {"attempted": False, "superseded": True, "timing_refused": True}
                port = self.engine.faceplate.port_finder()
                if not port or not self.ownership.claim(port):
                    notify(transfer_state="failed", reason="OWNERSHIP_UNAVAILABLE")
                    return {"attempted": False, "error": "ownership unavailable"}
                flash = getattr(self.engine.faceplate, "flash", None)
                delay = flash.delay("background") if flash is not None else 0.0
                if flash is not None and hasattr(flash, "screensaver_delay"):
                    delay = max(delay, flash.screensaver_delay())
                with self.lock:
                    if self._last_attempt is not None:
                        delay = max(delay, SCREENSAVER_CONTINUITY_SECONDS-(self.clock()-self._last_attempt))
                if delay > 0:
                    notify(transfer_state="deferred", reason="FLASH_DEFERRED", retry_after_ms=int(delay*1000))
                    return {"attempted": False, "deferred": True, "retry_after": delay}
                with open(job["content_path"], "rb") as stream:
                    data = stream.read(196609)
                if len(data) > 196608 or hashlib.sha256(data).hexdigest() != job["content_id"]:
                    raise ValueError("Delegated content identity changed")
                if flash is not None and hasattr(flash, "reserve_screensaver_attempt"):
                    flash.reserve_screensaver_attempt()
                with self.lock:
                    self._last_attempt = self.clock()
                cancelled = request.get("_cancelled")
                def invalid():
                    with self.lock:
                        current = self._job
                        same = current is not None and current.get("operation_id") == operation_id and not current.get("cancelled")
                    return not same or (cancelled is not None and cancelled.is_set()) or not self._valid(job)
                notify(transfer_state="transferring")
                with self.lock:self._display_operation=operation_id
                result = self.engine.faceplate.synchronize_scene(data, "screensaver", job["content_id"],
                    peak_load=float(job.get("peak_load", 1.0)), reason="Delegated screensaver",
                    cancelled=invalid, delegated=True)
            transfer=result.get('transfer') or {}
            if (result.get('synchronized') and not result.get('error') and transfer.get('end_sent')
                    and not transfer.get('sent_unconfirmed')):
                with self.lock:
                    if self._job and self._job['operation_id']==operation_id and not self._job.get('cancelled'):
                        self._lightbar=(job['content_id'],self.clock())
            evidence=dict(correlation_id=hashlib.sha256(operation_id.encode()).hexdigest()[:16],
                attempted=bool(result.get('attempted')),body_written=result.get('wrote') is True,
                synchronized=result.get('synchronized') is True,optical_playback='not-measured')
            for key in ('chunks','begin_status','end_status','begin_ack_ms','end_ack_ms','finalize_ms','total_ms'):
                value=transfer.get(key)
                if type(value) in (int,float) and 0<=value<=3600000:evidence[key]=value
            for key in ('already_stored','end_sent','sent_unconfirmed','payload_complete'):
                if type(transfer.get(key)) is bool:evidence[key]=transfer[key]
            with self.lock:self._last_receipt=evidence
            if result.get("sent_unconfirmed"):
                notify(transfer_state="unconfirmed", reason="USB_UNCONFIRMED")
            elif result.get("superseded") or result.get("cancelled"):
                notify(transfer_state="cancelled")
            elif result.get("deferred"):
                notify(transfer_state="deferred", reason="FLASH_DEFERRED", retry_after_ms=int(result.get("retry_after", 0)*1000))
            elif result.get("synchronized") and not result.get("error"):
                transfer = result.get("transfer") or {}
                # Only a real, new GIF body commit with matching GIF_END ACK
                # qualifies. CRC reuse can never establish phase zero.
                fresh = bool(result.get("wrote") is True and transfer.get("end_sent") and not transfer.get("sent_unconfirmed") and transfer.get("active_profile"))
                notify(transfer_state="confirmed", fresh_ack=fresh)
            else:
                notify(transfer_state="failed", reason=result.get("policy_reason") or "USB_FAILED")
            return result
        except UploadDeferred as error:
            notify(transfer_state="deferred", reason="FLASH_DEFERRED", retry_after_ms=int(error.retry_after*1000))
            return {"attempted": False, "deferred": True, "retry_after": error.retry_after}
        except Exception:
            notify(transfer_state="failed", reason="USB_FAILED")
            return {"attempted": True, "error": "Delegated transfer failed"}
        finally:
            with self.lock:
                self._executing = False
                cancelled_job = self._job is None or self._job.get("cancelled")
                if cancelled_job:
                    self._job = None
                restore = self._restore
                self._restore = None
            if terminal_receipt is not None and report:
                # Preserve late ACKs as receipts without reviving authority.
                report(operation_id, **terminal_receipt)
            if restore:
                self.restore(*restore)
            if self._stopped:
                self.ownership.close()

    def prepare_return(self,operation_id,reason,confirmed):
        # Explicit lifecycle input, never inferred from diagnostic history.
        enabled=self.engine.settings.all().get('faceplate_continuous_home_return',False) is True
        with self.lock:
            self._return_candidate=operation_id if (enabled and confirmed and reason=='STEAM_INACTIVE'
                and not self._executing and self._display_operation==operation_id) else None

    def service_continuous_return(self):
        panel=self.engine.faceplate
        if not isinstance(getattr(panel,'_continuous_return',None),dict):return
        # Evaluate providers/settings on the engine thread, never under the
        # serial lock. Worker cancellation reads only this cached decision.
        self._return_policy_allowed=(self.engine.settings.all().get('faceplate_continuous_home_return',False) is True
            and self._policy()['reason'] is None)
        due=getattr(panel,'continuous_return_needs_stop',None)
        if not callable(due) or not due():return
        now=self.clock()
        if self._return_stop_at is not None and now-self._return_stop_at<1:return
        self._return_stop_at=now
        self.engine.faceplate_worker.submit('return-stop',{'kind':'return-stop'},
            {'scene_class':'control','cancel_active':True,'reason':'continuous-return-expired'})

    def cancel(self, operation_id, reason=None):
        with self.lock:
            if self._job is None or self._job["operation_id"] != operation_id:
                return not self._executing
            self._job["cancelled"] = True
            self._lightbar=None
            quiescent = not self._executing
            if quiescent:
                self._job = None
            self._closed = True
        self.engine.faceplate_worker.cancel_scene_class("broker")
        return quiescent

    def restore(self, operation_id, report=None):
        with self.lock:
            now=self.clock()
            started=self._restore_trace.get('started_at',now) if self._restore_trace.get('operation_id')==operation_id else now
            self._restore_trace=dict(operation_id=operation_id,state='pending',started_at=started,updated_at=now)
            if self._executing:
                self._restore = (operation_id, report)
                self._restore_trace['state']='waiting-transaction'
                return
            self._job = None
            self._restore_pending = (operation_id, report)
        # Reconciliation selects NOW's game/Home and respects off/thermal/etc.
        self.engine._faceplate_next_reconcile = 0.0
        self.engine._faceplate_follow_key = None
        self.engine._faceplate_resume_requested = True
        blocked = bool(self._policy()["reason"])
        if blocked:
            with self.lock:
                self._restore_pending = None
                self._restore_trace.update(state='blocked',updated_at=self.clock())
        elif self._display_operation==operation_id:
            panel=self.engine.faceplate
            arm=getattr(panel,'arm_continuous_return',None)
            self._return_policy_allowed=True # blocked was evaluated outside serial above.
            allowed=lambda:(self._return_policy_allowed and not self.engine._stop.is_set()
                and not self.engine._faceplate_suspended and self.engine._faceplate_power_target is not False)
            if self._return_candidate==operation_id and callable(arm) and arm(operation_id,allowed):
                with self.lock:
                    self._return_candidate=None
                    self._restore_trace.update(exit_stop='continuous',transition='experimental')
                if report:report(operation_id,restore_state='pending')
                return
            with self.lock:
                self._exit_stop=dict(operation_id=operation_id,at=self.clock())
                self._restore_trace['exit_stop']='queued'
            generation=self.engine.faceplate_worker.submit('broker-exit:'+operation_id,
                {'kind':'broker-exit','operation_id':operation_id},
                {'scene_class':'control','reason':'screensaver-exit'})
            if not generation:
                with self.lock:
                    self._exit_stop=None
                    self._restore_trace['exit_stop']='queue-refused'
        if report:
            report(operation_id, restore_state="blocked" if blocked else "pending")

    def execute_exit(self,request):
        """One volatile stop on the sole worker; no flash write or saved Off."""
        operation_id=(request.get('payload') or {}).get('operation_id')
        with self.lock:
            if (not self._exit_stop or self._exit_stop['operation_id']!=operation_id
                    or self._job is not None or self._executing):
                return {'superseded':True}
            self._exit_stop['executing']=True
        try:
            cancelled=request.get('_cancelled')
            if ((cancelled is not None and cancelled.is_set()) or self._policy()['reason']):
                result={'ok':False,'superseded':True}
            else:
                result=self.engine.faceplate.set_power(False,'screensaver-exit')
            with self.lock:
                if self._restore_trace.get('operation_id')==operation_id:
                    self._restore_trace['exit_stop']='confirmed' if result.get('ok') else 'unconfirmed'
            return result
        finally:
            with self.lock:
                if self._exit_stop and self._exit_stop['operation_id']==operation_id:self._exit_stop=None
            self.engine._faceplate_next_reconcile=0.

    def normal_completed(self, result):
        """Observe the current normal route receipt, never a cached snapshot."""
        active=getattr(self.engine.faceplate,'_continuous_return',None)
        if active and (result.get('error') or result.get('sent_unconfirmed')):active['stop']=True
        with self.lock:
            if (self._job is None and not self._executing and result.get('synchronized')
                    and not any(result.get(k) for k in ('error','deferred','sent_unconfirmed'))):
                if (self._restore_pending is None and self._display_operation is not None
                        and self._restore_trace.get('operation_id')==self._display_operation):
                    self._restore_trace.update(state='confirmed',updated_at=self.clock(),
                        late_current_route_receipt=True)
                self._display_operation=None
            pending = self._restore_pending
            if pending is None or self._job is not None or self._executing:
                return
        if result.get("deferred"):
            state = "deferred"
        elif result.get("sent_unconfirmed"):
            state = "unconfirmed"
        elif result.get("synchronized") and not result.get("error"):
            state = "confirmed"
        else:
            state = "unconfirmed"
        operation_id, report = pending
        with self.lock:
            if self._restore_trace.get('operation_id')==operation_id:
                self._restore_trace.update(state=state,updated_at=self.clock())
            if state=='confirmed' and self._display_operation==operation_id:self._display_operation=None
        if state != "deferred":
            with self.lock:
                if self._restore_pending == pending:
                    self._restore_pending = None
        if report:
            report(operation_id, restore_state=state)

    def stop(self):
        self.projection.stop()
        with self.lock:
            self._stopped = True
            self._closed = True
            self._baseline = False
            operation = self._job["operation_id"] if self._job else None
        if operation:
            self.cancel(operation, "client-stopping")
        with self.lock:
            quiescent = not self._executing
        if quiescent:
            self.ownership.close()

