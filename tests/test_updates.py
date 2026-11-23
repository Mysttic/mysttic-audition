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
# Adresy wpisane wprost: testy pilnują źródła aktualizacji, a nie powtarzają stałych z updates.py.
REPO_API = "https://api.github.com/repos/Mysttic/mysttic-audition/releases?per_page=100"
REPO_DOWNLOADS = "https://github.com/Mysttic/mysttic-audition/releases/download/"
HUB_DOWNLOADS = "https://github.com/Mysttic/Mysttic/releases/download/"  # dawny hub wydań, do 0.4.0


def release(version, *, draft=False, prerelease=False, state="uploaded", tag=None, url_prefix=PREFIX, assets=None):
    tag = tag or f"v{version}"
    names = assets if assets is not None else [updates.package_name(version), updates.checksums_name(version)]
    return {
        "tag_name": tag, "draft": draft, "prerelease": prerelease, "published_at": "2026-10-28T12:00:00Z",
        "body": f"Mysttic Audition {version}",
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
        self.assertEqual(picked["tag"], "v0.10.0")
        self.assertEqual(picked["package"]["url"], f"{REPO_DOWNLOADS}v0.10.0/mysttic-audition-0.10.0-windows.zip")
        self.assertEqual(picked["checksums"]["url"], f"{REPO_DOWNLOADS}v0.10.0/mysttic-audition-0.10.0-checksums.txt")

    def test_ignores_other_tags_drafts_and_prereleases(self):
        releases = [
            release("9.0.0", tag="mysttic-audition-v9.0.0"),  # postać tagu z dawnego huba
            release("9.0.0", tag="v9.0.0-rc1"),
            release("9.0.0", tag="9.0.0"),
            release("9.0.0", tag="V9.0.0"),
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
        hub = release("0.3.0", url_prefix=HUB_DOWNLOADS)
        other_repo = release("0.3.0", url_prefix="https://github.com/Mysttic/mysttic-audition-x/releases/download/")
        for rel in (only_zip, foreign, hub, other_repo):
            with self.subTest(assets=[a["browser_download_url"] for a in rel["assets"]]):
                self.assertIsNone(updates.pick_release([rel], "0.2.0"))

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


class FakeResponse(io.BytesIO):
    """Odpowiedź serwera do podstawienia: treść, adres po przekierowaniach i obsługa `with`."""

    def __init__(self, data, url):
        super().__init__(data)
        self.url = url

    def geturl(self):
        return self.url


class SourceTests(unittest.TestCase):
    """Wydania i pliki tylko z tego repozytorium, bez tokenu, z kontrolą rozmiaru i SHA-256."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.url = f"{REPO_DOWNLOADS}v0.5.0/{updates.package_name('0.5.0')}"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_asks_this_repository_without_token(self):
        with mock.patch.object(updates.urllib.request, "urlopen", return_value=FakeResponse(b"[]", REPO_API)) as urlopen:
            self.assertEqual(updates.fetch_releases("mysttic-audition/0.5.0"), [])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, REPO_API)
        self.assertFalse(request.has_header("Authorization"))

    def test_link_leads_to_releases_of_this_repository(self):
        state = updates.Updater(self.tmp, "0.5.0", log=lambda *_: None).snapshot()
        self.assertEqual(state["site"], "https://github.com/Mysttic/mysttic-audition/releases")

    def test_downloads_only_from_this_repository(self):
        name = updates.package_name("0.5.0")
        for url in (f"{HUB_DOWNLOADS}mysttic-audition-v0.5.0/{name}",
                    f"https://github.com/Mysttic/mysttic-audition-x/releases/download/v0.5.0/{name}",
                    f"http://github.com/Mysttic/mysttic-audition/releases/download/v0.5.0/{name}",
                    "https://github.com/Mysttic/mysttic-audition/archive/refs/tags/v0.5.0.zip"):
            with self.subTest(url=url):
                with mock.patch.object(updates._download_opener, "open", side_effect=AssertionError("bez sieci")), \
                        self.assertRaises(updates.UpdateError) as caught:
                    updates.download(url, self.tmp / name, "mysttic-audition/0.5.0")
                self.assertEqual(caught.exception.problem, {"code": "update_bad_url", "repo": "Mysttic/mysttic-audition"})
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_download_checks_size_and_returns_sha256(self):
        data = b"paczka" * 50_000
        target = self.tmp / "paczka.zip"
        landed = "https://release-assets.githubusercontent.com/github-production-release-asset/1"
        with mock.patch.object(updates._download_opener, "open", return_value=FakeResponse(data, landed)) as opener:
            digest = updates.download(self.url, target, "mysttic-audition/0.5.0", len(data))
        self.assertEqual(opener.call_args.args[0].full_url, self.url)
        self.assertEqual(digest, hashlib.sha256(data).hexdigest())
        self.assertEqual(target.read_bytes(), data)
        target.unlink()
        with mock.patch.object(updates._download_opener, "open", return_value=FakeResponse(data, landed)), \
                self.assertRaises(updates.UpdateError) as caught:
            updates.download(self.url, target, "mysttic-audition/0.5.0", len(data) + 1)
        self.assertEqual(caught.exception.problem, {"code": "update_size_mismatch", "received": len(data),
                                                    "expected": len(data) + 1})
        self.assertEqual(list(self.tmp.iterdir()), [])  # ani paczki, ani pliku .part

    def test_download_refuses_redirect_outside_github(self):
        with mock.patch.object(updates._download_opener, "open", return_value=FakeResponse(b"x", "https://example.com/x")), \
                self.assertRaises(updates.UpdateError) as caught:
            updates.download(self.url, self.tmp / "paczka.zip", "mysttic-audition/0.5.0")
        self.assertEqual(caught.exception.problem["code"], "update_foreign_host")
        self.assertEqual(list(self.tmp.iterdir()), [])


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
