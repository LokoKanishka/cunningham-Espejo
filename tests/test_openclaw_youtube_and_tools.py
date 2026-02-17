import os
import sys
import unittest
from unittest.mock import patch


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))


import openclaw_direct_chat as direct_chat  # noqa: E402


class TestOpenClawYoutubeAndTools(unittest.TestCase):
    def test_extract_allowed_tools_from_legacy_dict(self) -> None:
        payload = {
            "tools": {
                "firefox": True,
                "web_search": True,
                "web_ask": True,
                "escritorio": True,
                "modelo": True,
                "streaming": False,
            }
        }
        out = direct_chat._extract_allowed_tools(payload)
        self.assertIn("firefox", out)
        self.assertIn("web_search", out)
        self.assertIn("web_ask", out)
        self.assertIn("desktop", out)
        self.assertIn("model", out)
        self.assertNotIn("escritorio", out)
        self.assertNotIn("modelo", out)

    def test_extract_allowed_tools_from_list(self) -> None:
        payload = {"allowed_tools": ["firefox", "web_search", "desktop", "model"]}
        out = direct_chat._extract_allowed_tools(payload)
        self.assertEqual(out, {"firefox", "web_search", "desktop", "model"})

    @patch("openclaw_direct_chat.shutil.which", return_value=None)
    @patch("openclaw_direct_chat.web_search.searxng_search")
    def test_pick_first_youtube_video_url_skips_results_page(self, mock_search, _mock_which) -> None:
        mock_search.side_effect = [
            {"ok": True, "results": [{"url": "https://www.youtube.com/results?search_query=lofi"}]},
            {"ok": True, "results": []},
        ]
        url, reason = direct_chat._pick_first_youtube_video_url("lofi")
        self.assertIsNone(url)
        self.assertEqual(reason, "no_youtube_video_url")

    @patch("openclaw_direct_chat.shutil.which", return_value=None)
    @patch("openclaw_direct_chat.web_search.searxng_search")
    def test_pick_first_youtube_video_url_uses_wrapped_watch(self, mock_search, _mock_which) -> None:
        wrapped = (
            "https://example.local/redirect?"
            "url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3Dabc123xyz"
        )
        mock_search.side_effect = [
            {"ok": True, "results": [{"url": wrapped}]},
            {"ok": True, "results": []},
        ]
        url, reason = direct_chat._pick_first_youtube_video_url("lofi")
        self.assertEqual(reason, "ok")
        self.assertIsNotNone(url)
        self.assertIn("youtube.com/watch?v=abc123xyz", str(url))
        self.assertIn("autoplay=1", str(url))

    @patch("openclaw_direct_chat._autodetect_dc_anchor_for_current_workspace")
    @patch("openclaw_direct_chat._trusted_dc_anchor_for_current_workspace")
    @patch("openclaw_direct_chat._active_dc_anchor_for_current_workspace")
    def test_anchor_selection_prefers_active(
        self,
        mock_active,
        mock_trusted,
        mock_auto,
    ) -> None:
        mock_active.return_value = ("0xabc", "active_anchor_ok")
        mock_trusted.return_value = ("0xdef", "ok")
        mock_auto.return_value = ("0x123", "auto_anchor_ok")
        wid, status = direct_chat._trusted_or_autodetected_dc_anchor(expected_profile="Profile 1")
        self.assertEqual(wid, "0xabc")
        self.assertEqual(status, "active_anchor_ok")
        mock_trusted.assert_not_called()
        mock_auto.assert_not_called()


if __name__ == "__main__":
    unittest.main()
