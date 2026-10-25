#!/usr/bin/env python3
"""One-shot, low-priority original RGB reduction; never runs in Decky/LED loop."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from signalbar.faceplate.source_projection import load_source, project_backgrounds

def main():
    try:
        text = sys.stdin.read(4097)
        if len(text) > 4096: raise ValueError('Projection request too large')
        request = json.loads(text)
        frames = load_source(request['source'])
        colours = project_backgrounds(frames, request['mapping'], request['rotate'],
            height=45 if request['source'].get('kind') == 'player-city' else 54)
        print(json.dumps({'ok': True, 'colours': colours, 'frames': len(frames)}))
        return 0
    except (OSError, ValueError, TypeError, KeyError):
        print(json.dumps({'ok': False, 'error': 'Source background unavailable or invalid'}))
        return 1

if __name__ == '__main__': sys.exit(main())
