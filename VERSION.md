# Wersja

0.3.0

---

Tu jest numer wydania i to jego zmiana uruchamia wydanie: workflow
[`.github/workflows/wydanie.yml`](.github/workflows/wydanie.yml) startuje tylko wtedy,
gdy ten plik był wśród zmian, które trafiły na gałąź `main`.

Numer ma postać `major.minor.patch`. Aplikacja i workflow czytają pierwszą linię złożoną
wyłącznie z takiego numeru, więc reszta pliku może być dowolna.

To jedyne miejsce z numerem wersji. Aplikacja czyta go przy starcie (nagłówek, okno
„O aplikacji”, porównanie z wydaniami przy sprawdzaniu aktualizacji), a paczka wydania
zawiera ten plik, więc po aktualizacji aplikacja zna swój nowy numer.

Podnosząc numer, dopisz sekcję `## [X.Y.Z] - RRRR-MM-DD` w [CHANGELOG.md](CHANGELOG.md).
Bez niej wydanie się nie zbuduje, a jej treść trafia do opisu wydania i do okna
aktualizacji w aplikacji.
