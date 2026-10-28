# Changelog

Everything worth knowing about each Mysttic Audition release. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and version numbers follow
[Semantic Versioning](https://semver.org/).

The release number is in [VERSION.md](VERSION.md): changing it on the `main` branch triggers a
release. The section for a version becomes the release description and the update notes shown
in the app.

## [0.4.0] - 2026-10-28

The interface is in English by default, with Polish to choose in Settings, and the language of
each recording is chosen before its transcription, independently of the interface language. The
documentation is in English too, with a Polish translation of the README.

### Added
- **Recording language chosen for each file.** Opening or dropping a file shows a dialog where
  you choose the language spoken in the recording and the model; only then is the file sent for
  transcription. "Transcribe again" uses the same dialog, with the file's last choice
  preselected.
- **Interface language** in a new General section of Settings: English or Polish. The change
  applies at once, without a restart, and is saved in `data/ustawienia.json`.
- **README.pl.md**, the Polish translation of the README.

### Changed
- **English by default.** After updating from 0.3.0 the interface is in English; Polish is in
  Settings, General section.
- The Transcription section of Settings holds only the defaults preselected in the new dialog.
  The default recording language is now "Detect automatically"; a language you have already
  chosen in Settings stays.
- Messages from the app (errors, statuses, dates, numbers and file sizes) follow the interface
  language. Error messages saved by earlier versions stay as they were.
- Messages shown outside the window (a failed start, a failed update installation) follow the
  interface language, and the console that installs the dependencies is in English.
- The changelog, the version file and the rest of the documentation are in English.

## [0.3.0] - 2026-10-28

A Settings window instead of switches scattered around the main window. The main window is left
for working with a recording: opening, the library, playback, search and fragments.

### Added
- **Settings window** (the "Settings" button in the header, or Ctrl+,) with Transcription,
  Playback, Updates and Data sections.
- **Data section:** the space taken by the library and the downloaded models, and buttons that
  open their folders.
- **List of keyboard shortcuts** in the Playback section.
- **Transcribe again** asks for the model and language in a small dialog, for that file only.

### Changed
- Model and language moved from the header to Settings. Settings are saved in
  `data/ustawienia.json`, so they don't depend on the window profile or the port.
- Update checking moved to Settings. The new version badge in the header and the dot next to
  the Updates section lead straight to it.
- "Scroll text" moved from under the waveform to Settings.

### Removed
- The "About" window: the version number and updates are in Settings.

## [0.2.0] - 2026-10-28

A desktop app instead of a page in the browser. It starts with a double-click on a single file,
runs in its own window and ends completely together with it. Plus an icon, a version number and
automatic updates from the Mysttic release hub.

### Added
- **Its own window** (pywebview with Edge WebView2) with the app icon in the title bar and on
  the taskbar.
- **Start by double-clicking `mysttic-audition.pyw`**, without a console. The first start and
  every change to `requirements.txt` install the dependencies in a visible window
  (`instaluj.bat`).
- **A single instance:** starting the app again brings the existing window back.
- **Export through the "Save As" dialog**, in the Downloads folder by default.
- **Version number** in the header and in the "About" window. Its only source is `VERSION.md`.
- **Updates:** once a day (an option you can turn off) the app checks the public releases in
  `Mysttic/Mysttic`, downloads a newer package, verifies its SHA-256 checksum and installs it at
  the next start, or right away with the "Restart and install" button. Data, models and the
  Python environment stay untouched.
- **Releases from GitHub Actions:** a zip package with checksums, a release in the project
  repository and a copy in the `Mysttic/Mysttic` hub, which the project page and the update
  check in the app use.
- The `data/app.log` log and a message box describing the error when the start fails.

### Changed
- Closing the window ends the whole process: the server, transcription, ffmpeg and the memory
  used by the model. Child processes are in a Windows job object, so they don't outlive even a
  crash. An interrupted transcription goes back to the queue at the next start.
- Port 8791, or a free port assigned by the system when it is taken.

### Removed
- `uruchom.bat` and opening the app in the browser. For working on the code there is the
  `app.py --server` mode.

## [0.1.0] - 2026-10-28

The first prototype, running in the browser. It was not published.

### Added
- Loading audio and video files (MP3, WAV, M4A, FLAC, MP4, MKV, MOV, AVI and more). The audio of
  a video is extracted automatically with ffmpeg, without manual conversion.
- Local faster-whisper transcription (large-v3-turbo on the CPU) with the timing of every word.
  Text appears as it is recognised, and clicking a word plays the recording from there.
- A zoomable waveform (wavesurfer.js) and a lossless FLAC preview for listening.
- Word and phrase search, insensitive to case, Polish characters and word forms.
- Fragments marked on the waveform or from search results, a loop and A/B comparison with keys.
- Fragment export: WAV exact to the sample, or the original codec without re-encoding.
- A library of previously opened files.

[0.4.0]: https://github.com/Mysttic/mysttic-audition/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Mysttic/mysttic-audition/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Mysttic/mysttic-audition/releases/tag/v0.2.0
