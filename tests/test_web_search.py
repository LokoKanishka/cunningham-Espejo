import os
import sys
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))


import molbot_direct_chat.web_search as web_search  # noqa: E402


class TestWebSearch(unittest.TestCase):
    def test_extract_web_search_request_internet(self) -> None:
        req = web_search.extract_web_search_request("busca en internet: teoria de cuerdas")
        self.assertIsNotNone(req)
        q, site = req  # type: ignore[misc]
        self.assertEqual(q, "teoria de cuerdas")
        self.assertIsNone(site)

    def test_extract_web_search_request_youtube_topic_before_site(self) -> None:
        req = web_search.extract_web_search_request("busca tutorial de docker en youtube")
        self.assertIsNotNone(req)
        q, site = req  # type: ignore[misc]
        self.assertEqual(q, "tutorial de docker")
        self.assertEqual(site, "youtube")

    def test_extract_web_search_request_youtube_site_before_topic(self) -> None:
        req = web_search.extract_web_search_request("busca en youtube: tutorial docker compose")
        self.assertIsNotNone(req)
        q, site = req  # type: ignore[misc]
        self.assertEqual(q, "tutorial docker compose")
        self.assertEqual(site, "youtube")


if __name__ == "__main__":
    unittest.main()
