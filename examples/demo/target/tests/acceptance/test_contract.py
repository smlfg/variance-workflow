"""Shared acceptance tests: every variant must pass these. Variants under test: VW_VARIANT (comma list) or all."""
import os
import re
import unittest

from textkit.slugify import available

SAMPLES = ["Hello World", "Äpfel & Birnen", "Straße 12", "C'est déjà l'été", "foo--bar__baz",
           "x" * 300, "a " * 100, "東京 2026", "user@example.com", "Rock 'n' Roll", "50% off!!!",
           "  leading and trailing  ", "MiXeD CaSe", "tab\tand\nnewline"]
EMPTY = ["", "   ", "!!!", "--", "\t\n", "&&&"]


def ids():
    env = [i for i in os.environ.get("VW_VARIANT", "").split(",") if i]
    return env or sorted(available())


class Contract(unittest.TestCase):
    def setUp(self):
        self.mods = available()

    def test_variants_exist(self):
        for vid in ids():
            with self.subTest(variant=vid):
                self.assertIn(vid, self.mods, f"variant {vid} not found; have {sorted(self.mods)}")
                meta = getattr(self.mods[vid], "VARIANT", None)
                self.assertIsInstance(meta, dict)
                self.assertTrue(meta.get("summary"))

    def test_shape(self):
        for vid in ids():
            f = self.mods[vid].slugify
            for s in SAMPLES:
                with self.subTest(variant=vid, text=s[:20]):
                    out = f(s)
                    self.assertIsInstance(out, str)
                    self.assertEqual(out, out.lower())
                    self.assertFalse(re.search(r"\s", out), out)
                    self.assertFalse(out.startswith("-") or out.endswith("-"), out)
                    self.assertNotIn("--", out)
                    self.assertLessEqual(len(out), 80)

    def test_idempotent_and_deterministic(self):
        for vid in ids():
            f = self.mods[vid].slugify
            for s in SAMPLES:
                with self.subTest(variant=vid, text=s[:20]):
                    self.assertEqual(f(s), f(s))
                    self.assertEqual(f(f(s)), f(s))

    def test_empty(self):
        for vid in ids():
            for s in EMPTY:
                with self.subTest(variant=vid, text=s):
                    self.assertEqual(self.mods[vid].slugify(s), "")

    def test_ascii_words_survive(self):
        for vid in ids():
            with self.subTest(variant=vid):
                out = self.mods[vid].slugify("Hello World")
                self.assertIn("hello", out)
                self.assertIn("world", out)


if __name__ == "__main__":
    unittest.main()
