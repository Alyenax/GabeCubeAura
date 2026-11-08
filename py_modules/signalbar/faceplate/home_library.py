# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Prepared-only Home playlist. Inventory I/O never runs on the LED thread."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
from pathlib import Path
import random
import threading
import time

from .steamgriddb import _read_json, MAX_GIF_BYTES


@dataclass(frozen=True)
class PreparedItem:
    key: str
    source: str
    path: Path
    manifest: dict

    def load(self):
        data = self.path.read_bytes()
        if not 0 < len(data) <= MAX_GIF_BYTES or hashlib.sha256(data).hexdigest() != self.manifest.get('sha256'):
            raise ValueError('Prepared library GIF changed')
        return data, {**self.manifest, 'appid': 0}, self.path

    def pack_reference(self):
        path = self.path.parent / 'artwork-dashboard.rgb'
        count = self.manifest.get('dashboard_pack_frames', 0)
        try:
            if type(count) is not int or not 1 <= count <= 80 or path.is_symlink() or path.stat().st_size != count*64*54*3:
                return None
        except OSError:
            return None
        return {**self.manifest, 'appid': 0}, path


def _item(root, source, key):
    if any(path.is_symlink() for path in (root, *root.parents)):
        return None
    manifest_path = root / 'manifest.json'
    path = root / 'faceplate.gif'
    if manifest_path.is_symlink() or path.is_symlink():
        return None
    manifest = _read_json(manifest_path, maximum=65536)
    if not manifest.get('ready') or not isinstance(manifest.get('sha256'), str):
        return None
    if source == 'artwork' and manifest.get('asset_kind', 'grid') not in {'grid', 'hero'}:
        return None
    try:
        if not 0 < path.stat().st_size <= MAX_GIF_BYTES:
            return None
    except OSError:
        return None
    return PreparedItem(key, source, path, manifest)


def inventory(library, source):
    entries=[]
    if library is None:
        return entries
    if source in {'artwork', 'both'}:
        try:
            roots=sorted(library.artwork_root.iterdir(), key=lambda path:path.name)
        except OSError:
            roots=[]
        for root in roots:
            if not root.name.isdigit() or root.is_symlink():
                continue
            for stage in ('prepared', 'draft'):
                for mode in ('static', 'animated', 'pan'):
                    item=_item(root/stage/mode,'artwork',f'artwork:{root.name}:{stage}:{mode}')
                    if item:entries.append(item)
    store=getattr(library,'independent_creations',None)
    if source in {'creations', 'both'} and store is not None:
        for record in store.entries():
            item=_item(store.directory(record['creation_id']),'creations','creation:'+record['creation_id'])
            if item:entries.append(item)
    # One visual is shown once even if assigned to multiple destinations.
    unique={}
    for item in entries:
        unique.setdefault(item.manifest['sha256'],item)
    return list(unique.values())


class HomeLibrary:
    def __init__(self, library, *, clock=time.monotonic, rng=None, loader=inventory):
        self.library=library;self.clock=clock;self.rng=rng or random.Random();self.loader=loader
        self.lock=threading.RLock();self.items=[];self.current_key='';self.deadline=0.
        self.options=None;self.bag=[];self.loaded=False;self.loading=False
        self.last_refresh=0.;self.epoch=0;self.stopped=False

    def _refresh(self, source, epoch):
        try:items=self.loader(self.library,source)
        except (OSError,ValueError,TypeError):items=[]
        with self.lock:
            if epoch!=self.epoch or self.stopped:return
            keys={item.key for item in items}
            if keys!={item.key for item in self.items}:self.bag=[]
            self.items=items;self.loaded=True;self.loading=False;self.last_refresh=self.clock()

    def _request_refresh(self, source):
        if self.loading or self.stopped:return
        self.loading=True
        threading.Thread(target=self._refresh,args=(source,self.epoch),daemon=True,name='faceplate-home-library').start()

    def current(self, source='artwork', shuffle=False, interval=300):
        if source not in {'artwork','creations','both'}:source='artwork'
        if interval not in {300,900,1800,3600}:interval=300
        with self.lock:
            options=(source,bool(shuffle),interval)
            if self.options!=options:
                source_changed=self.options is None or self.options[0]!=source
                self.options=options;self.deadline=self.clock()+interval if self.current_key and not source_changed else 0.;self.bag=[]
                if source_changed:
                    self.epoch+=1;self.items=[];self.current_key='';self.loaded=False;self.loading=False
            now=self.clock()
            if not self.loaded or now-self.last_refresh>=60:self._request_refresh(source)
            if not self.items:return None
            current=next((item for item in self.items if item.key==self.current_key),None)
            if current is not None and now<self.deadline:return current
            if shuffle:
                if not self.bag:
                    self.bag=[item.key for item in self.items];self.rng.shuffle(self.bag)
                    if len(self.bag)>1 and self.bag[0]==self.current_key:self.bag.append(self.bag.pop(0))
                key=self.bag.pop(0)
                current=next((item for item in self.items if item.key==key),self.items[0])
            else:
                index=next((i for i,item in enumerate(self.items) if item.key==self.current_key),-1)
                current=self.items[(index+1)%len(self.items)]
            self.current_key=current.key;self.deadline=now+interval
            return current

    def status(self):
        with self.lock:
            return {'count':len(self.items),'loading':self.loading,
                'supports_creations':getattr(self.library,'independent_creations',None) is not None}

    def stop(self):
        with self.lock:self.stopped=True;self.epoch+=1
