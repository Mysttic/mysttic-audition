# Historia zmian

Wszystko, co warto wiedzieć o kolejnych wydaniach Mysttic Audition. Format według
[Keep a Changelog](https://keepachangelog.com/pl/1.1.0/), numeracja według
[wersjonowania semantycznego](https://semver.org/lang/pl/).

Numer wydania jest w [VERSION.md](VERSION.md): jego zmiana na gałęzi `main` uruchamia
wydanie. Treść sekcji danej wersji trafia do opisu wydania i do okna aktualizacji
w aplikacji.

## [0.3.0] - 2026-10-28

Okno ustawień zamiast przełączników rozrzuconych po głównym oknie. Główne okno zostaje przy
pracy z nagraniem: otwieranie, biblioteka, odtwarzanie, szukanie i fragmenty.

### Dodane
- **Okno ustawień** (przycisk „Ustawienia” w nagłówku albo Ctrl+,) z sekcjami Transkrypcja,
  Odtwarzanie, Aktualizacje i Dane.
- **Sekcja Dane:** zajętość biblioteki i pobranych modeli oraz przyciski otwierające ich foldery.
- **Lista skrótów klawiszowych** w sekcji Odtwarzanie.
- **Ponowna transkrypcja** pyta o model i język w osobnym okienku, tylko dla tego pliku.

### Zmienione
- Model i język przeniesione z nagłówka do ustawień. Ustawienia zapisują się w
  `data/ustawienia.json`, więc nie zależą od profilu okna ani portu.
- Sprawdzanie aktualizacji przeniesione do ustawień. Znacznik nowej wersji w nagłówku i kropka
  przy sekcji Aktualizacje prowadzą prosto do niej.
- „Przewijaj tekst” przeniesione spod przebiegu fali do ustawień.

### Usunięte
- Okno „O aplikacji”: numer wersji i aktualizacje są w ustawieniach.

## [0.2.0] - 2026-10-28

Aplikacja desktopowa zamiast strony w przeglądarce. Startuje dwuklikiem w jednym pliku,
działa we własnym oknie i kończy się w całości razem z nim. Do tego ikona, numer wersji
i automatyczne aktualizacje z huba wydań Mysttic.

### Dodane
- **Własne okno** (pywebview z Edge WebView2) z ikoną aplikacji na pasku tytułu i pasku zadań.
- **Start dwuklikiem w `mysttic-audition.pyw`**, bez konsoli. Pierwsze uruchomienie i każda
  zmiana `requirements.txt` instalują zależności w widocznym oknie (`instaluj.bat`).
- **Jedna kopia aplikacji:** ponowne uruchomienie przywraca istniejące okno.
- **Eksport przez okno „Zapisz jako”**, domyślnie w folderze Pobrane.
- **Numer wersji** w nagłówku i w oknie „O aplikacji”. Jedynym źródłem jest `VERSION.md`.
- **Aktualizacje:** raz na dobę (opcja do wyłączenia) aplikacja sprawdza publiczne wydania
  w `Mysttic/Mysttic`, pobiera nowszą paczkę, sprawdza jej sumę SHA-256 i instaluje ją przy
  następnym uruchomieniu albo od razu przyciskiem „Uruchom ponownie i zainstaluj”. Dane,
  modele i środowisko Pythona zostają nietknięte.
- **Wydania z GitHub Actions:** paczka zip z sumami, wydanie w repozytorium projektu i kopia
  w hubie `Mysttic/Mysttic`, skąd korzystają strona i aktualizacja w aplikacji.
- Dziennik `data/app.log` i okienko z opisem błędu, gdy start się nie uda.

### Zmienione
- Zamknięcie okna kończy cały proces: serwer, transkrypcję, ffmpeg i pamięć zajętą przez model.
  Procesy potomne są w obiekcie zadania Windows, więc nie przeżywają nawet awarii. Przerwana
  transkrypcja wraca do kolejki przy następnym starcie.
- Port 8791, a gdy jest zajęty, wolny port przydzielony przez system.

### Usunięte
- `uruchom.bat` i otwieranie aplikacji w przeglądarce. Do pracy nad kodem zostaje tryb
  `app.py --server`.

## [0.1.0] - 2026-10-28

Pierwszy prototyp, działający w przeglądarce. Nie był publikowany.

### Dodane
- Wczytywanie plików audio i wideo (MP3, WAV, M4A, FLAC, MP4, MKV, MOV, AVI i inne). Dźwięk
  z wideo jest wyciągany automatycznie przez ffmpeg, bez ręcznej konwersji.
- Lokalna transkrypcja faster-whisper (large-v3-turbo na procesorze) z czasem każdego słowa.
  Tekst pojawia się na bieżąco, a kliknięcie słowa odtwarza nagranie od tego miejsca.
- Przebieg fali z przybliżaniem (wavesurfer.js) i bezstratny podgląd FLAC do odsłuchu.
- Wyszukiwanie słów i fraz, odporne na wielkość liter, polskie znaki i odmianę.
- Fragmenty zaznaczane na fali albo z wyników wyszukiwania, pętla i porównanie A/B klawiszami.
- Eksport fragmentu: WAV co do próbki albo oryginalny kodek bez ponownego kodowania.
- Biblioteka wcześniej otwartych plików.

[0.3.0]: https://github.com/Mysttic/mysttic-audition/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Mysttic/mysttic-audition/releases/tag/v0.2.0
