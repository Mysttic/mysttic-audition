# Version

0.4.0

---

This is the release number, and changing it is what triggers a release: the
[`.github/workflows/wydanie.yml`](.github/workflows/wydanie.yml) workflow runs only when this
file is among the changes that reach the `main` branch.

The number has the form `major.minor.patch`. The app and the workflow read the first line that
consists of such a number alone, so the rest of the file can say anything.

This is the only place with the version number. The app reads it at startup (the header,
Settings, comparing with releases when checking for updates), and the release package includes
this file, so after an update the app knows its new number.

When you raise the number, add a `## [X.Y.Z] - YYYY-MM-DD` section to
[CHANGELOG.md](CHANGELOG.md). Without it the release is not built, and its content becomes the
release description and the update notes shown in the app.
