<p align="center">
  <img src="brand/icon.svg" width="96" height="96" alt="">
</p>

<h1 align="center">Mysttic Audition</h1>

<p align="center">
  Lokalna aplikacja Windows do przeglądania nagrań: transkrypcja z czasem każdego słowa,
  wyszukiwanie słów i fraz, porównywanie i przycinanie fragmentów. Dźwięk nie jest w żaden
  sposób modyfikowany, a nagrania nie opuszczają komputera.
</p>

<p align="center">
  <a href="https://mysttic.github.io/Mysttic/mysttic-audition/"><b>Pobierz</b></a>
  &nbsp;·&nbsp; <a href="CHANGELOG.md">Historia zmian</a>
  &nbsp;·&nbsp; <a href="VERSION.md">Numer wersji</a>
</p>

![Mysttic Audition z otwartym nagraniem: przebieg fali z dwoma fragmentami, transkrypcja i wyniki wyszukiwania słowa „umowa”](docs/zrzut.png)

## Co potrafi

- **Audio i wideo bez konwersji.** MP3, WAV, M4A, FLAC, OGG, OPUS, WMA, MP4, MKV, MOV, AVI,
  WEBM i inne. Ścieżkę dźwiękową z wideo aplikacja wyciąga sama.
- **Transkrypcja na tym komputerze.** Whisper large-v3-turbo z czasem każdego słowa. Tekst
  pojawia się na bieżąco, kliknięcie słowa odtwarza nagranie od tego miejsca, a słowa
  rozpoznane z niską pewnością są podkreślone.
- **Szukanie z odmianą.** Wielkość liter, ogonki i interpunkcja nie mają znaczenia. „umowa”
  znajdzie „umowy” i „umowie”, a fraza „kara umowna” także „karę umowną”.
- **Fragmenty i porównanie A/B.** Zaznaczenie na fali albo „+” przy wyniku wyszukiwania,
  klawisze 1 do 9 i pętla.
- **Przycinanie bez modyfikacji.** WAV wycięty co do próbki albo oryginalny kodek bez
  ponownego kodowania.
- **Program jak każdy inny w Windows.** Własne okno i jedna kopia; zamknięcie okna kończy
  wszystko, łącznie z transkrypcją i pamięcią zajętą przez model.
- **Aktualizacje.** Raz na dobę, ze sprawdzeniem sumy SHA-256, instalacja przy następnym starcie.

## Instalacja

Wymagania:

- Windows 10 lub 11 z Microsoft Edge WebView2 (w Windows 11 jest w systemie);
- Python 3.10 lub nowszy z [python.org](https://www.python.org/downloads/), razem z „py
  launcher”, dzięki któremu działa dwuklik w pliki `.pyw`;
- około 2 GB miejsca na zależności i domyślny model;
- internet przy pierwszym uruchomieniu (zależności) i przy pierwszej transkrypcji (model, 1,6 GB).

Kroki:

1. Pobierz `mysttic-audition-<wersja>-windows.zip` ze
   [strony projektu](https://mysttic.github.io/Mysttic/mysttic-audition/) i rozpakuj w wybranym
   miejscu.
2. Dwuklik `mysttic-audition.pyw`. Pierwszy start otwiera konsolę z instalacją zależności
   (kilka minut), potem aplikacja uruchamia się sama.

## Obsługa

| Czynność | Jak |
|---|---|
| Otwarcie pliku | „Otwórz plik…” albo przeciągnięcie pliku do okna |
| Odtwarzanie od słowa | kliknięcie słowa albo znacznika czasu w transkrypcji |
| Odtwarzanie i pauza | Spacja |
| Przewijanie | strzałki w lewo i w prawo, o 2 s |
| Szukanie | pole „Szukaj słowa lub frazy”; Enter i Shift+Enter przechodzą między wynikami |
| Fragment | przeciągnięcie po fali albo „+” przy wyniku |
| Porównanie A/B | klawisze 1 do 9 odtwarzają fragmenty, L włącza pętlę |
| Eksport | „WAV” albo „Oryginał” przy fragmencie, potem okno „Zapisz jako” |
| O aplikacji i aktualizacje | ikona z numerem wersji w lewym górnym rogu |

Eksport:

- **WAV**: cięcie co do próbki. Próbki są identyczne z oryginałem (dla formatów stratnych: ze
  zdekodowanym oryginałem).
- **Oryginał**: ramki oryginalnego kodeka bez ponownego kodowania, więc dane są nietknięte.
  Granice cięcia mają dokładność ramki kodeka, około 20 do 30 ms; dla nieskompresowanego WAV
  cięcie jest co do próbki.

Zamknięcie okna kończy całą aplikację. Przerwana transkrypcja wraca do kolejki przy następnym
starcie. Ponowne uruchomienie przy otwartej aplikacji nie otwiera drugiej kopii, tylko
przywraca istniejące okno.

## Modele

| Model | Uwagi |
|---|---|
| large-v3-turbo | domyślny; na Ryzen 7 8845HS transkrypcja trwa ok. 0,25 długości nagrania |
| small | kilka razy szybszy, wyraźnie słabszy dla polskiego |
| medium | pośredni |
| large-v3 | najdokładniejszy, kilka razy wolniejszy od turbo |

Modele pobierają się do `models/` przy pierwszym użyciu, a transkrypcja działa na procesorze.
Whisper zapisuje liczby cyframi („10%” zamiast „dziesięć procent”), więc liczb szukaj cyframi.

## Aktualizacje

- Raz na dobę (opcja w oknie „O aplikacji”, domyślnie włączona) aplikacja pyta publiczne API
  GitHuba o wydania w [Mysttic/Mysttic](https://github.com/Mysttic/Mysttic/releases), z których
  korzysta też strona projektu. Bez tokenu i bez danych o użytkowniku czy komputerze.
- Nowszą wersję pobiera wyłącznie spod `github.com/Mysttic/Mysttic/releases/download/`,
  sprawdza rozmiar i sumę SHA-256, rozpakowuje do `data/update/` i czeka.
- Instaluje ją launcher przy następnym uruchomieniu albo od razu przycisk „Uruchom ponownie
  i zainstaluj”. Podmieniane są tylko pliki programu: `data/`, `models/` i `.venv/` zostają.
  Gdy nowa wersja zmienia zależności, launcher sam je doinstaluje.
- Błąd sieci niczego nie psuje; kolejna próba za godzinę.

## Dane i prywatność

- `data/<id>/`: kopia oryginalnej ścieżki dźwiękowej (bez obrazu), podgląd FLAC, przebieg fali
  i transkrypcja. Przesłana kopia pliku jest usuwana po wyciągnięciu dźwięku, oryginał zostaje
  tam, gdzie był. „Usuń z biblioteki” kasuje dane aplikacji dla danego pliku.
- `data/app.log` to dziennik, `data/aktualizacje.json` ustawienia aktualizacji, a `.webview/`
  ustawienia okna (wybrany model i język).
- Z internetem aplikacja łączy się tylko po zależności, modele i informację o wydaniach.

## Dla deweloperów

| Ścieżka | Rola |
|---|---|
| `mysttic-audition.pyw` | launcher: zależności, instalacja aktualizacji, start bez konsoli |
| `app.py` | serwer (FastAPI), dźwięk (ffmpeg, PyAV), transkrypcja, okno (pywebview) |
| `updates.py` | aktualizacje według kontraktu huba, tylko biblioteka standardowa |
| `static/` | interfejs (HTML, CSS, JS, wavesurfer.js w `vendor/`) i ikona |
| `instaluj.bat` | tworzy `.venv` i instaluje `requirements.txt` |
| `tools/pakiet.py` | paczka wydania z plikiem sum |
| `tools/make_icons.py` | ikona z jednego opisu: `brand/icon.svg`, `static/icon.ico`, `static/icon.png` |
| `tests/` | testy aktualizacji i paczki |
| `.github/workflows/` | `testy.yml` i `wydanie.yml` |
| `spike/` | eksperyment: Whisper w przeglądarce (WebGPU) porównany z faster-whisper |

Serwer bez okna pod http://127.0.0.1:8791 (inny port: `AUDITION_PORT`):

```bash
.venv/Scripts/python.exe app.py --server
```

Testy (sama biblioteka standardowa):

```bash
python -m unittest discover -s tests -v
```

Ikona po zmianie opisu w `tools/make_icons.py` (potrzebuje Pillow z `requirements-dev.txt`):

```bash
.venv/Scripts/python.exe tools/make_icons.py
```

### Wydanie nowej wersji

1. Podnieś numer w [VERSION.md](VERSION.md).
2. Dopisz sekcję `## [X.Y.Z] - RRRR-MM-DD` w [CHANGELOG.md](CHANGELOG.md).
3. Scal zmiany do `main`. Workflow [wydanie.yml](.github/workflows/wydanie.yml) uruchomi testy,
   zbuduje paczkę z sumami, opublikuje wydanie `vX.Y.Z` i skopiuje oba pliki do huba jako
   `mysttic-audition-vX.Y.Z`. Od tej chwili widzą je strona projektu i aktualizacja w aplikacji.

Jednorazowo w ustawieniach repozytorium (Settings, Secrets and variables, Actions) potrzebny jest
sekret `HUB_TOKEN`: token osobisty typu fine-grained, właściciel `Mysttic`, dostęp tylko do
`Mysttic/Mysttic`, uprawnienie Contents: Read and write. Kontrakt huba opisuje
[RELEASES.md](https://github.com/Mysttic/Mysttic/blob/master/RELEASES.md).

## Biblioteki zewnętrzne

faster-whisper i CTranslate2 (MIT), modele Whisper (MIT), FastAPI (MIT), Uvicorn
(BSD-3-Clause), pywebview (BSD-3-Clause), wavesurfer.js (BSD-3-Clause, licencja w
`static/vendor/`), PyAV (BSD-3-Clause), NumPy (BSD-3-Clause) oraz imageio-ffmpeg (BSD-2-Clause)
z kompilacją FFmpeg na licencji GPL. FFmpeg instaluje się przez pip i nie jest częścią paczki
wydania.
