import os
import sys
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))


from molbot_direct_chat.util import extract_url, normalize_text, parse_json_object, safe_session_id  # noqa: E402


class TestUtil(unittest.TestCase):
    def test_extract_url(self) -> None:
        self.assertEqual(extract_url("mira https://example.com/ hola"), "https://example.com/")
        self.assertIsNone(extract_url("sin url"))

    def test_normalize_text(self) -> None:
        self.assertEqual(normalize_text("  Hólá   Díegó "), "hola diego")

    def test_safe_session_id(self) -> None:
        self.assertEqual(safe_session_id("a b$c"), "abc")
        self.assertEqual(safe_session_id(""), "default")

    def test_parse_json_object(self) -> None:
        self.assertEqual(parse_json_object('{"ok": true}'), {"ok": True})
        self.assertEqual(parse_json_object("xx {\"a\": 1} yy"), {"a": 1})
        self.assertIsNone(parse_json_object("[]"))


if __name__ == "__main__":
    unittest.main()

