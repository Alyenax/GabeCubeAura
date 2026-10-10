"""The thinking part: Qwen, served by llama.cpp's llama-server.

llama-server has an OpenAI-style /v1/chat/completions endpoint on localhost,
so plain urllib is enough and there's no SDK to install. The Vulkan build runs
on the Steam Machine's AMD GPU. With every layer offloaded, the 4B model
should mostly sit in GPU memory instead of the 16 GB of system RAM, assuming
the GPU really has the 8 GB of its own we think it does.

The assistant starts and stops llama-server itself, because stopping the
process is the only reliable way I know to get the memory back. That's the
whole point when a game starts.

When to warm it up is the question I'm least sure about. Two options:

on_wake (the default). llama-server starts the moment the wake word fires.
Loading a 2.5 GB model takes a few seconds, and the person is still talking
for a few seconds, so with luck the two overlap and the answer isn't held up
much. Nothing sits in memory while nobody's talking to it.

resident. Keep it loaded whenever no game is running and stop it when one
starts. Faster answers, but 2.5 GB sits there the whole time you're at the
Home screen. Fine on a machine with RAM to spare, less fine on a stock one.

Either way it gets stopped when a game starts and comes back lazily after.
I think as the wake word comes up is when you probably warm up Qwen, but I'd
time both on real hardware before deciding.

A Home Assistant hand-off fits right here, too. Instead of (or before) asking
Qwen, post the text to HA's Assist conversation API and let it run the
house. I run something like that at home, modelled on MU/TH/UR from Alien.
Not built here, just the obvious place for it.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
import urllib.error
import urllib.request

from .session import user_command

# How long to wait for llama-server to load the model. Generous because the
# first load after boot reads the GGUF from disk cold.
LOAD_TIMEOUT = 60.0
# Spoken answers should be short. This caps a runaway one.
MAX_TOKENS = 200


class Brain:
    def __init__(self, server, model, port=8079, gpu_layers=99, context=4096,
                 system_prompt="", logger=None, popen=subprocess.Popen,
                 urlopen=urllib.request.urlopen):
        self.server = server
        self.model = model
        self.port = int(port)
        self.gpu_layers = int(gpu_layers)
        self.context = int(context)
        self.system_prompt = system_prompt
        self.log = logger
        self._popen = popen
        self._urlopen = urlopen
        self._process = None
        self._ready = threading.Event()
        self._lock = threading.Lock()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def warm_up(self):
        """Start llama-server in the background and return straight away."""
        with self._lock:
            if self._process and self._process.poll() is None:
                return
            self._ready.clear()
            command, env = user_command([
                self.server, "--model", self.model,
                "--host", "127.0.0.1", "--port", str(self.port),
                "--n-gpu-layers", str(self.gpu_layers), "--ctx-size", str(self.context),
            ])
            self._process = self._popen(
                command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL, env=env,
            )
        threading.Thread(target=self._wait_until_ready, name="gabecubeaura-voice-warm",
                         daemon=True).start()

    def _wait_until_ready(self):
        # /health answers 503 while the model loads and 200 once it's ready.
        deadline = time.monotonic() + LOAD_TIMEOUT
        while time.monotonic() < deadline and self._process and self._process.poll() is None:
            try:
                with self._urlopen(self.url + "/health", timeout=2) as response:
                    if response.status == 200:
                        self._ready.set()
                        return
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(0.5)

    def ask(self, text, cancel):
        """Send one question and return the reply text."""
        self.warm_up()
        deadline = time.monotonic() + LOAD_TIMEOUT
        while not self._ready.wait(0.25):
            if cancel.is_set() or time.monotonic() > deadline:
                return ""
        # No conversation history. Every wake starts fresh, which keeps the
        # context tiny. Keeping the last few turns would go here.
        body = json.dumps({
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": text},
            ],
            "max_tokens": MAX_TOKENS,
        }).encode("utf-8")
        request = urllib.request.Request(
            self.url + "/v1/chat/completions", data=body,
            headers={"Content-Type": "application/json"},
        )
        with self._urlopen(request, timeout=30) as response:
            reply = json.load(response)
        return reply["choices"][0]["message"]["content"].strip()

    def unload(self):
        """Stop llama-server so a game gets the memory back."""
        with self._lock:
            process, self._process = self._process, None
            self._ready.clear()
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
