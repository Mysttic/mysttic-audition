"""Aktualizacje Mysttic Audition z publicznego huba wydań Mysttic/Mysttic.

Kontrakt huba (RELEASES.md w repozytorium Mysttic/Mysttic) w skrócie:
- w hubie leżą wydania wszystkich projektów, więc liczą się tylko tagi złożone z przedrostka
  `mysttic-audition-v` i samego numeru X.Y.Z, a spośród nich najwyższy numer, nie pierwszy z listy;
- paczka i plik sum muszą mieć stan `uploaded`, inaczej wydanie jeszcze się wgrywa
  i po cichu nie ma aktualizacji;
- pliki pobieramy tylko spod github.com/Mysttic/Mysttic/releases/download/<tag>/,
  a przekierowania przyjmujemy tylko po HTTPS do hostów GitHuba;
- pytamy najwyżej raz na dobę, bez tokenu i bez danych o komputerze; błąd kończy się
  wpisem w dzienniku, a aplikacja działa dalej.

Pobraną paczkę sprawdzamy (rozmiar, SHA-256 z pliku sum, numer wersji w środku) i rozpakowujemy
do data/update/pliki. Pliki programu podmienia launcher (mysttic-audition.pyw) przy następnym
starcie, kiedy aplikacja nie działa.

Moduł korzysta tylko z biblioteki standardowej, żeby testy działały bez .venv.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

PROJECT = "mysttic-audition"
NAME = "Mysttic Audition"
HUB = "Mysttic/Mysttic"
TAG_PREFIX = f"{PROJECT}-v"
RELEASES_API = f"https://api.github.com/repos/{HUB}/releases?per_page=100"
DOWNLOAD_PREFIX = f"https://github.com/{HUB}/releases/download/"
SITE = f"https://mysttic.github.io/Mysttic/{PROJECT}/"
DOWNLOAD_HOSTS = {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
TIMEOUT = 10  # sekundy; sprawdzanie aktualizacji to czynność poboczna, lepiej odpuścić niż wisieć
MAX_PACKAGE_BYTES = 100 * 1024 * 1024  # paczka to kod i interfejs, kilka MB; większa to coś obcego
CHECK_INTERVAL = 24 * 3600
FIRST_CHECK_DELAY = 20  # sekundy po starcie, żeby nie konkurować z uruchamianiem
RETRY_INTERVAL = 3600
KEEP = {".venv", "models", "data", ".webview", ".git"}  # katalogi lokalne, których paczka nie może dotknąć
VERSION_RE = re.compile(r"\d+\.\d+\.\d+")
TAG_RE = re.compile(re.escape(TAG_PREFIX) + r"(\d+\.\d+\.\d+)")


class UpdateError(Exception):
    """Błąd z komunikatem, który można pokazać użytkownikowi."""


def read_version(path: Path) -> str:
    """Pierwsza linia pliku złożona z samego numeru X.Y.Z (format VERSION.md)."""
    try:
        for line in path.read_text("utf-8").splitlines():
            if VERSION_RE.fullmatch(line.strip()):
                return line.strip()
    except OSError:
        pass
    return "0.0.0"


def parse_version(text: str) -> tuple[int, ...]:
    """Numer X.Y.Z (już sprawdzony wyrażeniem VERSION_RE) jako krotka do porównań."""
    return tuple(int(part) for part in text.split("."))


def package_name(version: str) -> str:
    return f"{PROJECT}-{version}-windows.zip"


def checksums_name(version: str) -> str:
    return f"{PROJECT}-{version}-checksums.txt"


def pick_release(releases: object, current: str) -> dict | None:
    """Najwyższe wydanie tego projektu, nowsze od bieżącego i z kompletem plików; inaczej None."""
    best = None
    for release in releases if isinstance(releases, list) else []:
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
            continue
        match = TAG_RE.fullmatch(str(release.get("tag_name", "")))
        if match and (best is None or parse_version(match.group(1)) > parse_version(best[0])):
            best = (match.group(1), release)
    if best is None or parse_version(best[0]) <= parse_version(current):
        return None
    version, release = best
    tag = release["tag_name"]
    assets = {a.get("name"): a for a in release.get("assets") or [] if isinstance(a, dict)}
    files = {}
    for key, name in (("package", package_name(version)), ("checksums", checksums_name(version))):
        asset = assets.get(name)
        url = f"{DOWNLOAD_PREFIX}{tag}/{name}"
        if not asset or asset.get("state") != "uploaded" or asset.get("browser_download_url") != url:
            return None  # pliki jeszcze się wgrywają albo adres wygląda obco: na razie bez aktualizacji
        files[key] = {"name": name, "url": url, "size": asset.get("size")}
    return {"version": version, "tag": tag, "published": release.get("published_at"),
            "notes": (release.get("body") or "").strip(), **files}


def parse_checksums(text: str) -> dict[str, str]:
    """Plik w formacie sha256sum: `<64 znaki hex>  <nazwa pliku>` w każdej linii."""
    sums = {}
    for line in text.splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{64}) [ *](.+)", line.strip())
        if match:
            sums[match.group(2).strip()] = match.group(1).lower()
    return sums


def changelog_section(text: str, version: str) -> str:
    """Treść sekcji `## [X.Y.Z]` z CHANGELOG.md, bez nagłówka."""
    pattern = rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|^\[[^\]\n]+\]: |\Z)"
    match = re.search(pattern, text, re.S | re.M)
    return match.group(1).strip() if match else ""


def check_download_url(url: str) -> None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in DOWNLOAD_HOSTS:
        raise UpdateError(f"Odmowa pobierania spoza GitHuba ({parts.scheme}://{parts.hostname}).")


class _GitHubRedirects(urllib.request.HTTPRedirectHandler):
    """Przekierowania tylko po HTTPS i tylko do hostów GitHuba."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_download_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_download_opener = urllib.request.build_opener(_GitHubRedirects)


def fetch_releases(user_agent: str) -> object:
    request = urllib.request.Request(RELEASES_API, headers={
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": user_agent,
    })
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.load(response)


def download(url: str, target: Path, user_agent: str, expected_size: int | None = None, progress=None) -> str:
    """Pobiera plik i zwraca jego SHA-256. Przerwane pobranie nie zostawia pliku docelowego."""
    if not url.startswith(DOWNLOAD_PREFIX):
        raise UpdateError(f"Adres pliku nie prowadzi do wydań {HUB}.")
    check_download_url(url)
    part = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    received = 0
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/octet-stream"})
    try:
        with _download_opener.open(request, timeout=TIMEOUT) as response, open(part, "wb") as out:
            check_download_url(response.geturl())
            while chunk := response.read(256 * 1024):
                received += len(chunk)
                if received > MAX_PACKAGE_BYTES:
                    raise UpdateError("Plik jest większy, niż może być paczka aplikacji.")
                digest.update(chunk)
                out.write(chunk)
                if progress:
                    progress(received, expected_size)
        if expected_size is not None and received != expected_size:
            raise UpdateError(f"Pobrano {received} z {expected_size} bajtów.")
        part.replace(target)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return digest.hexdigest()


def extract_package(package: Path, target: Path, version: str) -> None:
    """Rozpakowuje paczkę do `target`. Ścieżka spoza `mysttic-audition/`, z `..` albo do danych przerywa całość."""
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    with zipfile.ZipFile(package) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            path = PurePosixPath(info.filename)
            if (path.is_absolute() or ".." in path.parts or ":" in info.filename or "\\" in info.filename
                    or len(path.parts) < 2 or path.parts[0] != PROJECT or path.parts[1] in KEEP):
                raise UpdateError(f"Podejrzana ścieżka w paczce: {info.filename}")
            destination = target.joinpath(*path.parts[1:])
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, open(destination, "wb") as out:
                shutil.copyfileobj(source, out)
    if (read_version(target / "VERSION.md") != version or not (target / "app.py").is_file()
            or not (target / f"{PROJECT}.pyw").is_file()):
        raise UpdateError(f"Paczka nie zawiera {NAME} w wersji {version}.")


def describe(exc: Exception) -> str:
    if isinstance(exc, UpdateError):
        return str(exc)
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (403, 429):
            return "GitHub chwilowo ogranicza liczbę zapytań. Spróbuj później."
        return f"GitHub odpowiedział błędem {exc.code}."
    if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError)):
        return "Brak połączenia z GitHubem."
    return "Nieoczekiwana odpowiedź GitHuba."


class Updater:
    """Stan aktualizacji dla interfejsu i praca w tle: sprawdzanie raz na dobę, pobieranie, przygotowanie."""

    def __init__(self, data: Path, version: str, log=print) -> None:
        self.version = version
        self.staging = data / "update"
        self.settings_file = data / "aktualizacje.json"
        self.user_agent = f"{PROJECT}/{version}"
        self.log = log
        self._lock = threading.Lock()
        self._busy = False
        self.settings = {"auto": True, "last_check": 0.0, "last_version": version}
        try:
            self.settings.update(json.loads(self.settings_file.read_text("utf-8")))
        except (OSError, ValueError):
            pass
        self.updated_from = None  # numer sprzed aktualizacji zainstalowanej przy tym starcie
        if self.settings.get("last_version") != version:
            self.updated_from = self.settings.get("last_version")
            self.settings["last_version"] = version
            self._save_settings()
        self.state = {"status": "idle", "release": None, "progress": None, "error": None}
        self._detect_staged()

    def _save_settings(self) -> None:
        self.settings_file.parent.mkdir(parents=True, exist_ok=True)
        self.settings_file.write_text(json.dumps(self.settings), "utf-8")

    def _detect_staged(self) -> None:
        """Paczka pobrana wcześniej, czekająca na instalację przy starcie."""
        try:
            staged = json.loads((self.staging / "gotowe.json").read_text("utf-8"))
        except (OSError, ValueError):
            return
        version = str(staged.get("version", ""))
        if VERSION_RE.fullmatch(version) and parse_version(version) > parse_version(self.version):
            self.state.update(status="ready", release=staged)
        else:
            shutil.rmtree(self.staging, ignore_errors=True)  # przygotowana wersja nie jest już nowsza

    def snapshot(self) -> dict:
        with self._lock:
            return {"current": self.version, "name": NAME, "site": SITE, "auto": self.settings["auto"],
                    "last_check": self.settings["last_check"] or None, "updated_from": self.updated_from,
                    **self.state}

    def set_auto(self, enabled: bool) -> dict:
        with self._lock:
            self.settings["auto"] = enabled
            self._save_settings()
        return self.snapshot()

    def check(self) -> dict:
        """Pyta hub o wydania. Nie rzuca wyjątków: błąd trafia do stanu i dziennika."""
        with self._lock:
            if self._busy or self.state["status"] in ("downloading", "ready"):
                return self._snapshot_unlocked()
            self._busy = True
            self.state.update(status="checking", error=None)
        try:
            release = pick_release(fetch_releases(self.user_agent), self.version)
            with self._lock:
                self.settings["last_check"] = time.time()
                self._save_settings()
                self.state.update(status="available" if release else "up_to_date", release=release)
        except Exception as exc:
            self.log(f"Aktualizacje: sprawdzenie nie powiodło się: {exc!r}")
            with self._lock:
                self.state.update(status="failed", error=describe(exc))
        finally:
            with self._lock:
                self._busy = False
        return self.snapshot()

    def _snapshot_unlocked(self) -> dict:
        return {"current": self.version, "name": NAME, "site": SITE, "auto": self.settings["auto"],
                "last_check": self.settings["last_check"] or None, "updated_from": self.updated_from,
                **self.state}

    def download(self) -> None:
        """Pobiera, sprawdza i rozpakowuje dostępne wydanie. Wywoływać w osobnym wątku."""
        with self._lock:
            release = self.state.get("release")
            if self._busy or self.state["status"] != "available" or not release:
                return
            self._busy = True
            self.state.update(status="downloading", progress=0.0, error=None)
        work = self.staging
        try:
            shutil.rmtree(work, ignore_errors=True)
            work.mkdir(parents=True)
            sums_file = work / release["checksums"]["name"]
            download(release["checksums"]["url"], sums_file, self.user_agent, release["checksums"]["size"])
            expected = parse_checksums(sums_file.read_text("utf-8")).get(release["package"]["name"])
            if not expected:
                raise UpdateError("Plik sum nie obejmuje paczki.")

            def progress(received: int, total: int | None) -> None:
                with self._lock:
                    self.state["progress"] = received / total if total else None

            package = work / release["package"]["name"]
            actual = download(release["package"]["url"], package, self.user_agent, release["package"]["size"], progress)
            if actual != expected:
                raise UpdateError("Suma SHA-256 paczki się nie zgadza.")
            files = work / "pliki"
            extract_package(package, files, release["version"])
            try:
                notes = changelog_section((files / "CHANGELOG.md").read_text("utf-8"), release["version"])
            except OSError:
                notes = ""
            staged = {**release, "notes": notes or release["notes"]}
            (work / "gotowe.json").write_text(json.dumps(staged, ensure_ascii=False), "utf-8")
            package.unlink()
            sums_file.unlink()
            with self._lock:
                self.state.update(status="ready", release=staged, progress=None)
            self.log(f"Aktualizacje: wersja {release['version']} gotowa do instalacji.")
        except Exception as exc:
            self.log(f"Aktualizacje: pobieranie nie powiodło się: {exc!r}")
            shutil.rmtree(work, ignore_errors=True)
            with self._lock:
                self.state.update(status="failed", error=describe(exc), progress=None)
        finally:
            with self._lock:
                self._busy = False

    def run(self) -> None:
        """Pętla w tle: przy włączonej opcji raz na dobę sprawdza i od razu pobiera nowe wydanie."""
        time.sleep(FIRST_CHECK_DELAY)
        while True:
            if self.settings["auto"] and time.time() - self.settings["last_check"] >= CHECK_INTERVAL:
                self.check()
                if self.settings["auto"] and self.state["status"] == "available":
                    self.download()
            time.sleep(RETRY_INTERVAL)
