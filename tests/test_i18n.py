"""Testy tłumaczeń interfejsu (static/i18n). Tylko biblioteka standardowa: python -m unittest discover -s tests"""
import ast
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
PLURAL_FORMS = {"en": {"one", "other"}, "pl": {"one", "few", "many", "other"}}  # kategorie Intl.PluralRules
POLISH_LETTERS = re.compile("[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")
# Wywołania z kodem błędu w app.py i updates.py oraz nazwy przekazanych szczegółów.
ERROR_CALL = re.compile(r'\b(?:problem|AppError|UpdateError)\("(\w+)"([^)\n]*)')
ERROR_DICT = re.compile(r'\{"code": "(\w+)"([^}\n]*)\}')


def load(language):
    return json.loads((STATIC / "i18n" / f"{language}.json").read_text("utf-8"))


def placeholders(entry):
    texts = entry.values() if isinstance(entry, dict) else [entry]
    return {name for text in texts for name in re.findall(r"\{(\w+)\}", text)}


def literal(source, pattern):
    """Lista z kodu (krotka Pythona albo tablica JS z napisami w apostrofach) jako lista Pythona."""
    match = re.search(pattern, source, re.M)
    return list(ast.literal_eval(match.group(1)))


class DictionaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dictionaries = {language: load(language) for language in PLURAL_FORMS}

    def test_same_keys(self):
        en, pl = self.dictionaries["en"], self.dictionaries["pl"]
        self.assertEqual(sorted(en.keys() - pl.keys()), [], "brak w pl.json")
        self.assertEqual(sorted(pl.keys() - en.keys()), [], "brak w en.json")

    def test_same_placeholders(self):
        en, pl = self.dictionaries["en"], self.dictionaries["pl"]
        for key in en:
            with self.subTest(key=key):
                self.assertEqual(placeholders(en[key]), placeholders(pl[key]))

    def test_plural_forms(self):
        for language, forms in PLURAL_FORMS.items():
            for key, entry in self.dictionaries[language].items():
                with self.subTest(language=language, key=key):
                    if isinstance(entry, dict):
                        self.assertEqual(set(entry), forms)
                        self.assertIn("n", placeholders(entry))
                    else:
                        self.assertIsInstance(entry, str)
                        self.assertTrue(entry.strip())

    def test_english_has_no_polish_text(self):
        for key, entry in self.dictionaries["en"].items():
            with self.subTest(key=key):
                self.assertIsNone(POLISH_LETTERS.search(json.dumps(entry, ensure_ascii=False)))


class UsageTests(unittest.TestCase):
    """Każdy klucz użyty w interfejsie i każdy kod błędu z serwera ma tłumaczenie."""

    @classmethod
    def setUpClass(cls):
        cls.en = load("en")
        cls.html = (STATIC / "index.html").read_text("utf-8")
        cls.app_js = (STATIC / "app.js").read_text("utf-8")
        cls.i18n_js = (STATIC / "i18n.js").read_text("utf-8")
        cls.app_py = (ROOT / "app.py").read_text("utf-8")
        cls.updates_py = (ROOT / "updates.py").read_text("utf-8")

    def assert_known(self, keys):
        self.assertEqual(sorted(set(keys) - self.en.keys()), [])

    def test_keys_in_html(self):
        keys = re.findall(r'data-i18n(?:-title|-placeholder)?="([^"]+)"', self.html)
        self.assertGreater(len(keys), 50)
        self.assert_known(keys)

    def test_keys_in_app_js(self):
        # napisy w apostrofach, które zaczynają się od przestrzeni nazw słownika, np. 'player.play'
        namespaces = {key.split(".")[0] for key in self.en}
        keys = [k for k in re.findall(r"'([a-z]+\.[\w.-]+)'", self.app_js) if k.split(".")[0] in namespaces]
        self.assertGreater(len(keys), 50)
        self.assert_known(keys)

    def test_models_and_languages(self):
        models = literal(self.app_py, r"^MODELS = (\(.*\))$")
        languages = literal(self.app_py, r"^LANGUAGES = (\(.*\))$")
        self.assertEqual(literal(self.app_js, r"^const MODELS = (\[.*\])$"), models)
        self.assertEqual(literal(self.app_js, r"^const LANGUAGES = (\[.*\])$"), languages)
        self.assert_known([f"models.{m}" for m in models] + [f"models.desc.{m}" for m in models]
                          + [f"languages.{code}" for code in languages])

    def test_interface_languages(self):
        server = literal(self.app_py, r"^UI_LANGUAGES = (\(.*?\))")
        interface = [code for code, _ in literal(self.i18n_js, r"^export const UI_LANGUAGES = (\[.*\])  ")]
        self.assertEqual(server, interface)
        self.assertEqual(set(server), set(PLURAL_FORMS))
        # serwer wpisuje język w miejsce lang="en" (app.py, index)
        self.assertIn('<html lang="en"', self.html)
        self.assertIn('''html.replace('<html lang="en"''', self.app_py)

    def test_server_error_codes(self):
        calls = ERROR_CALL.findall(self.app_py) + ERROR_CALL.findall(self.updates_py)
        calls += ERROR_DICT.findall(self.updates_py)
        used = {code for code, _ in calls}
        known = {key.removeprefix("error.") for key in self.en if key.startswith("error.")}
        self.assertGreater(len(used), 30)
        self.assertEqual(sorted(used - known), [], "kody bez tłumaczenia")
        self.assertEqual(sorted(known - used), [], "tłumaczenia nieużywanych kodów")
        for code, args in calls:
            with self.subTest(code=code):
                given = set(re.findall(r'(\w+)=', args)) | set(re.findall(r'"(\w+)":', args))
                self.assertLessEqual(placeholders(self.en[f"error.{code}"]), given)


if __name__ == "__main__":
    unittest.main()
