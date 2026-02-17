import os
import sys
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))


import openclaw_direct_chat as direct_chat  # noqa: E402


class TestGeminiWriteParser(unittest.TestCase):
    def test_extract_with_quotes(self) -> None:
        msg = 'cunn: en gemini escribí "Hola gemini" y da enter'
        out = direct_chat._extract_gemini_write_request(msg)
        self.assertEqual(out, "Hola gemini")

    def test_extract_last_write_verb(self) -> None:
        msg = "decile a cunn que abra gemini y escriba hola gemini"
        out = direct_chat._extract_gemini_write_request(msg)
        self.assertEqual(out, "hola gemini")

    def test_extract_none_without_gemini(self) -> None:
        msg = "escribi hola mundo y da enter"
        out = direct_chat._extract_gemini_write_request(msg)
        self.assertIsNone(out)

    def test_extract_escribile_chat_phrase(self) -> None:
        msg = "ahora en el chat escribile hola gemini"
        out = direct_chat._extract_gemini_write_request(msg)
        self.assertEqual(out, "hola gemini")


if __name__ == "__main__":
    unittest.main()
