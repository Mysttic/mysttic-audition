# Eksperyment: Whisper w przeglądarce

Sprawdzenie z 28.10.2026, czy aplikacja mogłaby działać w całości w przeglądarce (na przykład z
github.io) zamiast z Pythonem. Wniosek: da się, ale zostaje wersja lokalna, bo jest ok. 2,4 raza
szybsza i nie pobiera modelu w każdej przeglądarce.

Wzorzec to nagranie z syntezatora mowy Windows, który zapisuje prawdziwy początek każdego ze 139 słów.

| | faster-whisper (aplikacja, procesor) | Transformers.js 4.3.2, WebGPU, model 564 MB |
|---|---|---|
| Pierwsze otwarcie | model z dysku | 28 s (pobranie i załadowanie) |
| Transkrypcja 70,9 s nagrania | 16,5 s | 39,1 s |
| Tekst | wzorcowy | identyczny |
| Stałe przesunięcie czasów słów | 0,05 s za wcześnie | 0,16 s za późno |
| Średni błąd po odjęciu przesunięcia | 0,05 s | 0,05 s |

Pomiar na Ryzen 7 8845HS z Radeonem 780M. Pełny model 1,6 GB (enkoder fp16) dał ten sam tekst
i tę samą dokładność przy 43,6 s.

## Powtórzenie

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File spike/tts_gt.ps1 -TextFile spike/tekst.txt -OutWav spike/mowa.wav -OutJson spike/mowa_gt.json
```

```bash
.venv/Scripts/python.exe spike/fw_reference.py
```

```bash
.venv/Scripts/python.exe -m http.server 8792 --bind 127.0.0.1 --directory spike
```

Potem http://127.0.0.1:8792/ w przeglądarce z WebGPU. Parametry w adresie: `v` (wersja
Transformers.js), `model`, `enc` i `dec` (rodzaj wag), `auto` (start od razu), na przykład
`?enc=q4f16&dec=q4f16&auto`.
