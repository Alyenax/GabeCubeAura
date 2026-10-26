# Notice when GabeCubeAura has its own faceplate support, so this plugin can step aside.
"""GabeCubeAura took over this plugin's job. Its faceplate code lives in
py_modules/signalbar/faceplate, so finding that package in an installed,
enabled plugin means the panel is GabeCubeAura's to drive and this plugin
should leave it alone and ask to be uninstalled. A GabeCubeAura with faceplate
code of its own says so with a claim file instead (see claimant).
"""

import json
import os

MARKER = os.path.join("py_modules", "signalbar", "faceplate", "__init__.py")
# A GabeCubeAura that ships this (1.5.0 does) claims the panel only while its faceplate is
# switched on, so for it the claim is the whole answer. Shipping the package isn't enough:
# with its faceplate off nobody would drive the panel.
CLAIMS = os.path.join("py_modules", "signalbar", "faceplate_claim.py")


def _disabled(plugins_dir):
    """Plugin names switched off in Decky's settings (homebrew/settings/loader.json)."""
    path = os.path.join(os.path.dirname(plugins_dir), "settings", "loader.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            names = json.load(handle).get("disabled_plugins") or []
    except (OSError, ValueError, AttributeError):
        return set()
    return {str(name) for name in names}


CLAIM = "faceplate-claim.json"


def _alive(pid, proc_root="/proc"):
    """True if pid runs a Decky plugin backend (guards against a reused pid)."""
    try:
        with open(os.path.join(proc_root, str(int(pid)), "cmdline"), "rb") as handle:
            return b"/plugins/" in handle.read()
    except (OSError, TypeError, ValueError):
        return False


def claimant(settings_root, proc_root="/proc"):
    """Name from a live faceplate-claim.json in any plugin's settings folder, or "".

    A plugin writes {"plugin": name, "pid": pid} there while it drives the
    faceplate itself (GabeCubeAura's faceplate_claim.py). A file left behind
    by a crash names a dead process and is ignored.
    """
    try:
        folders = sorted(os.listdir(settings_root))
    except OSError:
        return ""
    for folder in folders:
        try:
            with open(os.path.join(settings_root, folder, CLAIM), "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and _alive(data.get("pid"), proc_root):
            return str(data.get("plugin") or folder)
    return ""


def faceplate_owner(plugins_dir, proc_root="/proc"):
    """Name of an enabled plugin with built-in faceplate support (GabeCubeAura), or "".

    Either signal counts: it holds a live claim, or it ships signalbar/faceplate
    without the claim code (an older build that can't tell us when it's off).
    """
    owner = claimant(os.path.join(os.path.dirname(plugins_dir), "settings"), proc_root)
    if owner:
        return owner
    try:
        folders = sorted(os.listdir(plugins_dir))
    except OSError:
        return ""
    disabled = None
    for folder in folders:
        root = os.path.join(plugins_dir, folder)
        if not os.path.isfile(os.path.join(root, MARKER)) or os.path.isfile(os.path.join(root, CLAIMS)):
            continue
        try:
            with open(os.path.join(root, "plugin.json"), "r", encoding="utf-8") as handle:
                name = str(json.load(handle).get("name") or folder)
        except (OSError, ValueError, AttributeError):
            name = folder
        if disabled is None:
            disabled = _disabled(plugins_dir)
        if name not in disabled:
            return name
    return ""
