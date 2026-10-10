"""Cloud mode: send what you said straight to a cloud model and play its answer.

Read this first. This mode sends a recording of your voice to a third party.
That's the opposite of GabeCubeAura's rule that everything stays on the
machine, which is why it's off, why it needs mode "cloud" in voice.json, and
why it won't even start unless a key file exists next to voice.json. Nobody
should end up here by accident.

The reason it's here at all: a model that fits in the GPU's 8 GB is a parlour
trick next to the big cloud ones. If this is ever going to be useful, the
cloud version is the one that would be.

It's the smallest thing that works: openWakeWord, record until quiet, post the
clip, play what comes back. No Parakeet, no Qwen, no llama-server. A provider
is one class with answer(wav_bytes), returning WAV bytes to play or text for
Piper to read.

Other providers would slot in as one more class each. I'm going from memory
on these, so check before building any of them:
- Gemini's generateContent takes audio as an inline part and answers in text,
  which would go through Piper. Spoken replies are its Live API, which is a
  streaming connection and a bigger job than one urllib call.
- Grok (xAI): last I looked its voice side was a realtime streaming API too.
  Its plain text API would need speech to text in front, same as Anthropic.
- Anthropic: as far as I know the API doesn't take audio, so it needs speech
  to text first (listen.py locally, or a cloud transcription call) and then
  sends text, with the reply going through Piper.

The key is read from voice-key in the settings folder by the plugin and handed
to the voice process over stdin. It's never logged, never in a setting that
gets exported, and only ever sent to the provider's own URL.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request


class OpenAIAudio:
    """OpenAI chat completions with audio in and audio out.

    Written from OpenAI's public docs for audio-capable chat completions.
    Check the request shape and the model name against their current docs
    before trusting it, because this part of their API has changed before.
    """

    URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self, key, model="gpt-4o-mini-audio-preview", voice="alloy",
                 system_prompt="", urlopen=urllib.request.urlopen):
        self._key = key
        self.model = model
        self.voice = voice
        self.system_prompt = system_prompt
        self._urlopen = urlopen

    def answer(self, wav):
        body = json.dumps({
            "model": self.model,
            "modalities": ["text", "audio"],
            "audio": {"voice": self.voice, "format": "wav"},
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": [{
                    "type": "input_audio",
                    "input_audio": {"data": base64.b64encode(wav).decode("ascii"), "format": "wav"},
                }]},
            ],
        }).encode("utf-8")
        request = urllib.request.Request(self.URL, data=body, headers={
            "Authorization": "Bearer " + self._key,
            "Content-Type": "application/json",
        })
        # The error text can echo the request, so only the status code gets out.
        try:
            with self._urlopen(request, timeout=30) as response:
                message = json.load(response)["choices"][0]["message"]
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"OpenAI answered {error.code}") from None
        audio = message.get("audio") or {}
        if audio.get("data"):
            return base64.b64decode(audio["data"])
        return str(message.get("content") or audio.get("transcript") or "").strip()


PROVIDERS = {"openai": OpenAIAudio}


def provider(values, key):
    kind = PROVIDERS.get(str(values["cloud_provider"]))
    if kind is None:
        raise ValueError(f"unknown cloud_provider {values['cloud_provider']!r}")
    return kind(key, values["cloud_model"], values["cloud_voice"], values["llm_system_prompt"])
