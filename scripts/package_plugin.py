"""Create the installable Decky ZIP with a single GabeCubeAura/ root."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import shutil
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
OUTPUT = ROOT / "out" / f"GabeCubeAura-v{PACKAGE['version']}.zip"
FIXED_OUTPUT = ROOT / "out" / "GabeCubeAura.zip"
CHECKSUMS = ROOT / "out" / "SHA256SUMS"
FILES = [
    "main.py",
    "plugin.json",
    "package.json",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "licenses/Material-Symbols-Apache-2.0.txt",
    "licenses/Phosphor-Icons-MIT.txt",
    "dist/index.js",
]


def iter_files(*, require_build=True):
    for relative in FILES:
        if not require_build and relative == "dist/index.js":
            continue
        path = ROOT / relative
        if not path.is_file():
            raise SystemExit(f"required release file is missing: {relative}")
        yield path
    for path in sorted((ROOT / "py_modules" / "signalbar").rglob("*.py")):
        yield path


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(OUTPUT, "w", ZIP_DEFLATED) as archive:
        for path in iter_files():
            relative = path.relative_to(ROOT)
            archive.write(path, Path("GabeCubeAura") / relative)
    if OUTPUT.stat().st_size > 5 * 1024 * 1024:
        raise SystemExit("runtime archive exceeds the 5 MiB updater limit")
    shutil.copy2(OUTPUT, FIXED_OUTPUT)
    digest = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    CHECKSUMS.write_text(
        f"{digest}  {OUTPUT.name}\n{digest}  {FIXED_OUTPUT.name}\n",
        encoding="utf-8",
    )
    print(OUTPUT)


if __name__ == "__main__":
    main()
