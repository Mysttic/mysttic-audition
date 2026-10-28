"""mysttic-audition: lokalny przegląd nagrań audio i wideo.

Transkrypcja z czasem każdego słowa (faster-whisper), wyszukiwanie fraz,
porównywanie i przycinanie fragmentów. Działa we własnym oknie (pywebview);
zamknięcie okna kończy cały proces. Serwer nasłuchuje tylko na 127.0.0.1.
"""
from __future__ import annotations

import ctypes
import json
import os
import queue
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path
from urllib.parse import unquote

import av
import imageio_ffmpeg
import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask

import updates

ROOT = Path(__file__).resolve().parent
APP_NAME = updates.NAME
VERSION = updates.read_version(ROOT / "VERSION.md")  # jedyne źródło numeru wersji
DATA = ROOT / "data"
MODELS_DIR = ROOT / "models"
STATIC = ROOT / "static"
HOST = "127.0.0.1"
PORT = int(os.environ.get("AUDITION_PORT", "8791"))  # gdy zajęty, okno dostaje port od systemu
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
SR = 16_000            # częstotliwość próbkowania wejścia Whispera
PEAKS_PER_SEC = 200    # rozdzielczość przebiegu fali
CPU_THREADS = max(1, (os.cpu_count() or 8) // 2)
MODELS = ("large-v3-turbo", "small", "medium", "large-v3")
LANGUAGES = ("pl", "auto", "en", "de", "uk", "ru", "cs", "sk", "fr", "es", "it")
# katalogi pamięci podręcznej Hugging Face w models/, z których faster-whisper wczytuje modele
MODEL_REPOS = {
    "large-v3-turbo": "mobiuslabsgmbh--faster-whisper-large-v3-turbo",
    "small": "Systran--faster-whisper-small",
    "medium": "Systran--faster-whisper-medium",
    "large-v3": "Systran--faster-whisper-large-v3",
}
ID_RE = re.compile(r"[0-9a-f]{8}")
LOSSLESS = {"flac", "alac", "wavpack", "tta", "ape", "truehd", "mlp", "shorten"}
COVER_CODECS = {"mjpeg", "png", "bmp", "gif"}  # okładki w MP3/M4A to nie wideo
# PCM, które mieści się w WAV. WAV liczy pozycję co do próbki, Matroska zaokrągla czas do 1 ms.
PCM_WAV = {"pcm_u8", "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "pcm_f64le", "pcm_alaw", "pcm_mulaw"}
# Kontener dla eksportu bez ponownego kodowania; pozostałe kodeki trafiają do .mka.
COPY_EXT = {
    "mp3": "mp3", "aac": "m4a", "alac": "m4a", "flac": "flac", "opus": "opus",
    "vorbis": "ogg", "ac3": "ac3", "eac3": "eac3", **{codec: "wav" for codec in PCM_WAV},
}

# faster_whisper (a z nim huggingface_hub) importujemy dopiero przy transkrypcji.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


# ---------- metadane plików ----------

_meta_lock = threading.RLock()


def meta_path(fid: str) -> Path:
    return DATA / fid / "meta.json"


def load_meta(fid: str) -> dict:
    with _meta_lock:
        return json.loads(meta_path(fid).read_text("utf-8"))


def save_meta(meta: dict) -> None:
    with _meta_lock:
        path = meta_path(meta["id"])
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
        os.replace(tmp, path)


def edit_meta(fid: str, change) -> dict:
    """Odczyt, zmiana i zapis meta.json jako jedna operacja."""
    with _meta_lock:
        meta = load_meta(fid)
        change(meta)
        save_meta(meta)
        return meta


def file_dir(fid: str) -> Path:
    if not ID_RE.fullmatch(fid) or not meta_path(fid).is_file():
        raise HTTPException(404, "Nie ma takiego pliku w bibliotece.")
    return DATA / fid


# ---------- przygotowanie dźwięku ----------

def ffmpeg(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [FFMPEG, "-hide_banner", "-nostdin", "-v", "error", "-y", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def probe(path: Path) -> dict:
    try:
        container = av.open(str(path))
    except av.error.FFmpegError as exc:
        raise ValueError(f"Nie rozpoznano pliku audio ani wideo ({exc}).") from exc
    with container:
        streams = list(container.streams)
        audio = [s for s in streams if s.type == "audio"]
        if not audio:
            raise ValueError("Plik nie zawiera ścieżki dźwiękowej.")
        cc = audio[0].codec_context
        fmt = cc.format.name if cc.format else ""
        lossless = cc.name.startswith("pcm_") or cc.name in LOSSLESS
        return {
            "codec": cc.name,
            "sample_rate": cc.sample_rate,
            "channels": cc.layout.nb_channels,
            # Stratne kodeki dekodują się do float; 16 bitów w zupełności wystarcza.
            "bits": 24 if lossless and fmt.rstrip("p") not in ("u8", "s16") else 16,
            "has_video": any(s.type == "video" and s.codec_context.name not in COVER_CODECS for s in streams),
            "audio_tracks": len(audio),
        }


def write_peaks(samples: np.ndarray, path: Path) -> None:
    """Maksimum amplitudy w oknach 1/PEAKS_PER_SEC s, przeskalowane do 0..255."""
    step = SR // PEAKS_PER_SEC
    count = -(-samples.size // step)
    padded = np.zeros(count * step, dtype=np.int32)
    padded[: samples.size] = np.abs(samples.astype(np.int32))
    peaks = padded.reshape(count, step).max(axis=1).astype(np.float32)
    ref = float(np.percentile(peaks, 99.9)) or 1.0
    np.clip(np.round(peaks / ref * 255), 0, 255).astype(np.uint8).tofile(path)


def prepare(fid: str) -> None:
    """Z przesłanego pliku robi: kopię oryginalnej ścieżki, podgląd FLAC, PCM 16 kHz i przebieg fali."""
    d = DATA / fid
    src = d / load_meta(fid)["upload"]
    try:
        info = probe(src)
        original_name = "original.wav" if info["codec"] in PCM_WAV else "original.mka"
        rf64 = ["-rf64", "auto"] if original_name.endswith(".wav") else []  # WAV powyżej 4 GB
        original = ["-map", "0:a:0", "-c", "copy", *rf64, str(d / original_name)]
        sample_fmt = "s32" if info["bits"] == 24 else "s16"
        proxy = ["-map", "0:a:0", "-c:a", "flac", "-sample_fmt", sample_fmt, str(d / "proxy.flac")]
        pcm = ["-map", "0:a:0", "-ac", "1", "-ar", str(SR), "-f", "s16le", str(d / "pcm16k.raw")]
        result = ffmpeg("-i", str(src), *original, *proxy, *pcm)
        has_original = result.returncode == 0
        if not has_original:
            # Niektórych kodeków nie da się skopiować do Matroski; wtedy zostaje sam podgląd.
            (d / original_name).unlink(missing_ok=True)
            result = ffmpeg("-i", str(src), *proxy, *pcm)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip()[-600:] or "ffmpeg zakończył się błędem.")
        samples = np.fromfile(d / "pcm16k.raw", dtype="<i2")
        if samples.size == 0:
            raise ValueError("Ścieżka dźwiękowa jest pusta.")
        write_peaks(samples, d / "peaks.u8")
        src.unlink()  # przesłana kopia nie jest już potrzebna, oryginał użytkownika zostaje u niego

        def ready(meta: dict) -> None:
            meta.update(status="ready", audio=info, has_original=has_original,
                        original=original_name if has_original else None,
                        duration=round(samples.size / SR, 3), peaks_per_sec=PEAKS_PER_SEC)
            meta.pop("upload")
            meta["transcript"]["status"] = "queued"

        edit_meta(fid, ready)
        JOBS.put(fid)
    except Exception as exc:
        edit_meta(fid, lambda meta: meta.update(status="error", error=str(exc)[:600]))


# ---------- transkrypcja ----------

JOBS: queue.Queue[str] = queue.Queue()
LIVE: dict[str, dict] = {}  # trwająca transkrypcja: {"segments": [...], "progress": 0..1}
_model_cache: dict[str, object] = {}


def get_model(name: str):
    if name not in _model_cache:
        from faster_whisper import WhisperModel

        _model_cache.clear()  # w pamięci trzymamy jeden model naraz
        _model_cache[name] = WhisperModel(name, device="cpu", compute_type="int8",
                                          cpu_threads=CPU_THREADS, download_root=str(MODELS_DIR))
    return _model_cache[name]


def transcribe(fid: str) -> None:
    d = DATA / fid
    if not meta_path(fid).is_file():
        return  # usunięty z biblioteki, zanim przyszła jego kolej
    job = edit_meta(fid, lambda m: m["transcript"].update(status="running", phase="model", error=None))["transcript"]
    live = LIVE[fid] = {"segments": [], "progress": 0.0}
    model = get_model(job["model"])
    edit_meta(fid, lambda m: m["transcript"].update(phase="transcribe"))
    audio = np.fromfile(d / "pcm16k.raw", dtype="<i2").astype(np.float32) / 32768.0
    started = time.time()
    segments, info = model.transcribe(
        audio,
        language=None if job["language"] == "auto" else job["language"],
        word_timestamps=True,
        vad_filter=True,                   # pomija ciszę i ogranicza halucynacje
        condition_on_previous_text=False,  # mniej zapętleń na długich nagraniach
    )
    for seg in segments:
        words = [{"w": w.word, "s": round(w.start, 3), "e": round(w.end, 3), "p": round(w.probability, 2)}
                 for w in seg.words or []]
        if not words and seg.text.strip():
            words = [{"w": " " + seg.text.strip(), "s": round(seg.start, 3), "e": round(seg.end, 3), "p": 1.0}]
        live["segments"].append({"start": round(seg.start, 3), "end": round(seg.end, 3), "words": words})
        live["progress"] = min(1.0, seg.end / max(info.duration, 0.001))
    seconds = round(time.time() - started, 1)
    result = {"model": job["model"], "language": info.language, "segments": live["segments"]}
    (d / "transcript.json").write_text(json.dumps(result, ensure_ascii=False), "utf-8")
    edit_meta(fid, lambda m: m["transcript"].update(
        status="done", phase=None, detected_language=info.language, seconds=seconds))


def worker() -> None:
    while True:
        fid = JOBS.get()
        try:
            transcribe(fid)
        except Exception as exc:  # błąd jednego pliku nie zatrzymuje kolejki
            if meta_path(fid).is_file():
                edit_meta(fid, lambda m: m["transcript"].update(status="error", phase=None, error=str(exc)[:600]))
        finally:
            LIVE.pop(fid, None)


def recover() -> None:
    """Po restarcie: przerwane przygotowanie to błąd, przerwana transkrypcja wraca do kolejki."""
    DATA.mkdir(exist_ok=True)
    metas = sorted((load_meta(p.parent.name) for p in DATA.glob("*/meta.json")), key=lambda m: m["created"])
    for meta in metas:
        if meta["status"] == "processing":
            edit_meta(meta["id"], lambda m: m.update(
                status="error", error="Przygotowanie przerwane przez zamknięcie aplikacji. Dodaj plik ponownie."))
        elif meta["status"] == "ready" and meta["transcript"]["status"] in ("queued", "running"):
            edit_meta(meta["id"], lambda m: m["transcript"].update(status="queued", phase=None))
            JOBS.put(meta["id"])


# ---------- pomocnicze ----------

def check_options(model: str, language: str) -> None:
    if model not in MODELS or language not in LANGUAGES:
        raise HTTPException(400, "Nieznany model lub język.")


def safe_stem(name: str) -> str:
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", Path(name).stem).strip(" .")
    return stem[:60] or "nagranie"


def stamp(t: float) -> str:
    """Czas do nazwy pliku, np. 01m23s450."""
    ms = round(t * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return (f"{h}h" if h else "") + f"{m:02d}m{s:02d}s{ms:03d}"


# ---------- API ----------

app = FastAPI(title=APP_NAME, version=VERSION)


@app.middleware("http")
async def no_cache_for_ui(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/files")
def list_files() -> list[dict]:
    DATA.mkdir(exist_ok=True)
    metas = []
    for path in DATA.glob("*/meta.json"):
        try:
            metas.append(load_meta(path.parent.name))
        except (OSError, ValueError):
            pass  # katalog w trakcie usuwania
    return sorted(metas, key=lambda m: m["created"], reverse=True)


@app.put("/api/files")
async def upload(request: Request, model: str = MODELS[0], language: str = "pl") -> dict:
    """Przyjmuje surową zawartość pliku (nazwa w nagłówku X-Filename) i zapisuje ją strumieniowo."""
    check_options(model, language)
    name = Path(unquote(request.headers.get("x-filename", ""))).name or "nagranie"
    suffix = Path(name).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
        suffix = ""
    DATA.mkdir(exist_ok=True)
    fid = secrets.token_hex(4)
    while (DATA / fid).exists():
        fid = secrets.token_hex(4)
    d = DATA / fid
    d.mkdir()
    size = 0
    try:
        with open(d / f"upload{suffix}", "wb") as out:
            async for chunk in request.stream():
                out.write(chunk)
                size += len(chunk)
        if size == 0:
            raise HTTPException(400, "Plik jest pusty.")
    except BaseException:
        shutil.rmtree(d, ignore_errors=True)
        raise
    meta = {
        "id": fid, "name": name, "size": size, "created": time.time(),
        "status": "processing", "upload": f"upload{suffix}",
        "transcript": {"status": "waiting", "model": model, "language": language},
    }
    save_meta(meta)
    threading.Thread(target=prepare, args=(fid,), daemon=True).start()
    return meta


@app.get("/api/files/{fid}")
def get_file(fid: str) -> dict:
    file_dir(fid)
    return load_meta(fid)


@app.delete("/api/files/{fid}")
def delete_file(fid: str) -> dict:
    d = file_dir(fid)
    meta = load_meta(fid)
    if meta["status"] == "processing" or meta["transcript"]["status"] == "running":
        raise HTTPException(409, "Plik jest właśnie przetwarzany. Spróbuj po zakończeniu.")
    try:
        shutil.rmtree(d)
    except OSError as exc:
        raise HTTPException(409, f"Nie udało się usunąć wszystkich danych ({exc.strerror}). Spróbuj ponownie.")
    return {"deleted": fid}


@app.get("/api/files/{fid}/peaks")
def get_peaks(fid: str) -> FileResponse:
    return FileResponse(file_dir(fid) / "peaks.u8", media_type="application/octet-stream")


@app.get("/api/files/{fid}/audio")
def get_audio(fid: str) -> FileResponse:
    return FileResponse(file_dir(fid) / "proxy.flac", media_type="audio/flac")


@app.get("/api/files/{fid}/transcript")
def get_transcript(fid: str, since: int = 0) -> dict:
    d = file_dir(fid)
    job = load_meta(fid)["transcript"]
    if job["status"] == "done":
        segments = json.loads((d / "transcript.json").read_text("utf-8"))["segments"]
    else:
        live = LIVE.get(fid)
        segments = live["segments"] if live else []
        job["progress"] = live["progress"] if live else 0.0
    return {"transcript": job, "segments": segments[since:], "count": len(segments)}


class TranscribeRequest(BaseModel):
    model: str
    language: str


@app.post("/api/files/{fid}/transcribe")
def retranscribe(fid: str, req: TranscribeRequest) -> dict:
    d = file_dir(fid)
    check_options(req.model, req.language)
    with _meta_lock:
        meta = load_meta(fid)
        if meta["status"] != "ready":
            raise HTTPException(409, "Plik nie jest jeszcze gotowy.")
        if meta["transcript"]["status"] in ("queued", "running"):
            raise HTTPException(409, "Transkrypcja tego pliku już trwa.")
        (d / "transcript.json").unlink(missing_ok=True)
        meta = edit_meta(fid, lambda m: m.update(
            transcript={"status": "queued", "model": req.model, "language": req.language}))
    JOBS.put(fid)
    return meta


@app.get("/api/files/{fid}/export")
def export(fid: str, start: float, end: float, mode: str = "wav") -> FileResponse:
    d = file_dir(fid)
    meta = load_meta(fid)
    if meta["status"] != "ready":
        raise HTTPException(409, "Plik nie jest jeszcze gotowy.")
    start, end = max(0.0, start), min(end, meta["duration"])
    if end - start < 0.01:
        raise HTTPException(400, "Fragment jest za krótki.")
    if mode == "wav":
        # Podgląd FLAC to bezstratnie zdekodowany oryginał, więc cięcie jest dokładne co do próbki.
        source, ext = d / "proxy.flac", "wav"
        codec = ["-c:a", "pcm_s24le" if meta["audio"]["bits"] == 24 else "pcm_s16le"]
    elif mode == "copy":
        if not meta.get("has_original"):
            raise HTTPException(409, "Tej ścieżki nie da się przyciąć bez ponownego kodowania. Użyj WAV.")
        # Kopia oryginalnych ramek: dane bez zmian, granice cięcia z dokładnością do ramki kodeka.
        # PCM nie ma ramek, więc te same próbki zapisane tym samym kodekiem dają cięcie co do próbki.
        original_codec = meta["audio"]["codec"]
        source, ext = d / meta["original"], COPY_EXT.get(original_codec, "mka")
        codec = ["-c:a", original_codec if original_codec.startswith("pcm_") else "copy"]
    else:
        raise HTTPException(400, "Nieznany tryb eksportu.")
    out_dir = d / "exports"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{secrets.token_hex(4)}.{ext}"
    result = ffmpeg("-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(source),
                    "-map", "0:a:0", *codec, str(out))
    if result.returncode != 0:
        out.unlink(missing_ok=True)
        raise HTTPException(500, "Eksport nie powiódł się: " + result.stderr.strip()[-400:])
    name = f"{safe_stem(meta['name'])}_{stamp(start)}-{stamp(end)}.{ext}"
    return FileResponse(out, filename=name, background=BackgroundTask(out.unlink, missing_ok=True))


# ---------- wersja i aktualizacje ----------

UPDATER: updates.Updater | None = None  # tworzony przy starcie, gdy wiadomo, w jakim trybie działamy


def updater() -> updates.Updater:
    if UPDATER is None:
        raise HTTPException(503, "Aktualizacje nie są jeszcze gotowe.")
    return UPDATER


@app.get("/api/version")
def get_version() -> dict:
    return {"name": APP_NAME, "version": VERSION}


# ---------- ustawienia i dane ----------

SETTINGS_FILE = DATA / "ustawienia.json"  # w folderze danych, a nie w profilu WebView2, więc nie zależy od portu
DEFAULT_SETTINGS = {"model": MODELS[0], "language": "pl", "follow": True}
_settings_lock = threading.Lock()


def load_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
    try:
        stored = json.loads(SETTINGS_FILE.read_text("utf-8"))
        settings.update({key: value for key, value in stored.items() if key in DEFAULT_SETTINGS})
    except (OSError, ValueError, AttributeError):
        pass
    return settings


class SettingsUpdate(BaseModel):
    model: str | None = None
    language: str | None = None
    follow: bool | None = None


@app.get("/api/settings")
def get_settings() -> dict:
    return load_settings()


@app.post("/api/settings")
def save_settings(req: SettingsUpdate) -> dict:
    with _settings_lock:
        settings = load_settings()
        settings.update(req.model_dump(exclude_none=True))
        check_options(settings["model"], settings["language"])
        DATA.mkdir(exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(settings), "utf-8")
    return settings


def disk_usage(path: Path) -> int:
    """Bajty plików w katalogu. Dowiązania symboliczne pomijamy, bo liczą się tam, dokąd prowadzą."""
    total = 0
    for folder, _, names in os.walk(path):
        for name in names:
            try:
                info = os.lstat(os.path.join(folder, name))
            except OSError:
                continue
            if not stat.S_ISLNK(info.st_mode):
                total += info.st_size
    return total


def model_bytes(name: str) -> int:
    """Rozmiar modelu: pliki migawki prowadzą dowiązaniami do wspólnego katalogu blobs/."""
    total = 0
    for path in (MODELS_DIR / f"models--{MODEL_REPOS[name]}" / "snapshots").glob("*/*"):
        try:
            total += path.stat().st_size if path.is_file() else 0
        except OSError:
            pass
    return total


@app.get("/api/storage")
def get_storage() -> dict:
    models = [{"name": name, "bytes": model_bytes(name)} for name in MODELS
              if (MODELS_DIR / f"models--{MODEL_REPOS[name]}").is_dir()]
    return {
        "data_dir": str(DATA), "data_bytes": disk_usage(DATA) if DATA.exists() else 0,
        "files": sum(1 for _ in DATA.glob("*/meta.json")),
        "models_dir": str(MODELS_DIR), "models_bytes": disk_usage(MODELS_DIR) if MODELS_DIR.exists() else 0,
        "models": models,
    }


class FolderRequest(BaseModel):
    folder: str


@app.post("/api/open-folder")
def open_folder(req: FolderRequest) -> dict:
    path = {"data": DATA, "models": MODELS_DIR}.get(req.folder)
    if path is None:
        raise HTTPException(400, "Nieznany folder.")
    path.mkdir(exist_ok=True)
    os.startfile(path)  # otwiera Eksplorator Windows
    return {"opened": str(path)}


@app.get("/api/update")
def update_state() -> dict:
    return updater().snapshot()


@app.post("/api/update/check")
def update_check() -> dict:
    return updater().check()


@app.post("/api/update/download")
def update_download() -> dict:
    threading.Thread(target=updater().download, daemon=True, name="aktualizacja").start()
    return updater().snapshot()


class UpdateSettings(BaseModel):
    auto: bool


@app.post("/api/update/settings")
def update_settings(req: UpdateSettings) -> dict:
    return updater().set_auto(req.auto)


@app.post("/api/update/restart")
def update_restart() -> dict:
    """Zamyka okno; launcher czeka na koniec procesu, instaluje aktualizację i otwiera aplikację od nowa."""
    if WINDOW is None:
        raise HTTPException(409, "Ponowne uruchomienie działa tylko w oknie aplikacji.")
    if updater().snapshot()["status"] != "ready":
        raise HTTPException(409, "Nie ma przygotowanej aktualizacji.")
    launcher = shutil.which("pyw") or sys.executable
    subprocess.Popen(  # poza obiektem zadania, inaczej zginąłby razem z tym procesem
        [launcher, str(ROOT / "mysttic-audition.pyw"), "--czekaj", str(os.getpid())], cwd=ROOT,
        creationflags=subprocess.CREATE_BREAKAWAY_FROM_JOB | subprocess.DETACHED_PROCESS)
    threading.Timer(0.3, WINDOW.destroy).start()  # odpowiedź zdąży dojść, zanim okno zniknie
    return {"restarting": True}


# ---------- uruchomienie ----------

WINDOW = None  # okno aplikacji (pywebview)
INSTANCE_FILE = DATA / "instance.json"  # port działającej instancji, dla drugiego uruchomienia
LOG_FILE = DATA / "app.log"


@app.post("/api/focus", include_in_schema=False)
def focus_window() -> dict:
    """Drugie uruchomienie nie otwiera nowego okna, tylko wyciąga istniejące na wierzch."""
    if WINDOW is None:
        raise HTTPException(404, "Aplikacja działa bez okna.")
    WINDOW.restore()
    WINDOW.on_top = True
    WINDOW.on_top = False
    return {"focused": True}


def focus_running_instance() -> bool:
    try:
        port = json.loads(INSTANCE_FILE.read_text("utf-8"))["port"]
        request = urllib.request.Request(f"http://{HOST}:{port}/api/focus", method="POST")
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status == 200
    except (OSError, ValueError, KeyError, TypeError):
        return False  # brak instancji albo plik został po awarii


def kill_children_with_app() -> None:
    """Obiekt zadania Windows: ffmpeg i procesy WebView2 kończą się razem z aplikacją, także po awarii."""
    from ctypes import wintypes

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

    class BasicLimits(ctypes.Structure):
        _fields_ = [("per_process_time", ctypes.c_int64), ("per_job_time", ctypes.c_int64),
                    ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
                    ("max_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                    ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("basic", BasicLimits), ("io", IoCounters), ("process_memory", ctypes.c_size_t),
                    ("job_memory", ctypes.c_size_t), ("peak_process_memory", ctypes.c_size_t),
                    ("peak_job_memory", ctypes.c_size_t)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = kernel32.CreateJobObjectW(None, None)
    limits = ExtendedLimits()
    # KILL_ON_JOB_CLOSE kończy procesy potomne razem z aplikacją; BREAKAWAY_OK pozwala wyjść z zadania
    # tylko temu, kto o to poprosi wprost (launcher przy ponownym uruchomieniu po aktualizacji).
    limits.basic.flags = 0x2000 | 0x0800
    configured = kernel32.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
    if not (configured and kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess())):
        print(f"Obiekt zadania niedostępny (błąd {ctypes.get_last_error()}).", flush=True)
    # Uchwytu nie zamykamy: system zamknie go razem z procesem i wtedy zakończy procesy potomne.


def bind_socket() -> socket.socket:
    """Stały port zachowuje ustawienia interfejsu między uruchomieniami; gdy jest zajęty, port wybiera system."""
    for port in (PORT, 0):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((HOST, port))
            sock.listen(64)
            return sock
        except OSError:
            sock.close()
    raise OSError("Brak wolnego portu na 127.0.0.1.")


def log_to_file() -> None:
    """pythonw nie ma konsoli: komunikaty i błędy trafiają do data/app.log."""
    DATA.mkdir(exist_ok=True)
    mode = "w" if LOG_FILE.exists() and LOG_FILE.stat().st_size > 5_000_000 else "a"
    sys.stdout = sys.stderr = open(LOG_FILE, mode, encoding="utf-8", buffering=1)
    print(f"start {time.strftime('%Y-%m-%d %H:%M:%S')}, {APP_NAME} {VERSION}, pid {os.getpid()}")


def run_desktop() -> None:
    """Program z własnym oknem. Zamknięcie okna kończy wszystko: serwer, transkrypcję i ffmpeg."""
    global WINDOW, UPDATER
    if sys.stderr is None:
        log_to_file()
    import webview  # okno z Edge WebView2, potrzebne tylko w tym trybie

    if focus_running_instance():
        return
    kill_children_with_app()
    # własny identyfikator: pasek zadań grupuje okno osobno od innych programów w Pythonie i pokazuje jego ikonę
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Mysttic.Audition")
    recover()
    threading.Thread(target=worker, daemon=True, name="transkrypcja").start()
    UPDATER = updates.Updater(DATA, VERSION)
    threading.Thread(target=UPDATER.run, daemon=True, name="aktualizacje").start()
    sock = bind_socket()
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_config=None, log_level="warning"))
    threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True, name="serwer").start()
    INSTANCE_FILE.write_text(json.dumps({"pid": os.getpid(), "port": port}), "utf-8")

    webview.settings["ALLOW_DOWNLOADS"] = True  # eksport fragmentu otwiera okno „Zapisz jako”
    WINDOW = webview.create_window(
        APP_NAME, f"http://{HOST}:{port}/", width=1400, height=900, min_size=(1000, 640),
        background_color="#14161a", text_select=True)
    webview.start(private_mode=False, storage_path=str(ROOT / ".webview"), icon=str(STATIC / "icon.ico"))

    # Okno zamknięte: proces kończy się od razu, bez czekania na trwającą transkrypcję. System zwalnia
    # pamięć modelu, a przerwana transkrypcja wraca do kolejki przy następnym uruchomieniu.
    INSTANCE_FILE.unlink(missing_ok=True)
    os._exit(0)


def run_server() -> None:
    """Tryb deweloperski: sam serwer na stałym porcie, bez okna. Ctrl+C kończy.

    Aktualizacje można tu sprawdzić i pobrać ręcznie, ale bez pracy w tle i bez ponownego uruchamiania.
    """
    global UPDATER
    recover()
    threading.Thread(target=worker, daemon=True, name="transkrypcja").start()
    UPDATER = updates.Updater(DATA, VERSION)
    print(f"{APP_NAME} {VERSION} (serwer): http://{HOST}:{PORT}/", flush=True)
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


def main() -> None:
    if "--server" in sys.argv:
        run_server()
        return
    try:
        run_desktop()
    except Exception as exc:
        traceback.print_exc()
        ctypes.windll.user32.MessageBoxW(
            None, f"Nie udało się uruchomić aplikacji:\n{exc}\n\nSzczegóły: {LOG_FILE}", APP_NAME, 0x10)
        os._exit(1)


if __name__ == "__main__":
    main()
