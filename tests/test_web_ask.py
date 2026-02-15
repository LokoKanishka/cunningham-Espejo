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
        site, prompt, followup, followup2 = req  # type: ignore[misc]
        self.assertEqual(site, "gemini")
        self.assertEqual(prompt, "que hora es?")
        self.assertIsNone(followup)
        self.assertIsNone(followup2)

    def test_extract_dialoga(self) -> None:
        req = extract_web_ask_request("Dialoga con ChatGPT: explicame relatividad")
        self.assertIsNotNone(req)
        site, prompt, followup, followup2 = req  # type: ignore[misc]
        self.assertEqual(site, "chatgpt")
        self.assertEqual(prompt, "explicame relatividad")
        self.assertIsInstance(followup, str)
        self.assertTrue(len(followup) > 0)
        self.assertIsInstance(followup2, str)
        self.assertTrue(len(followup2) > 0)


if __name__ == "__main__":
    unittest.main()
