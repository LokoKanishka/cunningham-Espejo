import os
import sys
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))


from molbot_direct_chat.web_ask import extract_web_ask_request  # noqa: E402


class TestWebAsk(unittest.TestCase):
    def test_extract_preguntale(self) -> None:
        req = extract_web_ask_request("Preguntale a Gemini: que hora es?")
        self.assertIsNotNone(req)
        site, prompt, followups = req  # type: ignore[misc]
        self.assertEqual(site, "gemini")
        self.assertEqual(prompt, "que hora es?")
        self.assertIsNone(followups)

    def test_extract_dialoga(self) -> None:
        req = extract_web_ask_request("Dialoga con ChatGPT: explicame relatividad")
        self.assertIsNotNone(req)
        site, prompt, followups = req  # type: ignore[misc]
        self.assertEqual(site, "chatgpt")
        self.assertEqual(prompt, "explicame relatividad")
        self.assertIsInstance(followups, list)
        self.assertEqual(len(followups), 4)
        self.assertTrue(all(isinstance(x, str) and len(x) > 0 for x in followups))


if __name__ == "__main__":
    unittest.main()
