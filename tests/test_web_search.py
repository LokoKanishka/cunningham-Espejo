import os
import sys
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))


from molbot_direct_chat import web_search  # noqa: E402


class TestWebSearchExtraction(unittest.TestCase):
    def test_extract_web_search_query_explicit_internet(self) -> None:
        q = web_search.extract_web_search_query("busca en internet: tension iran estados unidos")
        self.assertEqual(q, "tension iran estados unidos")

    def test_extract_web_search_query_news_phrase(self) -> None:
        q = web_search.extract_web_search_query("podes contarme noticias del conflicto de iran y estados unidos?")
        self.assertEqual(q, "conflicto de iran y estados unidos")

    def test_extract_web_search_query_news_topic(self) -> None:
        q = web_search.extract_web_search_query("noticias sobre inflacion en argentina")
        self.assertEqual(q, "inflacion en argentina")

    def test_extract_web_search_query_timing_plus_conflict_fragment(self) -> None:
        q = web_search.extract_web_search_query("hoy de el conflicto entre irán y esto")
        self.assertEqual(q, "el conflicto entre irán y esto")


if __name__ == "__main__":
    unittest.main()
