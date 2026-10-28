"""Mysttic Audition: start dwuklikiem.

Uruchamia aplikację ze środowiska .venv, bez okna konsoli. Przedtem:
- instaluje aktualizację przygotowaną przez aplikację w data/update (tylko gdy aplikacja nie działa);
- gdy środowiska brakuje albo zmienił się requirements.txt, uruchamia instaluj.bat w widocznym oknie.

Z argumentem `--czekaj <pid>` (tak uruchamia go aplikacja po „Uruchom ponownie”) najpierw czeka
na koniec wskazanego procesu. Launcher korzysta tylko z biblioteki standardowej.
"""
import ctypes
import hashlib
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHONW = ROOT / ".venv" / "Scripts" / "pythonw.exe"
MARKER = ROOT / ".venv" / "zainstalowano.txt"  # skrót requirements.txt z ostatniej udanej instalacji
STAGING = ROOT / "data" / "update"
INSTANCE = ROOT / "data" / "instance.json"
TITLE = "Mysttic Audition"


def version_of(text: str) -> tuple[int, ...]:
    match = re.search(r"^(\d+)\.(\d+)\.(\d+)$", text, re.M)
    return tuple(int(part) for part in match.groups()) if match else (0, 0, 0)


def wait_for_exit(pid: int) -> None:
    handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if handle:
        ctypes.windll.kernel32.WaitForSingleObject(handle, 30_000)
        ctypes.windll.kernel32.CloseHandle(handle)


def app_running() -> bool:
    try:
        port = json.loads(INSTANCE.read_text("utf-8"))["port"]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/version", timeout=1) as response:
            return response.status == 200
    except (OSError, ValueError, KeyError, TypeError):
        return False


def install_update() -> None:
    """Kopiuje pliki przygotowanej, nowszej wersji na miejsce obecnych. Dane, modele i .venv zostają."""
    files = STAGING / "pliki"
    try:
        staged = json.loads((STAGING / "gotowe.json").read_text("utf-8"))["version"]
    except (OSError, ValueError, KeyError, TypeError):
        return
    current = (ROOT / "VERSION.md").read_text("utf-8") if (ROOT / "VERSION.md").exists() else ""
    if not files.is_dir() or version_of(staged) <= version_of(current):
        shutil.rmtree(STAGING, ignore_errors=True)
        return
    try:
        for source in files.rglob("*"):
            if source.is_file():
                target = ROOT / source.relative_to(files)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        shutil.rmtree(STAGING)
    except OSError as exc:
        ctypes.windll.user32.MessageBoxW(
            None, f"Nie udało się zainstalować aktualizacji {staged}:\n{exc}\n\n"
                  "Spróbuję ponownie przy następnym uruchomieniu.", TITLE, 0x30)


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--czekaj":
        wait_for_exit(int(sys.argv[2]))
    if not app_running():
        install_update()
    # bez \r, żeby zamiana końcówek linii przez gita nie wymuszała ponownej instalacji
    wanted = hashlib.sha256((ROOT / "requirements.txt").read_bytes().replace(b"\r\n", b"\n")).hexdigest()

    def installed() -> bool:
        return PYTHONW.exists() and MARKER.exists() and MARKER.read_text("ascii").strip() == wanted

    if not installed():
        setup = subprocess.run(["cmd", "/c", str(ROOT / "instaluj.bat")], cwd=ROOT,
                               creationflags=subprocess.CREATE_NEW_CONSOLE)
        if setup.returncode == 0:
            MARKER.write_text(wanted, "ascii")
    if installed():
        subprocess.Popen([str(PYTHONW), str(ROOT / "app.py")], cwd=ROOT)


if __name__ == "__main__":
    main()
