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

    def test_extract_web_search_request_en_youtube_busca_with_accent(self) -> None:
        req = web_search.extract_web_search_request("en youtube buscá musica focus y abrí un video")
        self.assertIsNotNone(req)
        q, site = req  # type: ignore[misc]
        self.assertEqual(q, "musica focus y abrí un video")
        self.assertEqual(site, "youtube")

    def test_extract_web_search_request_youtube_busca_without_en(self) -> None:
        req = web_search.extract_web_search_request("youtube busca tutorial playwright")
        self.assertIsNotNone(req)
        q, site = req  # type: ignore[misc]
        self.assertEqual(q, "tutorial playwright")
        self.assertEqual(site, "youtube")

    def test_extract_web_search_request_en_la_web(self) -> None:
        req = web_search.extract_web_search_request("cunn: busca en la web The Wall de Pink Floyd")
        self.assertIsNotNone(req)
        q, site = req  # type: ignore[misc]
        self.assertEqual(q, "The Wall de Pink Floyd")
        self.assertIsNone(site)

    def test_extract_web_search_query_en_la_web(self) -> None:
        q = web_search.extract_web_search_query("busca en la web: historia del album the wall")
        self.assertEqual(q, "historia del album the wall")


if __name__ == "__main__":
    unittest.main()
