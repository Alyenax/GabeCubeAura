# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Bounded, transactional playlists for the Steam-owned installed player.

Publication copies only broker-validated GIFs. Rotation uses the existing
display lease and adapter; the Studio/browser never owns a playback timer.
"""
from __future__ import annotations
import copy
import hashlib
import os
import stat
from uuid import uuid4
from .core import BrokerError,digest,ident,integer,TERMINAL
from .limits import LIMITS

MAX_BATCHES=512
MAX_BYTES=32*1024**2
MAX_TOTAL=128*1024**2

def valid_rows(rows):
    return (isinstance(rows,list) and 1<=len(rows)<=MAX_BATCHES and
        all(isinstance(r,dict) and set(r)=={'content_id','bytes','duration_cs'} and digest(r['content_id'])
            and integer(r['bytes'],1,LIMITS['max_content_bytes']) and integer(r['duration_cs'],1,LIMITS['max_loop_duration_cs']) for r in rows)
        and sum(r['bytes'] for r in rows)<=MAX_BYTES)

class PlayerBatches:
    def __init__(self,runtime):
        self.runtime=runtime;self.broker=runtime.broker
        self.root=self.broker.root/'player-batches';self.staging={}
        self._directory(self.root)
        # A crash never publishes a partial playlist. Only our private pending
        # directories and bounded, known GIF names are eligible for cleanup.
        for path in self.root.iterdir():
            if path.name.startswith('.pending-') or digest(path.name) and path.name not in runtime.bindings:self._remove(path)

    @staticmethod
    def _directory(path):
        path.mkdir(mode=0o700,exist_ok=True)
        info=path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o700:raise BrokerError('CONTENT_INVALID')

    def _remove(self,path):
        if path.parent!=self.root or path.is_symlink() or not path.is_dir():return
        leaves=list(path.iterdir())
        if any(p.is_symlink() or not p.is_file() or not digest(p.stem) or p.suffix!='.gif' or p.stat().st_uid!=os.geteuid() for p in leaves):return
        for p in leaves:p.unlink(missing_ok=True)
        path.rmdir()

    def cleanup(self):
        for key,s in list(self.staging.items()):
            if self.broker.now_ms()-s['updated']>120000:
                self.staging.pop(key);self._remove(s['path'])

    def remove(self,key):
        stage=self.staging.pop(key,None)
        if stage:self._remove(stage['path'])
        self._remove(self.root/key)

    def _data(self,path,content_id):
        if path.parent.is_symlink():raise BrokerError('CONTENT_INVALID')
        info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_nlink!=1 or not 0<info.st_size<=LIMITS['max_content_bytes']:raise BrokerError('CONTENT_INVALID')
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
        with os.fdopen(fd,'rb') as stream:data=stream.read(LIMITS['max_content_bytes']+1)
        if len(data)!=info.st_size or hashlib.sha256(data).hexdigest()!=content_id:raise BrokerError('CONTENT_INVALID')
        return data

    def _cache(self,content_id,data,metadata):
        b=self.broker
        if content_id in b.contents and b.contents[content_id]['metadata'] is not None:
            if self._data(b.contents[content_id]['path'],content_id)!=data:raise BrokerError('CONTENT_INVALID')
            return
        while len(b.contents)>=LIMITS['max_contents'] or sum(c['size'] for c in b.contents.values())+len(data)>LIMITS['max_cached_content_bytes']:
            key=next((key for key in b.contents if not b._pinned(key)),None)
            if key is None:raise BrokerError('CACHE_FULL')
            b.contents.pop(key)['path'].unlink(missing_ok=True)
        b._disk(len(data));path=b.contents_dir/(content_id+'.gif')
        if path.exists():
            if self._data(path,content_id)!=data:raise BrokerError('CONTENT_INVALID')
        else:
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o400)
            with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        b.contents[content_id]=dict(path=path,size=len(data),metadata=copy.deepcopy(metadata),used=b.now_ms(),owner=None)
        b._queue_extension(content_id,path)

    def publish(self,client,args):
        b=self.broker;r=self.runtime;self.cleanup()
        if (not ident(args['token']) or len(args['token'])<32 or not digest(args['collection_id']) or not digest(args['content_id'])
            or not integer(args['count'],1,MAX_BATCHES) or not integer(args['index'],0,args['count']-1)
            or type(args['alignment_ms']) is not int or args['alignment_ms']!=0):raise BrokerError('INVALID_REQUEST')
        key=hashlib.sha256(args['token'].encode()).hexdigest();content=b.contents.get(args['content_id'])
        if not content or content['metadata'] is None or (client,args['content_id'],args['collection_id']) not in b.registration:raise BrokerError('CONTENT_MISSING')
        existing=r.bindings.get(key)
        if existing:
            rows=existing.get('batches',[])
            if (existing['collection_id']!=args['collection_id'] or len(rows)!=args['count'] or rows[args['index']]['content_id']!=args['content_id']):raise BrokerError('REQUEST_CONFLICT')
            return {**r.descriptor(), 'next_index':len(rows),'published':True}
        if len(r.bindings)>=4:raise BrokerError('CACHE_FULL')
        stage=self.staging.get(key)
        if stage is None:
            if args['index']!=0:raise BrokerError('REQUEST_CONFLICT')
            if len(self.staging)>=2:raise BrokerError('RATE_LIMITED',1000)
            path=self.root/('.pending-'+uuid4().hex);self._directory(path)
            stage=dict(client=client,collection_id=args['collection_id'],count=args['count'],rows=[],metadata=[],bytes=0,path=path,updated=b.now_ms())
            self.staging[key]=stage
        if stage['client']!=client:raise BrokerError('AUTH_DENIED')
        if stage['collection_id']!=args['collection_id'] or stage['count']!=args['count'] or args['index']>len(stage['rows']):raise BrokerError('REQUEST_CONFLICT')
        if args['index']<len(stage['rows']):
            if stage['rows'][args['index']]['content_id']!=args['content_id']:raise BrokerError('REQUEST_CONFLICT')
            if len(stage['rows'])==stage['count']:return self._commit(key,stage)
            return dict(next_index=len(stage['rows']),published=False)
        data=self._data(content['path'],args['content_id'])
        total=sum(sum(row['bytes'] for row in binding.get('batches',[])) for binding in r.bindings.values())+sum(s['bytes'] for s in self.staging.values())
        if stage['bytes']+len(data)>MAX_BYTES or total+len(data)>MAX_TOTAL:raise BrokerError('CONTENT_TOO_LARGE')
        b._disk(len(data));path=stage['path']/(args['content_id']+'.gif')
        if not path.exists():
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o400)
            with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        row=dict(content_id=args['content_id'],bytes=len(data),duration_cs=content['metadata']['duration_cs'])
        stage['rows'].append(row);stage['metadata'].append(copy.deepcopy(content['metadata']));stage['bytes']+=len(data);stage['updated']=b.now_ms()
        if len(stage['rows'])<stage['count']:return dict(next_index=len(stage['rows']),published=False)
        return self._commit(key,stage)

    def _commit(self,key,stage):
        b=self.broker;r=self.runtime
        target=self.root/key
        if target.exists():raise BrokerError('CONTENT_INVALID')
        first=stage['rows'][0];first_data=self._data(stage['path']/(first['content_id']+'.gif'),first['content_id'])
        self._cache(first['content_id'],first_data,stage['metadata'][0])
        binding=dict(content_id=first['content_id'],collection_id=stage['collection_id'],mode='async',alignment_ms=0,batches=stage['rows'])
        stage['path'].rename(target)
        try:r._save({**r.bindings,key:binding})
        except (OSError,ValueError,TypeError):
            self._remove(target);self.staging.pop(key,None);raise BrokerError('CONTENT_INVALID') from None
        self.staging.pop(key,None);r._event('batches-published')
        return {**r.descriptor(),'next_index':stage['count'],'published':True}

    def first(self,key,binding):
        content_id=binding['content_id'];content=self.broker.contents.get(content_id)
        if content and content['metadata'] is not None:return
        path=self.root/key/(content_id+'.gif');data=self._data(path,content_id)
        metadata=self.broker.validator(path,content_id)
        if 'error' in metadata:raise BrokerError(metadata['error'])
        self._cache(content_id,data,metadata)

    def deferred(self,lease,retry_after_ms):
        previous=lease.pop('batch_previous',None)
        if not previous:return False
        lease.update(content_id=previous[0],batch_index=previous[1],transfer_state='confirmed',quiescent=True,
            batch_deadline=self.broker.now_ms()+max(5000,retry_after_ms),batch_error='FLASH_DEFERRED',reason=None)
        self.runtime._event('batch-deferred','FLASH_DEFERRED')
        return True

    def attach(self,lease,key):
        rows=self.runtime.bindings.get(key,{}).get('batches')
        if rows:
            lease.update(batch_binding=key,batch_index=0,batch_advancing=False)
            if lease['transfer_state']=='confirmed':self.confirmed(lease)

    def confirmed(self,lease):
        binding=self.runtime.bindings.get(lease.get('batch_binding'),{});rows=binding.get('batches')
        lease.pop('batch_previous',None)
        if rows:lease['batch_deadline']=self.broker.now_ms()+max(LIMITS['screensaver_min_attempt_interval_ms'],rows[lease['batch_index']]['duration_cs']*10)

    def tick(self):
        b=self.broker;lease=b.lease
        if (not lease or not lease.get('gca_owned') or not lease.get('batch_binding') or lease.get('batch_advancing')
            or lease['lease_state'] in TERMINAL|{'revoking'} or lease['transfer_state']!='confirmed'
            or b.now_ms()<lease.get('batch_deadline',2**63)):return
        rows=self.runtime.bindings.get(lease['batch_binding'],{}).get('batches',[])
        if len(rows)<2:return
        lease['batch_advancing']=True
        try:b.worker.submit(self._advance,lease['operation_id'],lease['generation'],lease['batch_binding'],lease['batch_index'])
        except RuntimeError:lease['batch_advancing']=False

    def _advance(self,operation,generation,key,index):
        b=self.broker;r=self.runtime
        try:
            with b.lock:
                binding=copy.deepcopy(r.bindings.get(key,{}));rows=binding.get('batches',[])
                if not rows:return
                next_index=(index+1)%len(rows);row=rows[next_index];path=self.root/key/(row['content_id']+'.gif')
            data=self._data(path,row['content_id']);metadata=b.validator(path,row['content_id'])
            if 'error' in metadata:raise BrokerError(metadata['error'])
            with b.lock:
                lease=b.operations.get(operation)
                if (b.stopped or lease is None or lease is not b.lease or lease['generation']!=generation or lease.get('batch_binding')!=key
                    or lease.get('batch_index')!=index or not lease.get('gca_owned') or not b.is_valid(operation) or key not in r.bindings):return
                b._policy(lease['activation_id'],flash=True,continuity=True)
                self._cache(row['content_id'],data,metadata)
                previous=(lease['content_id'],lease.get('transfer_serial',0))
                lease.update(content_id=row['content_id'],transfer_serial=previous[1]+1,transfer_state='queued',quiescent=False,batch_index=next_index,batch_previous=(previous[0],index))
                replace=getattr(b.adapter,'replace',None)
                if not callable(replace) or not replace(b._job(lease),b._reporter(lease)):
                    if lease is b.lease and lease['lease_state'] not in TERMINAL|{'revoking'}:
                        lease.update(content_id=previous[0],transfer_state='confirmed',quiescent=True,batch_index=index,batch_deadline=b.now_ms()+5000)
                        lease.pop('batch_previous',None)
                    return
                lease['batch_index']=next_index;lease.pop('batch_error',None)
                r._event('batch-queued')
        except (OSError,ValueError,KeyError,BrokerError) as error:
            with b.lock:
                lease=b.operations.get(operation)
                if lease and lease is b.lease and lease['generation']==generation:
                    lease['batch_error']=getattr(error,'code','CONTENT_INVALID');lease['batch_deadline']=b.now_ms()+30000
                    r._event('batch-deferred',lease['batch_error'])
        finally:
            with b.lock:
                lease=b.operations.get(operation)
                if lease and lease['generation']==generation:lease['batch_advancing']=False
