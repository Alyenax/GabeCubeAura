"""Voice assistant scaffold: say "hey Gabe", ask something, hear an answer.

USB mic, openWakeWord, Parakeet for the words, Qwen for the answer, Piper to
say it, and a face on the JSAUX faceplate if one's fitted. The plugin only
loads supervisor.py. The models run in a separate process under a venv's
Python. Off unless voice.json turns it on. docs/VOICE.md has the setup and
what's left.
"""

from __future__ import annotations

from .supervisor import Supervisor, VoiceOff, build

__all__ = ["Supervisor", "VoiceOff", "build"]
