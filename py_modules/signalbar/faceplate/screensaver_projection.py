"""Bounded whole-image/bottom-edge LED timelines from an admitted RGB332 GIF.

No serial access, screenshot capture, Pillow or persistent companion process.
Parsing/projection runs in a disposable child; output() only indexes memory.
"""
from bisect import bisect_right
from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

MAX_OUTPUT=2*1024*1024
PALETTE=tuple((round(r*255/7),round(g*255/7),round(b*255/3))
              for r in range(8) for g in range(8) for b in range(4))

def whole_frame(indices,mapping='whole'):
    if mapping not in ('whole','bottom'):raise ValueError('PROJECTION_MAPPING')
    columns=[[0,0,0] for _ in range(64)]
    for n,index in enumerate(indices):
        if mapping=='bottom' and n<64*46:continue
        rgb=PALETTE[index];column=columns[n%64]
        for c in range(3):column[c]+=rgb[c]
    colours=[]
    for led in range(17):
        totals=[0,0,0];left,right=led*64,(led+1)*64
        for x in range(left//17,min(64,(right+16)//17)):
            weight=min(right,(x+1)*17)-max(left,x*17)
            for c in range(3):totals[c]+=columns[x][c]*weight
        divisor=64*(8 if mapping=='bottom' else 54)
        colours.extend((value+divisor//2)//divisor for value in totals)
    return bytes(colours)

def prepare(path,digest):
    # The caller supplies a private immutable content path, never a client URL.
    if __package__:
        from ..jsaux_broker.validator import validate_bytes
    else:
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'jsaux_broker'))
        from validator import validate_bytes
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    with os.fdopen(fd,'rb') as stream:data=stream.read(196609)
    if len(data)>196608 or hashlib.sha256(data).hexdigest()!=digest:raise ValueError('CONTENT_INVALID')
    rows=[];bottom_rows=[]
    def collect(indices,delay):
        for target,mapping in ((rows,'whole'),(bottom_rows,'bottom')):
            colour=whole_frame(indices,mapping).hex()
            if target and target[-1][1]==colour:target[-1][0]+=delay
            else:target.append([delay,colour])
    meta=validate_bytes(data,on_frame=collect)
    return dict(duration_cs=meta['duration_cs'],rows=rows,bottom_rows=bottom_rows)

class ScreensaverProjection:
    def __init__(self):
        self.lock=threading.RLock();self.cache=OrderedDict();self.process=None;self.closed=False
        self.last_state='idle'
        self.last_error=''

    def prepare(self,content_id,path):
        with self.lock:
            if self.closed or content_id in self.cache:return
            self.last_state='preparing'
            self.last_error=''
        candidates=[sys.executable] if Path(sys.executable).name.startswith('python') else []
        candidates+=['/usr/bin/python3','/usr/local/bin/python3']
        interpreter=next((p for p in candidates if Path(p).is_file() and os.access(p,os.X_OK)),None)
        if not interpreter:
            with self.lock:self.last_state='unavailable';self.last_error='PYTHON_MISSING'
            return
        process=None
        try:
            with self.lock:
                if self.closed:return
                process=subprocess.Popen([interpreter,'-I',str(Path(__file__).resolve()),str(path),content_id],
                    stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                    close_fds=True,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'})
                self.process=process
            raw,_=process.communicate(timeout=10)
            if process.returncode:raise ValueError('PROJECTION_CHILD_FAILED')
            if len(raw)>MAX_OUTPUT:raise ValueError('PROJECTION_LIMIT')
            self.install(content_id,json.loads(raw))
        except (OSError,ValueError,subprocess.TimeoutExpired) as error:
            if process is not None:
                if process.poll() is None:process.kill()
                process.communicate()
            with self.lock:
                self.last_state='unavailable'
                self.last_error=('PROJECTION_TIMEOUT' if isinstance(error,subprocess.TimeoutExpired) else
                    str(error) if str(error) in ('PROJECTION_LIMIT','PROJECTION_CHILD_FAILED') else 'PROJECTION_INVALID')
        finally:
            with self.lock:
                if self.process is process:self.process=None

    def install(self,content_id,value):
        if not isinstance(value,dict):raise ValueError('PROJECTION_LIMIT')
        whole=self._timeline(value.get('rows'),value.get('duration_cs'))
        bottom=self._timeline(value.get('bottom_rows',value.get('rows')),value.get('duration_cs'))
        with self.lock:
            if self.closed:return
            self.cache[content_id]={'whole':whole,'bottom':bottom};self.cache.move_to_end(content_id)
            while len(self.cache)>4:self.cache.popitem(last=False)
            self.last_state='ready'

    @staticmethod
    def _timeline(rows,duration):
        if not isinstance(rows,list) or not 1<=len(rows)<=6000:raise ValueError('PROJECTION_LIMIT')
        frames=[];ends=[];total=0
        for row in rows:
            if not isinstance(row,list) or len(row)!=2 or type(row[0]) is not int or not 0<=row[0]<=2400000:raise ValueError('PROJECTION_LIMIT')
            if not isinstance(row[1],str) or len(row[1])!=102:raise ValueError('PROJECTION_LIMIT')
            raw=bytes.fromhex(row[1])
            if len(raw)!=51:raise ValueError('PROJECTION_LIMIT')
            total+=row[0];ends.append(total);frames.append(raw)
        if type(duration) is not int or total!=duration or total>2400000:raise ValueError('PROJECTION_LIMIT')
        return total,tuple(ends),tuple(frames)

    def output(self,content_id,elapsed,mapping='whole'):
        with self.lock:timelines=self.cache.get(content_id)
        if timelines is None or mapping not in ('whole','bottom'):return None
        timeline=timelines[mapping]
        total,ends,frames=timeline
        position=max(0,int(elapsed*100))%total if total else 0
        raw=frames[min(bisect_right(ends,position),len(frames)-1)] if total else frames[0]
        return tuple(tuple(raw[n:n+3]) for n in range(0,51,3))

    def stop(self):
        with self.lock:
            self.closed=True;self.cache.clear();process=self.process
            if process is not None and process.poll() is None:process.terminate()

    def snapshot(self):
        with self.lock:return dict(state=self.last_state,cached_collections=len(self.cache),error=self.last_error)

    def contains(self,content_id):
        with self.lock:return content_id in self.cache

if __name__=='__main__':
    import resource
    resource.setrlimit(resource.RLIMIT_CPU,(5,5))
    if sys.platform!='darwin':resource.setrlimit(resource.RLIMIT_AS,(67108864,67108864))
    resource.setrlimit(resource.RLIMIT_FSIZE,(0,0));resource.setrlimit(resource.RLIMIT_NOFILE,(16,16))
    try:
        result=json.dumps(prepare(sys.argv[1],sys.argv[2]),separators=(',',':'))
        if len(result)>MAX_OUTPUT:raise ValueError('PROJECTION_LIMIT')
        print(result)
    except Exception:sys.exit(1)
