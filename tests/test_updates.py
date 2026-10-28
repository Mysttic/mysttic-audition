"""Testy modułu aktualizacji. Tylko biblioteka standardowa: python -m unittest discover -s tests"""
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import updates  # noqa: E402

PREFIX = updates.DOWNLOAD_PREFIX


def release(version, *, draft=False, prerelease=False, state="uploaded", tag=None, url_prefix=PREFIX, assets=None):
    tag = tag or f"mysttic-audition-v{version}"
    names = assets if assets is not None else [updates.package_name(version), updates.checksums_name(version)]
    return {
        "tag_name": tag, "draft": draft, "prerelease": prerelease, "published_at": "2026-10-28T12:00:00Z",
        "body": f"Mysttic Audition {version}\n\n{updates.SITE}",
        "assets": [{"name": n, "state": state, "size": 10, "browser_download_url": f"{url_prefix}{tag}/{n}"}
                   for n in names],
    }


def make_package(version, extra=None):
    """Paczka jak z tools/pakiet.py: katalog mysttic-audition/ z minimum plików."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mysttic-audition/VERSION.md", f"# Wersja\n\n{version}\n")
        archive.writestr("mysttic-audition/app.py", "print('app')\n")
        archive.writestr("mysttic-audition/mysttic-audition.pyw", "print('start')\n")
        archive.writestr("mysttic-audition/CHANGELOG.md", f"# Historia\n\n## [{version}] - 2026-10-29\n\n### Dodane\n- Nowość.\n\n## [0.2.0] - 2026-10-28\n\nStare.\n")
        archive.writestr("mysttic-audition/static/app.js", "// ui\n")
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return buffer.getvalue()


class VersionTests(unittest.TestCase):
    def test_read_version_takes_first_bare_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "VERSION.md"
            path.write_text("# Wersja\n\nnie 1.2\n0.3.1\n\n9.9.9\n", "utf-8")
            self.assertEqual(updates.read_version(path), "0.3.1")
            self.assertEqual(updates.read_version(Path(tmp) / "brak.md"), "0.0.0")

    def test_versions_compare_numerically(self):
        self.assertGreater(updates.parse_version("0.10.0"), updates.parse_version("0.9.9"))
        self.assertEqual(updates.parse_version("1.2.3"), (1, 2, 3))


class PickReleaseTests(unittest.TestCase):
    def test_takes_highest_version_not_first(self):
        picked = updates.pick_release([release("0.3.0"), release("0.10.0"), release("0.4.0")], "0.2.0")
        self.assertEqual(picked["version"], "0.10.0")
        self.assertEqual(picked["package"]["url"], f"{PREFIX}mysttic-audition-v0.10.0/mysttic-audition-0.10.0-windows.zip")

    def test_ignores_other_projects_drafts_and_suffixes(self):
        releases = [
            release("9.0.0", tag="chatt-v9.0.0"),
            release("9.0.0", tag="mysttic-audition-viewer-v9.0.0"),
            release("9.0.0", tag="mysttic-audition-v9.0.0-rc1"),
            release("8.0.0", draft=True),
            release("7.0.0", prerelease=True),
        ]
        self.assertIsNone(updates.pick_release(releases, "0.2.0"))

    def test_no_update_when_not_newer(self):
        self.assertIsNone(updates.pick_release([release("0.2.0"), release("0.1.0")], "0.2.0"))

    def test_highest_release_still_uploading_means_no_update_yet(self):
        releases = [release("0.4.0", state="starter"), release("0.3.0")]
        self.assertIsNone(updates.pick_release(releases, "0.2.0"))

    def test_missing_checksums_or_foreign_url_means_no_update(self):
        only_zip = release("0.3.0", assets=[updates.package_name("0.3.0")])
        foreign = release("0.3.0", url_prefix="https://example.com/download/")
        self.assertIsNone(updates.pick_release([only_zip], "0.2.0"))
        self.assertIsNone(updates.pick_release([foreign], "0.2.0"))

    def test_garbage_response(self):
        self.assertIsNone(updates.pick_release({"message": "rate limited"}, "0.2.0"))
        self.assertIsNone(updates.pick_release([None, 5, {"tag_name": None}], "0.2.0"))


class HelperTests(unittest.TestCase):
    def test_parse_checksums(self):
        digest = "a" * 64
        sums = updates.parse_checksums(f"{digest}  mysttic-audition-0.3.0-windows.zip\n{'B' * 64} *inny.txt\nśmieci\n")
        self.assertEqual(sums, {"mysttic-audition-0.3.0-windows.zip": digest, "inny.txt": "b" * 64})

    def test_download_hosts(self):
        updates.check_download_url("https://release-assets.githubusercontent.com/x")
        for url in ("http://github.com/x", "https://github.com.evil.example/x", "https://example.com/x"):
            with self.assertRaises(updates.UpdateError):
                updates.check_download_url(url)

    def test_changelog_section(self):
        text = "# H\n\n## [0.3.0] - 2026-10-29\n\nOpis.\n\n### Dodane\n- A\n\n## [0.2.0] - 2026-10-28\n\nB\n\n[0.3.0]: https://x\n"
        self.assertEqual(updates.changelog_section(text, "0.3.0"), "Opis.\n\n### Dodane\n- A")
        self.assertEqual(updates.changelog_section(text, "0.2.0"), "B")
        self.assertEqual(updates.changelog_section(text, "9.9.9"), "")


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def package(self, data):
        path = self.tmp / "paczka.zip"
        path.write_bytes(data)
        return path

    def test_extracts_files_without_top_directory(self):
        updates.extract_package(self.package(make_package("0.3.0")), self.tmp / "pliki", "0.3.0")
        self.assertEqual((self.tmp / "pliki" / "static" / "app.js").read_text(), "// ui\n")
        self.assertEqual(updates.read_version(self.tmp / "pliki" / "VERSION.md"), "0.3.0")

    def test_rejects_wrong_version(self):
        with self.assertRaises(updates.UpdateError):
            updates.extract_package(self.package(make_package("0.3.0")), self.tmp / "pliki", "0.4.0")

    def test_rejects_paths_outside_and_into_local_data(self):
        for evil in ("mysttic-audition/../poza.txt", "/abs.txt", "inny-katalog/app.py",
                     "mysttic-audition/data/meta.json", "mysttic-audition/.venv/x.py", "C:/x.txt"):
            with self.subTest(evil=evil), self.assertRaises(updates.UpdateError):
                updates.extract_package(self.package(make_package("0.3.0", {evil: "x"})), self.tmp / "pliki", "0.3.0")
        self.assertFalse((self.tmp / "poza.txt").exists())


class UpdaterTests(unittest.TestCase):
    """Cały przebieg: sprawdzenie, pobranie, weryfikacja, rozpakowanie, bez sieci."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.package = make_package("0.3.0")
        self.sums = f"{hashlib.sha256(self.package).hexdigest()}  mysttic-audition-0.3.0-windows.zip\n".encode()
        rel = release("0.3.0")
        for asset in rel["assets"]:
            asset["size"] = len(self.package) if asset["name"].endswith(".zip") else len(self.sums)
        self.releases = [rel, release("0.1.0")]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake_download(self, url, target, user_agent, expected_size=None, progress=None):
        data = self.package if url.endswith(".zip") else self.sums
        target.write_bytes(data)
        if progress:
            progress(len(data), expected_size)
        return hashlib.sha256(data).hexdigest()

    def test_check_download_and_stage(self):
        updater = updates.Updater(self.tmp, "0.2.0", log=lambda *_: None)
        with mock.patch.object(updates, "fetch_releases", return_value=self.releases), \
                mock.patch.object(updates, "download", side_effect=self.fake_download):
            self.assertEqual(updater.check()["status"], "available")
            updater.download()
        state = updater.snapshot()
        self.assertEqual(state["status"], "ready", state["error"])
        self.assertIn("Nowość", state["release"]["notes"])
        self.assertTrue((self.tmp / "update" / "pliki" / "app.py").is_file())
        staged = json.loads((self.tmp / "update" / "gotowe.json").read_text("utf-8"))
        self.assertEqual(staged["version"], "0.3.0")
        # następny start w starej wersji widzi gotową paczkę
        self.assertEqual(updates.Updater(self.tmp, "0.2.0", log=lambda *_: None).snapshot()["status"], "ready")

    def test_bad_checksum_leaves_nothing(self):
        self.sums = f"{'0' * 64}  mysttic-audition-0.3.0-windows.zip\n".encode()
        updater = updates.Updater(self.tmp, "0.2.0", log=lambda *_: None)
        with mock.patch.object(updates, "fetch_releases", return_value=self.releases), \
                mock.patch.object(updates, "download", side_effect=self.fake_download):
            updater.check()
            updater.download()
        state = updater.snapshot()
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["error"], {"code": "update_checksum_mismatch"})
        self.assertFalse((self.tmp / "update").exists())

    def test_network_failure_is_quiet(self):
        updater = updates.Updater(self.tmp, "0.2.0", log=lambda *_: None)
        with mock.patch.object(updates, "fetch_releases", side_effect=OSError("brak sieci")):
            state = updater.check()
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["last_check"], None)

    def test_stale_staging_is_removed_and_update_is_reported(self):
        (self.tmp / "update").mkdir()
        (self.tmp / "update" / "gotowe.json").write_text(json.dumps({"version": "0.3.0"}), "utf-8")
        (self.tmp / "aktualizacje.json").write_text(json.dumps({"auto": False, "last_version": "0.2.0"}), "utf-8")
        updater = updates.Updater(self.tmp, "0.3.0", log=lambda *_: None)
        state = updater.snapshot()
        self.assertEqual(state["status"], "idle")
        self.assertEqual(state["updated_from"], "0.2.0")
        self.assertFalse(state["auto"])
        self.assertFalse((self.tmp / "update").exists())


if __name__ == "__main__":
    unittest.main()
