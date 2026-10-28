"""Odniesienie do testu: faster-whisper z ustawieniami aplikacji, wynik w fw.json."""
import json
import time
import wave
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

HERE = Path(__file__).resolve().parent

# decode_audio z faster-whisper 1.2.1 nie działa z PyAV 19, a nagranie i tak jest w 16 kHz mono.
with wave.open(str(HERE / "mowa.wav")) as wav:
    assert wav.getframerate() == 16_000 and wav.getnchannels() == 1
    audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
t0 = time.perf_counter()
model = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8", cpu_threads=8,
                     download_root=str(HERE.parent / "models"))
t1 = time.perf_counter()
segments, _ = model.transcribe(audio, language="pl", word_timestamps=True, vad_filter=True,
                               condition_on_previous_text=False)
words = [{"w": w.word, "s": round(w.start, 3), "e": round(w.end, 3)} for seg in segments for w in seg.words]
t2 = time.perf_counter()
result = {
    "engine": "faster-whisper large-v3-turbo int8, CPU (aplikacja)",
    "load_s": round(t1 - t0, 1),
    "transcribe_s": round(t2 - t1, 1),
    "duration_s": round(len(audio) / 16_000, 2),
    "words": words,
}
(HERE / "fw.json").write_text(json.dumps(result, ensure_ascii=False), "utf-8")
print(f"ładowanie {result['load_s']} s, transkrypcja {result['transcribe_s']} s, słów {len(words)}")
