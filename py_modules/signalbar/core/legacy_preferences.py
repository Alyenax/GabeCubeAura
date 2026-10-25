"""Allowlisted legacy preferences retained for migration; no rendering or audio."""
import math
import re

REVISION = "gaben-export-v4-7"
AMPLITUDES = ("subtle", "natural", "expressive")


def bank_name(mount, mode, amplitude="natural"):
    return f"{mount}-{mode}" + (f"-{amplitude}" if amplitude != "natural" else "")
EXPRESSIONS = ("idle", "listening", "question", "thinking", "happy")
DEFAULTS = {"enabled": False, "microphone": "", "mount": "round", "eye_color": "#66c0f4",
            "character": "gabe", "companion_color": "#a879a8",
            "wake_enabled": False, "wake_all_assistants": False, "wake_sensitivity": "balanced", "wake_phrases": "ok",
            "glasses_color": "#b4a17b", "mouth_color": "#36d7dc", "face_revision": REVISION,
            "beard_shadow": True, "beard_shadow_strength": 60,
            "mouth_style": "slow-prism",
            "mouth_edge_color": "#6824ff", "mouth_width": 40,
            "emotional_amplitude": "natural",
            "wake_command_mode": "separate",
            "shortcut": "guide-a", "trigger_sound": True, "spoken_greeting": False,
            "confirm_game_close": True, "voice_volume": 100, "companion_volume": 70,
            "companion_response": "hybrid", "companion_speech_volume": 100,
            "companion_voice": "soft", "companion_motion": "lively", "companion_spoken_greeting": False,
            "companion_banter": True, "text_notifications": False,
            "companion_mouth_color": "#f2b6d0", "companion_mouth_edge_color": "#853f66",
            "duck_listening": True,
            "voice_interrupt": False,
            "voice_without_visuals": False,
            "output_volume_route": "auto",
            "language": "fr", "recognition_engine": "auto"}


def settings(value=None):
    value = value if isinstance(value, dict) else {}
    result = dict(DEFAULTS)
    result["enabled"] = value.get("enabled") is True
    result["wake_enabled"] = value.get("wake_enabled") is True
    result['wake_all_assistants']=value.get('wake_all_assistants')is True
    result["trigger_sound"] = value.get("trigger_sound", True) is True
    result["spoken_greeting"] = value.get("spoken_greeting") is True
    result['companion_spoken_greeting']=value.get('companion_spoken_greeting') is True
    result['companion_banter']=value.get('companion_banter',True) is True
    result['text_notifications']=value.get('text_notifications') is True
    result["confirm_game_close"] = value.get("confirm_game_close", True) is True
    result['duck_listening'] = value.get('duck_listening',True) is True
    result['voice_interrupt'] = value.get('voice_interrupt') is True
    result['voice_without_visuals'] = value.get('voice_without_visuals') is True
    music=value.get('companion_volume',70)
    if isinstance(music,(int,float)) and not isinstance(music,bool) and math.isfinite(music):
        result['companion_volume']=max(10,min(100,int(music)))
    speech=value.get('companion_speech_volume',100)
    if isinstance(speech,(int,float)) and not isinstance(speech,bool) and math.isfinite(speech):
        result['companion_speech_volume']=max(20,min(100,int(speech)))
    volume = value.get("voice_volume", 100)
    if isinstance(volume, (int, float)) and not isinstance(volume, bool) and math.isfinite(volume):
        result["voice_volume"] = max(20, min(150, int(volume)))
    width = value.get("mouth_width", DEFAULTS["mouth_width"])
    if isinstance(width, (int, float)) and not isinstance(width, bool) and math.isfinite(width):
        result["mouth_width"] = max(25, min(100, int(width)))
    result["beard_shadow"] = value.get("beard_shadow", DEFAULTS["beard_shadow"]) is True
    shadow = value.get("beard_shadow_strength", DEFAULTS["beard_shadow_strength"])
    if isinstance(shadow, (int, float)) and not isinstance(shadow, bool) and math.isfinite(shadow):
        result["beard_shadow_strength"] = max(45, min(75, int(shadow)))
    for key, choices in (("language", ("fr", "en")),
                         ("character", ("gabe", "companion", "glados", "eyes")),
                         ("companion_response", ("hybrid", "musical")),
                         ("companion_motion", ("calm", "lively")),
                         ("wake_sensitivity", ("strict", "balanced", "sensitive", "very-sensitive")),
                         ("wake_phrases", ("ok", "hey", "both")),
                         ("wake_command_mode", ("separate", "continuous")),
                         ("mouth_style", ("slow-prism", "single-colour")),
                         ("emotional_amplitude", AMPLITUDES),
                         ("recognition_engine", ("auto", "cpu")),
                         ("output_volume_route", ("auto", "cec", "pipewire")),
                         ("shortcut", ("guide-a", "guide-x", "guide-y", "lb-rb", "disabled")),
                         ("mount", ("optique", "rectangular", "round"))):
        if value.get(key) in choices:
            result[key] = value[key]
    for key in ("eye_color", "glasses_color", "mouth_color", "mouth_edge_color", "companion_color", "companion_mouth_color", "companion_mouth_edge_color"):
        if isinstance(value.get(key), str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value[key]):
            result[key] = value[key].lower()
    for key in ("microphone",):
        candidate = value.get(key, "")
        if isinstance(candidate, str) and re.fullmatch(r"[\w./:-]{0,160}", candidate):
            result[key] = candidate
    # Allowlist migration: obsolete cloud fields never enter runtime or exports.
    # Migrate only the previous factory pink, never a chosen custom colour.
    if result['companion_color']=='#ec81a5' and value.get('face_revision') in (None,REVISION,'companion-fluid-v1','companion-fluid-v2'):
        result['companion_color']=DEFAULTS['companion_color']
    if result['character']=='companion':
        companion_revision = 'companion-living-turn-v2'
        result['face_revision']=companion_revision
    if result['character']=='glados':
        glados_revision = 'glados-native-micro-v2'
        result['face_revision']=glados_revision
    if result['character']=='eyes':
        eyes_revision = 'playful-eyes-native-v1'
        result['face_revision']=eyes_revision
    # Legacy saved selectors cannot assign another character's voice.
    result['companion_voice']='robotic' if result['character']=='glados' else 'soft'
    if result['character'] in ('glados','eyes'):result['companion_response']='hybrid'
    return result

