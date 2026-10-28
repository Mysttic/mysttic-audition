"""Paczka wydania: mysttic-audition-<wersja>-windows.zip i mysttic-audition-<wersja>-checksums.txt.

    python tools/pakiet.py [katalog_wyjściowy]   (domyślnie dist/)

W paczce są tylko pliki potrzebne do działania, w katalogu `mysttic-audition/`, bo tak
rozpakowuje ją aktualizacja w aplikacji (updates.extract_package). Plik sum ma format
sha256sum i obejmuje paczkę, zgodnie z kontraktem huba Mysttic/Mysttic.
"""
from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import updates  # noqa: E402

FILES = ["app.py", "updates.py", "mysttic-audition.pyw", "instaluj.bat", "requirements.txt",
         "VERSION.md", "CHANGELOG.md", "README.md", "README.pl.md"]
DIRS = ["static"]


def build(out_dir: Path, root: Path = ROOT) -> tuple[Path, Path]:
    version = updates.read_version(root / "VERSION.md")
    out_dir.mkdir(parents=True, exist_ok=True)
    package = out_dir / updates.package_name(version)
    paths = [root / name for name in FILES]
    paths += sorted(path for folder in DIRS for path in (root / folder).rglob("*") if path.is_file())
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, f"{updates.PROJECT}/{path.relative_to(root).as_posix()}")
    checksums = out_dir / updates.checksums_name(version)
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    checksums.write_text(f"{digest}  {package.name}\n", "utf-8", newline="\n")
    return package, checksums


if __name__ == "__main__":
    for path in build(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist"):
        print(f"{path} ({path.stat().st_size} B)")
