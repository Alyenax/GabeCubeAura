"""Voice assistant settings, read from voice.json in the plugin's settings folder.

This lives in its own file instead of the main settings store on purpose.
It's a scaffold. Nobody needs a UI toggle for something that can't answer yet,
and a file you have to create by hand is about as off by default as it gets. No file, or "enabled": false, means nothing below ever loads.

The defaults are sized for a stock Steam Machine with 16 GB of system RAM.
Rough budget with everything loaded at once:

    openWakeWord (hey_jarvis)           tiny, well under 100 MB
    Parakeet TDT 0.6B v2, ONNX on CPU   about 1-2 GB
    Qwen3 4B Instruct Q4_K_M            about 2.5 GB, plus a bit of KV cache
    Piper medium voice                  about 60-100 MB

So roughly 4 GB on top of SteamOS and Steam's UI. That's fine at the Home
screen and not fine during a game, which is why the assistant drops all of it
when a game starts. We think the GPU has its own 8 GB of GDDR6, and if that's
right the Qwen weights go there through llama.cpp's Vulkan build and system RAM
only carries the rest. I haven't confirmed the 8 GB, so treat it as a guess.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil

FILENAME = "voice.json"
# Cloud mode's API key, one line, next to voice.json. Kept out of voice.json
# so it can't end up in a settings export, and refused unless only its owner
# can read it (chmod 600).
KEY_FILENAME = "voice-key"
# Everything the optional pieces need lives in /home, because SteamOS replaces
# the read-only root on every update. See docs/VOICE.md for the layout.
HOME = "/home/deck/voice"

DEFAULTS = {
    "enabled": False,
    # The venv's Python. The whole pipeline runs under it as its own process,
    # because Decky's bundled 3.11 can't load packages built for SteamOS's
    # 3.13. Any Python works here as long as the packages were installed with
    # it. See __main__.py.
    "python": HOME + "/venv/bin/python",
    # "local" keeps everything on the machine: Parakeet, Qwen, Piper.
    # "cloud" sends the recording to a cloud model instead. See cloud.py
    # before turning that on, because it breaks the plugin's local-only rule.
    "mode": "local",

    # Stock openWakeWord model, fine for testing. A custom "hey Gabe" gets
    # trained with openWakeWord's training notebook and goes here as a path to
    # the .onnx file.
    "wake_word": "hey_jarvis",
    # openWakeWord's own docs suggest 0.5 as a starting point. Raise it if
    # the TV keeps waking it up.
    "wake_threshold": 0.5,

    # onnx-asr model name. v2 is English only and the most accurate; swap in
    # "nemo-parakeet-tdt-0.6b-v3" if you want other languages. onnx-asr pulls
    # the weights from Hugging Face on first load unless stt_path points at a
    # local copy, and a local copy is what you want on a console.
    "stt_model": "nemo-parakeet-tdt-0.6b-v2",
    "stt_path": "",

    # Qwen3 4B Instruct at Q4_K_M (about 2.5 GB) is the smallest Qwen I'd
    # trust with tool calls, which matters if this ever drives Home Assistant.
    # Qwen3 1.7B at Q4_K_M (about 1.2 GB) is the light fallback if 4B is too
    # slow or too big (it thinks out loud by default, so add /no_think to the
    # system prompt if you switch). On a machine with 32 GB, Qwen3 8B fits. Point
    # llm_model at a different GGUF and that's the whole change. GGUF builds
    # are on Hugging Face (Qwen's own Qwen3 repos, or unsloth's
    # Qwen3-4B-Instruct-2507-GGUF).
    "llm_model": HOME + "/models/Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
    # The Vulkan build of llama.cpp's llama-server, which runs on AMD.
    "llm_server": HOME + "/llama.cpp/bin/llama-server",
    # Off the usual 8080 so it doesn't collide with anything else on the box.
    "llm_port": 8079,
    # 99 means "put every layer on the GPU". Drop it to split the model with
    # the CPU if the GPU turns out to be short on memory.
    "llm_gpu_layers": 99,
    # Short questions and short answers. 4096 keeps the KV cache small.
    "llm_context": 4096,
    "llm_system_prompt": (
        "You are Gabe, the voice of a Steam Machine. Answer in one or two short "
        "spoken sentences. No lists, no markdown."
    ),
    # "on_wake": start llama-server when the wake word fires and stop it when
    # a game starts. "resident": keep it loaded whenever no game runs. More in
    # brain.py.
    "warm": "on_wake",

    # Piper medium English voice (about 60 MB), from rhasspy/piper-voices on
    # Hugging Face. en_GB-alan-medium is there too if you want it to sound
    # like the repo spells.
    "tts_voice": HOME + "/piper/en_US-lessac-medium.onnx",
    "tts_binary": HOME + "/piper/piper",

    # Cloud mode only. The one provider written so far is "openai". The model
    # name changes often, so check OpenAI's docs for the current audio one.
    "cloud_provider": "openai",
    "cloud_model": "gpt-4o-mini-audio-preview",
    "cloud_voice": "alloy",

    # Folder of pre-made mood GIFs: idle.gif, curious.gif, thinking.gif,
    # talking.gif. See face.py for why they're files and not drawn live.
    "faces_dir": HOME + "/faces",

    # Give up listening after this long even if the room never goes quiet.
    "listen_seconds": 8.0,
    # How long a gap counts as "done talking".
    "silence_seconds": 0.8,
}


def load(settings_dir):
    """Return the settings merged over the defaults. Bad or missing file means off."""
    values = dict(DEFAULTS)
    path = os.path.join(settings_dir or "", FILENAME)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return values
    if isinstance(raw, dict):
        values.update({key: raw[key] for key in DEFAULTS if key in raw})
    values["enabled"] = values["enabled"] is True
    if values["mode"] not in ("local", "cloud"):
        values["mode"] = "local"
    return values


def read_key(settings_dir):
    """Return the cloud key, or "" when there's no usable key file."""
    path = os.path.join(settings_dir or "", KEY_FILENAME)
    try:
        if os.stat(path).st_mode & 0o077:
            return ""
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def missing(values, find_spec=importlib.util.find_spec, which=shutil.which,
            exists=os.path.exists):
    """List what's missing. Runs in the voice process, under the venv's Python.
    find_spec looks for a module without importing it, so this is quick."""
    gaps = []
    local = values["mode"] == "local"
    # Cloud mode skips Parakeet and Qwen. Piper is only needed if the
    # provider answers in text, so it isn't a hard requirement there.
    for module in ("numpy", "openwakeword") + (("onnx_asr",) if local else ()):
        try:
            found = find_spec(module) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            gaps.append(module)
    for tool in ("pw-record", "pw-play"):
        if not which(tool):
            gaps.append(tool)
    for key in ("llm_server", "llm_model", "tts_binary", "tts_voice") if local else ():
        if not exists(values[key]):
            gaps.append(key + " " + str(values[key]))
    return gaps
