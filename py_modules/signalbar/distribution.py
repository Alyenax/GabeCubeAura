"""Build capabilities, independent of the selected update channel."""

import re


def supports_private_tools(version: str) -> bool:
    return bool(re.fullmatch(r"(?:v)?\d+\.\d+\.\d+-(?:lab|test)\.\d+", str(version)))


def require_private_tools(version: str):
    if not supports_private_tools(version):
        raise RuntimeError("Private testing tools are unavailable in this build. Export a local diagnostic instead.")


def speech_release_client(update_manager):
    # Public packs are not published yet. Never send a public user to private
    # authorization, or treat a changed update channel as installation consent.
    if not supports_private_tools(update_manager.installed_version):
        raise RuntimeError("The public speech module is not available yet. Installed modules remain usable.")
    return update_manager._release_client("private")
