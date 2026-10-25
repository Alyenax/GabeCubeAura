"""Check GPL code / separately licensed artwork and keep publication fail-closed."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
POLICY = "SEE LICENSE IN LICENSING.md"
GPL = "GPL-3.0-only"
ART = "CC-BY-NC-SA-4.0"
GPL_TEXT_SHA256 = "fb981668c18a279e285fc4d83fba1e836cc84dd4daa73c9697d3cfd2d8aca6e0"
CC_TEXT_SHA256 = "e66c269d4819aaab34b49ef5220c4ddab6756f21bb5180761a4eb8561f2b7bbd"
GRAPHICS = {".png", ".gif", ".rgb", ".rgbz", ".svg", ".webp"}
REQUIRED = {
    "LICENSE", "LICENSING.md", "THIRD_PARTY_NOTICES.md",
    "licenses/faceplate-scope.json", "licenses/faceplate-assets.json",
    "licenses/CC-BY-NC-SA-4.0.txt", "licenses/Faceplate-Artwork-NOTICE.md",
    "licenses/BSD-3-Clause-previous.txt", "licenses/Pixel-Faceplate-BSD-3-Clause.txt",
    "licenses/Decky-UI-LGPL-2.1.txt", "licenses/React-Icons-LICENSE.txt",
    "licenses/Tabler-Icons-MIT.txt", "licenses/third-party-files.json",
    "licenses/decky-api-1.1.3/LICENSE", "licenses/decky-api-1.1.3/package.json",
    "licenses/decky-api-1.1.3/src/index.ts", "licenses/decky-api-1.1.3/src/types.ts",
    "licenses/decky-api-1.1.3/src/types.d.ts", "licenses/decky-api-1.1.3/dist/index.js",
}


def _file(root: Path, relative: str) -> Path:
    parts = PurePosixPath(relative)
    if parts.is_absolute() or ".." in parts.parts or "\\" in relative:
        raise ValueError(f"Unsafe licence inventory path: {relative}")
    path = root / relative
    if any((root / Path(*parts.parts[:i])).is_symlink()
           for i in range(1, len(parts.parts) + 1)) or not path.is_file():
        raise ValueError(f"Missing/unsafe licence inventory file: {relative}")
    return path


def _hash(root: Path, relative: str) -> str:
    return hashlib.sha256(_file(root, relative).read_bytes()).hexdigest()


def check_license_scope(root: Path, staged: Path | None = None, *, public_build: bool = False) -> None:
    root = Path(root)
    data = json.loads(_file(root, "licenses/faceplate-scope.json").read_text())
    pkg = json.loads(_file(root, "package.json").read_text())
    if pkg.get("license") != POLICY:
        raise ValueError("Mixed-license package must point to LICENSING.md")
    if data.get("schema") != 2 or any(data.get(key) != GPL for key in (
        "future_default_license", "faceplate_code_license", "frontend_and_studio_code_license",
    )):
        raise ValueError("GCA code, including Faceplate and UI, must remain GPL-3.0-only")
    if data.get("faceplate_asset_license") != ART or data.get("asset_manifest") != "licenses/faceplate-assets.json":
        raise ValueError("Separate Faceplate artwork scope must use CC-BY-NC-SA-4.0")
    history = data.get("release_history", {})
    if (history.get("last_public_software_release") != "v1.4.0"
            or history.get("later_development_visibility") != "private"
            or history.get("private_lab_220_publicly_distributed") is not False):
        raise ValueError("Reviewed history: v1.4.0 was public; Labs including Lab 220 stayed private")
    if history.get("infer_grants_from_private_license_file") is not False:
        raise ValueError("Do not infer a third-party grant from private licence metadata")
    if public_build and data.get("publish_clearance") != "CLEARED":
        raise ValueError("Public release blocked: final artifact and third-party rights review remain pending")
    for relative, expected in (("LICENSE", GPL_TEXT_SHA256),
                               ("licenses/CC-BY-NC-SA-4.0.txt", CC_TEXT_SHA256)):
        if _hash(root, relative) != expected:
            raise ValueError(f"Official licence text changed: {relative}")
    for relative in REQUIRED:
        _file(root, relative)
    licensing = _file(root, "LICENSING.md").read_text()
    if data["notice"] not in licensing or GPL not in licensing or ART not in licensing:
        raise ValueError("Missing code/artwork scope notice")

    located = {p.relative_to(root).as_posix()
               for directory in ("py_modules/signalbar/faceplate", "py_modules/signalbar/jsaux_broker")
               for p in (root / directory).glob("*.py")}
    gpl, bsd = set(data["gpl_source_paths"]), set(data["inherited_bsd"])
    if gpl & bsd or located != gpl | bsd:
        raise ValueError("Overlapping or unclassified Faceplate Python code")
    if not set(data["shared_provenance_review"]) <= gpl | bsd:
        raise ValueError("Shared provenance review must identify classified code")
    for relative in gpl | bsd | set(data["frontend_and_studio_source_paths"]):
        code = _file(root, relative).read_text()
        if "SPDX-License-Identifier: PolyForm" in code or "SPDX-License-Identifier: CC-BY-NC" in code:
            raise ValueError(f"Noncommercial licence incorrectly applied to code: {relative}")
        if relative in bsd and ("hodapp/pixel-faceplate" not in code or "BSD-3-Clause" not in code):
            raise ValueError(f"Legacy BSD attribution lost from {relative}")

    runtime = json.loads(_file(root, "scripts/runtime-files.json").read_text())
    if len(runtime) != len(set(runtime)):
        raise ValueError("Duplicate runtime inventory path")
    if "licenses/PolyForm-Noncommercial-1.0.0.md" in runtime:
        raise ValueError("Superseded PolyForm policy cannot be bundled")
    if any(p.startswith("assets/faceplate/calibrated-home/") for p in runtime):
        raise ValueError("Third-party Stray starter must not be bundled")
    declared = json.loads(_file(root, data["asset_manifest"]).read_text())
    if declared.get("license") != ART:
        raise ValueError("Artwork manifest licence mismatch")
    files = declared.get("files", [])
    paths = [entry["path"] for entry in files]
    expected_graphics = {p for p in runtime if p.startswith("assets/faceplate/") and Path(p).suffix in GRAPHICS}
    if len(paths) != len(set(paths)) or set(paths) != expected_graphics:
        raise ValueError("Unclassified or duplicate bundled Faceplate artwork")
    technical = {p for p in runtime if p.startswith("assets/faceplate/")} - expected_graphics
    if set(declared.get("technical_metadata_excluded", [])) != technical:
        raise ValueError("Technical metadata must stay outside the artwork grant")
    for entry in files:
        relative = entry["path"]
        if entry.get("license") != ART or not entry.get("creator") or not entry.get("attribution"):
            raise ValueError(f"Missing artwork attribution or licence: {relative}")
        if _hash(root, relative) != entry.get("sha256"):
            raise ValueError(f"Artwork bytes changed without rights inventory review: {relative}")
        if _hash(root, entry["source"]) != entry.get("source_sha256"):
            raise ValueError(f"Artwork provenance changed without inventory review: {relative}")
    third_party = json.loads(_file(root, "licenses/third-party-files.json").read_text())
    for entry in third_party["files"]:
        if _hash(root, entry["path"]) != entry["sha256"]:
            raise ValueError(f"Third-party notice/source changed: {entry['path']}")
    required = REQUIRED | {p for p in runtime if p.startswith("licenses/")}
    if not required <= set(runtime):
        raise ValueError("Runtime omits required licensing files")
    if staged is not None:
        staged = Path(staged)
        for relative in required:
            if _file(staged, relative).read_bytes() != _file(root, relative).read_bytes():
                raise ValueError(f"Bundled licensing material differs from source: {relative}")
        for relative in gpl | bsd | expected_graphics | technical:
            if _hash(staged, relative) != _hash(root, relative):
                raise ValueError(f"Bundled code/artwork differs from reviewed source: {relative}")


if __name__ == "__main__":
    check_license_scope(ROOT, public_build=True)
    print("GPL code / CC artwork inventory and publication review: OK.")
