# Voice assistant (scaffold)

Say "hey Gabe", ask a question, and the Steam Machine answers out loud while a
little face on the JSAUX faceplate reacts. That's the idea. What's here is the
frame for it. Every piece is written and plugged together, but none of it has
run on a Steam Machine yet, and it stays off until you turn it on by hand.

I have something like this at home already, except mine pretends to be
MU/TH/UR from Alien and runs the house through Home Assistant. Getting the
audio pipeline working is the easy bit. The trick is whether it does anything
useful once it can hear you.

## How it fits together

Everything lives in `py_modules/signalbar/voice/`, one small file per step:

```
USB mic (pw-record, 16 kHz mono)          mic.py
  -> openWakeWord hears "hey Gabe"        wake.py
  -> curious face, start loading Qwen     face.py, brain.py
  -> record until you stop talking
  -> Parakeet turns it into text          listen.py
  -> Qwen writes a short answer           brain.py
  -> Piper says it, talking face          speak.py
  -> back to listening
```

`assistant.py` is the loop that runs those in order on one background thread.
When a game starts it cancels whatever it's doing, lets go of the mic so it
isn't fighting voice chat, and unloads the models. When the game ends it goes
back to listening and reloads the models the next time someone talks to it.

None of that runs inside the plugin. Decky's loader is a frozen binary with
Python 3.11 built in, SteamOS ships Python 3.13, and numpy or onnxruntime
built for one won't import into the other. So the pipeline runs as its own
process, `python -m signalbar.voice`, under a venv's Python, started as the
logged-in user.

The plugin side is `supervisor.py`, which only uses the standard library. It
starts that process, sends it `{"game": true}` or `{"game": false}` as JSON
lines on stdin, and reads lines like `{"state": "curious", "mood": "curious"}`
back from stdout. Moods go to the faceplate, which lives in the plugin. If
the voice process dies, the supervisor logs a line and starts it again after
5 s, doubling up to 5 minutes. Its stderr goes to `voice.log` in the
settings folder.

`main.py` builds the supervisor at start-up, stops it at unload and tells it
when the game changes. If voice.json is missing or the venv's Python isn't
there, nothing starts. If the voice process finds a piece missing, it says
so, the plugin logs one line, and it isn't started again. Nothing else in the
plugin changes.

## Memory

The defaults are sized for a stock Steam Machine with 16 GB of RAM, not for
one with extra RAM fitted.

| Piece | Default | Roughly |
| --- | --- | --- |
| Wake word | openWakeWord `hey_jarvis` | tiny |
| Speech to text | Parakeet TDT 0.6B v2, ONNX on the CPU | 1-2 GB |
| Answers | Qwen3 4B Instruct, Q4_K_M GGUF | 2.5 GB |
| Speech | Piper `en_US-lessac-medium` | 60-100 MB |

About 4 GB with everything loaded, next to SteamOS and Steam's UI. That's
fine at the Home screen and too much to keep during a game, so everything
unloads when one starts. We think the GPU has its own 8 GB of GDDR6. If so,
llama-server's Vulkan build puts the Qwen weights there and system RAM only
carries the rest. I haven't confirmed that, so measure before relying on it.

If 4B is slow or too big, Qwen3 1.7B at Q4_K_M is about 1.2 GB. With 32 GB of
RAM, Qwen3 8B fits. Changing the model means pointing `llm_model` at a
different GGUF. I went with 4B as the default because it's the smallest Qwen
I'd trust with tool calls, which is what Home Assistant commands need.

## Trying it

SteamOS replaces its read-only root on every update, so all of this goes
under `/home/deck/voice` and nothing touches the system.

1. Plug in a USB mic and make it the default input in Desktop Mode.
2. Make a venv and install the Python bits:
   `python -m venv /home/deck/voice/venv`, then
   `/home/deck/voice/venv/bin/pip install openwakeword onnx-asr[cpu] numpy`.
   Any Python works, since the voice process runs under the venv's own and
   never inside Decky. SteamOS's 3.13 is the obvious pick. If it won't make a
   venv, a standalone Python in /home (uv can fetch one) does the same job.
3. Run `openwakeword.utils.download_models()` once from the venv to fetch the
   stock wake word models.
4. Grab the Vulkan Linux build of llama.cpp from its GitHub releases and
   unpack it to `/home/deck/voice/llama.cpp`. Download a Qwen3 4B Instruct
   Q4_K_M GGUF from Hugging Face (unsloth's `Qwen3-4B-Instruct-2507-GGUF`
   has one) into `/home/deck/voice/models`.
5. Get Piper's Linux build into `/home/deck/voice/piper`, plus a voice from
   `rhasspy/piper-voices` on Hugging Face (the `.onnx` and its `.onnx.json`).
6. Download `nemo-parakeet-tdt-0.6b-v2` for onnx-asr somewhere local and set
   `stt_path` to it, so nothing downloads at runtime. Use v3 if you want
   languages other than English.
7. Optional: put `idle.gif`, `curious.gif`, `thinking.gif` and `talking.gif`
   (64x54) in `/home/deck/voice/faces` for the faceplate.
8. Create `voice.json` in the plugin's settings folder
   (`~/homebrew/settings/GabeCubeAura/`) and restart Decky:

```json
{
  "enabled": true,
  "python": "/home/deck/voice/venv/bin/python",
  "stt_path": "/home/deck/voice/models/parakeet-tdt-0.6b-v2"
}
```

The full list of keys, with the reasoning next to each one, is in
`voice/config.py`. The plugin starts and stops llama-server itself, because
stopping the process is how a game gets the memory back. You could run it as
a systemd user service instead, but then it never unloads.

## Home Assistant

The obvious place for a Home Assistant hand-off is `brain.py`: send the text
to HA's Assist conversation API, either instead of Qwen or before it, and let
HA run the lights and whatever else. That's how my MU/TH/UR setup works. It
isn't built here.

## What's left

- Run any of it on a Steam Machine. Everything above is written against each
  project's docs.
- Check the voice process really starts as the logged-in user through
  runuser, and that it can see the mic from there.
- If the voice process crashes, llama-server can be left running. Setting
  PR_SET_PDEATHSIG on it would tie the two together.
- See how much memory the paused voice process still holds during a game. If
  it's more than expected, stop the process on game start instead of pausing
  it.
- Add a `show_gif(path)` call to the faceplate service (PR #4) so `face.py`
  has something to call. Until then the face does nothing.
- Make the mood GIFs and train a real "hey Gabe" model.
- Replace the volume-based end-of-speech check with Silero VAD.
- Stream Qwen's answer into Piper a sentence at a time, and let a game start
  cut speech off mid-sentence.
- A settings toggle and a status line, once it can actually answer things.
