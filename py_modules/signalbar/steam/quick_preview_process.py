"""Decode only frame zero, in a bounded disposable process, never in Decky."""
import io
import os
from pathlib import Path
import shutil
import sys
import warnings


def native_decoder(path):
    """Replace this worker, not spawn a grandchild surviving RPC timeouts."""
    ffmpeg = shutil.which('ffmpeg')
    if ffmpeg:
        command = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin',
            '-threads', '1', '-filter_threads', '1', '-i', str(path),
            '-frames:v', '1', '-vf', 'scale=320:160:force_original_aspect_ratio=decrease',
            '-an', '-sn', '-dn', '-c:v', 'mjpeg', '-threads', '1', '-q:v', '4',
            '-f', 'image2pipe', 'pipe:1']
    else:
        gst = shutil.which('gst-launch-1.0')
        if not gst:
            print('quick-preview:decoder-unavailable', file=sys.stderr)
            return 2
        command = [gst, '-q', 'filesrc', 'location='+str(path), '!', 'decodebin',
            '!', 'videoconvert', '!', 'videoscale', 'add-borders=true',
            '!', 'video/x-raw,format=RGB,width=320,height=160,pixel-aspect-ratio=1/1',
            '!', 'jpegenc', 'snapshot=true', 'quality=82', '!', 'fdsink', 'fd=1']
    os.execv(command[0], command)


def main():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
        # macOS RLIMIT_AS is not supported. SteamOS isolates image memory too.
        if sys.platform.startswith('linux'):
            resource.setrlimit(resource.RLIMIT_AS, (1024*1024*1024, 1024*1024*1024))
        path = Path(sys.argv[1])
        if not path.is_file() or not 0 < path.stat().st_size <= 12*1024*1024: return 1
        try:
            from PIL import Image
        except ImportError:
            return native_decoder(path)
        Image.MAX_IMAGE_PIXELS = 8_000_000
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(path) as source:
            source.seek(0)
            source.thumbnail((320,160), Image.Resampling.LANCZOS)
            image = source.convert('RGB')
            output = io.BytesIO()
            image.save(output, format='JPEG', quality=82, optimize=True)
        data = output.getvalue()
        if len(data) > 128*1024: return 1
        sys.stdout.buffer.write(data)
        return 0
    except Exception:
        print('quick-preview:decode-failed', file=sys.stderr)
        return 1


if __name__ == '__main__': sys.exit(main())
