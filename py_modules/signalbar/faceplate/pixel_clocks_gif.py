# SPDX-License-Identifier: GPL-3.0-only
"""Bounded lossless finite native-GIF validation for external clock packets."""
import json
import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from signalbar.faceplate.gif_transform import _decode_lzw, _subblocks


def inspect(data):
    if not 14 <= len(data) <= 81920 or data[:6] not in (b'GIF87a', b'GIF89a'):
        raise ValueError('invalid bounded GIF')
    if data[6:10] != b'\x40\0\x36\0' or not data[10] & 128:
        raise ValueError('expected native64x54 global palette')
    pos = 13
    count = 1 << ((data[10] & 7) + 1)
    global_palette = data[pos:pos+3*count]; pos += 3*count
    if len(global_palette) != 3*count:
        raise ValueError('truncated palette')
    frames = duration = 0
    gce = None
    composite = bytearray(64*54*3)
    peak = 0.
    while pos < len(data):
        tag = data[pos]; pos += 1
        if tag == 0x3b:
            if pos != len(data) or not frames or gce is not None or not 0 < duration <= 7600:
                raise ValueError('invalid finite timeline')
            return dict(frames=frames, duration_cs=duration, peak_load=peak)
        if tag == 0x21:
            if pos >= len(data): raise ValueError('truncated extension')
            label=data[pos];pos+=1
            if label != 0xf9 or gce is not None or pos+6 > len(data):
                raise ValueError('only finite graphics-control extensions allowed')
            if data[pos] != 4 or data[pos+5] != 0: raise ValueError('invalid GCE')
            flags=data[pos+1]; delay=int.from_bytes(data[pos+2:pos+4],'little')
            if flags & 0xe2 or ((flags>>2)&7) not in (0,1) or not delay:
                raise ValueError('unsupported disposal/delay')
            gce=(delay,data[pos+4] if flags&1 else None);pos+=6;continue
        if tag != 0x2c or gce is None or pos+9 > len(data): raise ValueError('invalid image block')
        left=int.from_bytes(data[pos:pos+2],'little');top=int.from_bytes(data[pos+2:pos+4],'little')
        width=int.from_bytes(data[pos+4:pos+6],'little');height=int.from_bytes(data[pos+6:pos+8],'little');flags=data[pos+8];pos+=9
        if not width or not height or left+width>64 or top+height>54 or flags&0x78:
            raise ValueError('invalid image rectangle')
        palette=global_palette
        if flags&128:
            n=3*(1<<((flags&7)+1));palette=data[pos:pos+n];pos+=n
            if len(palette)!=n:raise ValueError('truncated local palette')
        if pos>=len(data):raise ValueError('truncated image')
        minimum=data[pos];pos+=1
        packed,pos=_subblocks(data,pos)
        indices=_decode_lzw(packed,minimum,width*height)
        delay,transparent=gce;gce=None
        if not frames and ((left,top,width,height)!=(0,0,64,54) or transparent is not None):
            raise ValueError('first frame must be complete and opaque')
        for i,index in enumerate(indices):
            if index==transparent:continue
            if index*3+3>len(palette):raise ValueError('invalid palette index')
            x=left+i%width;y=top+i//width;o=(y*64+x)*3
            composite[o:o+3]=palette[index*3:index*3+3]
        frames+=1;duration+=delay
        if frames>1024 or duration>7600:raise ValueError('clock timeline budget exceeded')
        peak=max(peak,sum(composite)/(64*54*765))
    raise ValueError('missing trailer')


def rotate(data):
    """Rotate native partial/local-palette packets without changing any RGB."""
    inspect(data)
    from signalbar.faceplate.gif import _lzw, _sub_blocks
    pos=13+3*(1<<((data[10]&7)+1));out=bytearray(data[:pos])
    while pos<len(data):
        tag=data[pos]
        if tag==0x3b:out.append(tag);break
        if tag==0x21:
            out.extend(data[pos:pos+8]);pos+=8;continue
        descriptor=bytearray(data[pos:pos+10]);pos+=10
        left=int.from_bytes(descriptor[1:3],'little');top=int.from_bytes(descriptor[3:5],'little')
        width=int.from_bytes(descriptor[5:7],'little');height=int.from_bytes(descriptor[7:9],'little')
        descriptor[1:3]=(64-left-width).to_bytes(2,'little');descriptor[3:5]=(54-top-height).to_bytes(2,'little')
        out.extend(descriptor)
        if descriptor[9]&128:
            n=3*(1<<((descriptor[9]&7)+1));out.extend(data[pos:pos+n]);pos+=n
        minimum=data[pos];pos+=1;packed,pos=_subblocks(data,pos)
        values=_decode_lzw(packed,minimum,width*height)
        out.append(minimum);out.extend(_sub_blocks(_lzw(values[::-1],minimum)))
    result=bytes(out)
    if len(result)>81920:raise ValueError('Rotated clock exceeds synchronized budget')
    inspect(result)
    return result


if __name__=='__main__':
    try:
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU,(5,5))
            # macOS cannot enforce RLIMIT_AS reliably; decoder is bounded above.
            if sys.platform!='darwin':resource.setrlimit(resource.RLIMIT_AS,(128*1024**2,128*1024**2))
        except ImportError:pass
        data=Path(sys.argv[1]).read_bytes()
        print(json.dumps(dict(ok=True,**inspect(data))))
    except Exception as error:
        print(json.dumps(dict(ok=False,error=str(error)[:120])));sys.exit(1)
