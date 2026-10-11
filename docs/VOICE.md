# Voice assistant (draft)

This is a draft and an example. It doesn't work yet, it isn't meant to merge
as-is, and it's off unless you go out of your way to turn it on. The idea is
the obvious one: say "hey Gabe", ask something, the Steam Machine answers out
loud and a little face on the JSAUX faceplate reacts.

I have something like this at home already, except mine pretends to be
MU/TH/UR from Alien and runs the house through Home Assistant. Wiring up the
audio is the easy bit. The trick is whether it does anything.

## Two versions

Both start the same way: a USB mic, openWakeWord listening for the wake word,
then record until you stop talking. Both stop listening and let go of
everything when a game starts.

Local (`"mode": "local"`) keeps it all on the machine. Parakeet turns the
recording into text, a small Qwen through llama.cpp writes an answer, Piper
reads it out. Nothing leaves the box, which is how GabeCubeAura works
everywhere else. The catch is that the models that fit in the GPU's 8 GB are
too weak to do anything good. Honestly, the local version is a parlour trick.

Cloud (`"mode": "cloud"`) sends the recording straight to a cloud model
that takes audio and answers with audio or text. No Parakeet, no Qwen. One
provider is written (OpenAI's audio chat completions) and Gemini, Grok and
Anthropic have notes on where they'd go in `voice/cloud.py`. It would be far
more useful. It also means your voice goes to a third party every time you
say the wake word, which is the opposite of the plugin's whole security
posture. So it's off, and it won't start without a key file. It costs money
per question too, and every answer waits on a round trip to the provider,
probably a couple of seconds before it starts talking. I haven't timed it.

## Memory on a stock machine

A stock Steam Machine has 16 GB of RAM. We think the GPU has its own 8 GB of
GDDR6, but I haven't confirmed that.

| Local piece | Default | Roughly |
| --- | --- | --- |
| Wake word | openWakeWord `hey_jarvis` | tiny |
| Speech to text | Parakeet TDT 0.6B v2, ONNX on the CPU | 1-2 GB |
| Answers | Qwen3 4B Instruct, Q4_K_M | 2.5 GB, on the GPU if it fits |
| Speech | Piper `en_US-lessac-medium` | 60-100 MB |

About 4 GB in all, which is fine at the Home screen and too much during a
game, so it unloads when one starts. Qwen3 1.7B (about 1.2 GB) is the light
option; a 32 GB machine fits Qwen3 8B. Cloud mode only keeps the wake word
loaded, plus Piper if the provider answers in text.

Even the small stuff is a problem, though. Parakeet on its own is around 2 GB,
and this is a machine built to run games that, if we're being honest, is
already a bit under-specced. Nothing on it expects a random 2 GB of memory
pressure to show up out of nowhere, never mind the extra the actual model
needs on top. Unloading for games helps, but it doesn't make that go away.

## Is it useful, though?

This is the real open question and I don't have a good answer. There aren't
any controls on the machine you'd want your voice for. Gaming knowledge is
the obvious pitch, and wiring a Wikipedia or walkthrough lookup into a voice
assistant is about the dumbest and worst way to get that information.

The Reddit video that started this may well be a basic text to speech fired
by a controller button, not AI at all. If that's what people actually want,
it's a much smaller feature than this.

## What would make it worth doing

Home Assistant. Hand the text (or the request) to HA's Assist and the Steam
Machine becomes a voice remote for the house: lights for movie night, the
thermostat, whatever you've got. That's what my MU/TH/UR setup does, and it's
the one use I actually have for this. `brain.py` notes
where it would go. It isn't built.

## How it's put together

Everything is in `py_modules/signalbar/voice/`. The models can't load inside
the plugin (Decky's loader bundles Python 3.11, SteamOS ships 3.13), so the
pipeline runs as its own process, `python -m signalbar.voice`, under a venv's
Python, as the logged-in user. `supervisor.py` is the plugin side: it starts
that process, passes game changes down and moods up as JSON lines, puts the
moods on the faceplate, and restarts the process with a backoff if it dies.
Its stderr goes to `voice.log` in the settings folder. `main.py` builds the
supervisor at start-up, stops it at unload and tells it when the game changes.

## Trying it

Everything goes under `/home/deck/voice`, since SteamOS replaces the
read-only root on updates.

Both versions:
1. Plug in a USB mic and make it the default input in Desktop Mode.
2. Make a venv with any Python (SteamOS's 3.13 is fine) and install
   `openwakeword numpy`, plus `onnx-asr[cpu]` for local mode. Run
   `openwakeword.utils.download_models()` once.
3. Create `voice.json` in `~/homebrew/settings/GabeCubeAura/` and restart
   Decky. `voice/config.py` lists every key with the reasoning.

Local, on top of that: the Vulkan Linux build of llama.cpp in
`/home/deck/voice/llama.cpp`, a Qwen3 4B Instruct Q4_K_M GGUF from Hugging
Face in `models/`, Piper and a voice from `rhasspy/piper-voices` in `piper/`,
and a local copy of `nemo-parakeet-tdt-0.6b-v2` for `stt_path`.

```json
{"enabled": true, "stt_path": "/home/deck/voice/models/parakeet-tdt-0.6b-v2"}
```

Cloud, on top of that: put your API key alone in `voice-key` next to
voice.json and `chmod 600` it, or it gets refused. The plugin reads it and
hands it to the voice process over stdin. It's never logged and never in
voice.json, so it can't end up in a settings export.

```json
{"enabled": true, "mode": "cloud"}
```

Mood GIFs are optional: `idle.gif`, `curious.gif`, `thinking.gif` and
`talking.gif` (64x54) in `/home/deck/voice/faces`.

## What's left

- Run any of it on a Steam Machine. All of it is written from each project's
  docs, and the OpenAI request shape needs checking against their current
  ones.
- Check the voice process starts as the logged-in user and can see the mic.
- Add a `show_gif(path)` call to the faceplate service (PR #4) so the face
  has something to call, and make the GIFs.
- Train a real "hey Gabe" model, and swap the volume-based end-of-speech check
  for Silero VAD.
- Kill llama-server if the voice process crashes (PR_SET_PDEATHSIG), and let a
  game starting cut speech off mid-sentence.
- Measure what the paused voice process still holds during a game.
- Decide whether any of this is worth it. See above.

I absolutely do not expect this to be merged. It doesn't even work in its
current form; this is just an example of how the pieces could go together.
