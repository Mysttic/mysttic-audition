# Experiment: Whisper in the browser

A check from 28 October 2026 of whether the app could run entirely in the browser (for example
from github.io) instead of with Python. Conclusion: it can, but the app stays local, because the
local version is about 2.4 times faster and does not download the model in every browser.

The reference is a recording from the Windows speech synthesizer, which reports the true start
of each of its 139 words.

| | faster-whisper (the app, CPU) | Transformers.js 4.3.2, WebGPU, 564 MB model |
|---|---|---|
| First start | model from disk | 28 s (download and load) |
| Transcribing 70.9 s of audio | 16.5 s | 39.1 s |
| Text | the reference | identical |
| Constant shift of word times | 0.05 s early | 0.16 s late |
| Mean error after removing the shift | 0.05 s | 0.05 s |

Measured on a Ryzen 7 8845HS with a Radeon 780M. The full 1.6 GB model (fp16 encoder) gave the
same text and the same accuracy in 43.6 s.

## Reproducing

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File spike/tts_gt.ps1 -TextFile spike/tekst.txt -OutWav spike/mowa.wav -OutJson spike/mowa_gt.json
```

```bash
.venv/Scripts/python.exe spike/fw_reference.py
```

```bash
.venv/Scripts/python.exe -m http.server 8792 --bind 127.0.0.1 --directory spike
```

Then open http://127.0.0.1:8792/ in a browser with WebGPU. URL parameters: `v` (the
Transformers.js version), `model`, `enc` and `dec` (weight types), `auto` (start at once), for
example `?enc=q4f16&dec=q4f16&auto`.
