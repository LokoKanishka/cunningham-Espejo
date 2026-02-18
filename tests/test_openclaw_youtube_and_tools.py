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

    def test_extract_youtube_transport_request_pause_and_close(self) -> None:
        req = direct_chat._extract_youtube_transport_request(
            "en youtube detené el video actual y cerrá la ventana"
        )
        self.assertEqual(req, ("pause", True))

    def test_extract_youtube_transport_request_ignores_search_play_open(self) -> None:
        req = direct_chat._extract_youtube_transport_request(
            "en youtube buscá musica focus y reproducí el primer video"
        )
        self.assertIsNone(req)

    @patch("openclaw_direct_chat._youtube_transport_action")
    @patch("openclaw_direct_chat._guardrail_check")
    def test_local_action_routes_youtube_pause(
        self,
        mock_guardrail,
        mock_transport,
    ) -> None:
        mock_guardrail.return_value = (True, "GUARDRAIL_OK")
        mock_transport.return_value = (True, "ok action=pause")
        out = direct_chat._maybe_handle_local_action(
            "en youtube pausá el video",
            {"firefox", "web_search", "desktop", "model"},
            "sess_test",
        )
        self.assertIsNotNone(out)
        self.assertIn("paus", str(out.get("reply", "")).lower())
        mock_transport.assert_called_once_with("pause", close_window=False, session_id="sess_test")

    def test_local_action_youtube_pause_requires_firefox_tool(self) -> None:
        out = direct_chat._maybe_handle_local_action(
            "en youtube pausá el video",
            {"web_search", "desktop", "model"},
            "sess_test",
        )
        self.assertIsNotNone(out)
        self.assertIn("firefox", str(out.get("reply", "")).lower())

    @patch("openclaw_direct_chat._window_matches_profile", return_value=True)
    @patch("openclaw_direct_chat._wmctrl_windows_for_desktop")
    @patch("openclaw_direct_chat._xdotool_active_window")
    def test_fallback_profiled_chrome_anchor_prefers_active_window(
        self,
        mock_active,
        mock_windows,
        _mock_profile,
    ) -> None:
        mock_active.return_value = "0xabc"
        mock_windows.return_value = [
            ("0x111", "100", "Google Chrome"),
            ("0xabc", "101", "YouTube - Google Chrome"),
        ]
        wid, status = direct_chat._fallback_profiled_chrome_anchor_for_workspace(0, "Profile 1")
        self.assertEqual(wid, "0xabc")
        self.assertEqual(status, "fallback_active_profiled_chrome")

    @patch.dict(os.environ, {"DIRECT_CHAT_CHROME_USER_DATA_DIR": "/tmp/direct_chat_chrome_ud_test"}, clear=False)
    @patch("openclaw_direct_chat.subprocess.Popen")
    @patch("openclaw_direct_chat._find_new_profiled_chrome_window", return_value=("0xabc", 1))
    @patch("openclaw_direct_chat._wmctrl_list", return_value={})
    @patch("openclaw_direct_chat._chrome_command", return_value="/usr/bin/google-chrome")
    def test_spawn_profiled_chrome_uses_user_data_dir_override(
        self,
        _mock_cmd,
        _mock_list,
        _mock_find,
        mock_popen,
    ) -> None:
        wid, status = direct_chat._spawn_profiled_chrome_anchor_for_workspace(1, "Profile 1")
        self.assertEqual(wid, "0xabc")
        self.assertEqual(status, "spawn_profiled_chrome_ok")
        argv = [str(x) for x in (mock_popen.call_args.args[0] if mock_popen.call_args else [])]
        self.assertIn("--user-data-dir=/tmp/direct_chat_chrome_ud_test", argv)

    @patch.dict(os.environ, {"DIRECT_CHAT_WORKSPACE_ID": "2", "DIRECT_CHAT_ISOLATED_WORKSPACE": "1"}, clear=False)
    @patch("openclaw_direct_chat._wmctrl_active_desktop", return_value=0)
    def test_wmctrl_current_desktop_ignores_forced_workspace_env(self, _mock_active) -> None:
        self.assertEqual(direct_chat._wmctrl_current_desktop(), 0)

    @patch("openclaw_direct_chat._wmctrl_active_desktop", return_value=2)
    def test_local_action_set_isolated_workspace_is_ignored(self, _mock_active) -> None:
        out = direct_chat._maybe_handle_local_action(
            "fijá workspace aislado",
            {"firefox", "web_search", "desktop", "model"},
            "sess_test",
        )
        self.assertIsNone(out)

    @patch.dict(os.environ, {"DIRECT_CHAT_ISOLATED_WORKSPACE": "1"}, clear=False)
    @patch("openclaw_direct_chat.web_ask.extract_web_ask_request", return_value=("chatgpt", "hora en madrid", []))
    @patch("openclaw_direct_chat.web_ask.run_web_ask", return_value={"status": "ok", "answer": "12:00"})
    @patch("openclaw_direct_chat.web_ask.format_web_ask_reply", return_value="ok")
    def test_web_ask_not_blocked_in_isolated_workspace_mode(self, _mock_fmt, _mock_run, _mock_web_req) -> None:
        out = direct_chat._maybe_handle_local_action(
            "preguntale a chatgpt que hora es en madrid",
            {"firefox", "web_search", "web_ask", "desktop", "model"},
            "sess_test",
        )
        self.assertIsNotNone(out)
        self.assertEqual(str(out.get("reply", "")), "ok")

    @patch("openclaw_direct_chat._spawn_profiled_chrome_anchor_for_workspace", return_value=(None, "spawn_none"))
    @patch("openclaw_direct_chat._fallback_profiled_chrome_anchor_for_workspace", return_value=(None, "fallback_none"))
    @patch("openclaw_direct_chat._trusted_or_autodetected_dc_anchor", return_value=(None, "anchor_none"))
    @patch("openclaw_direct_chat._wmctrl_windows_for_desktop", return_value=[])
    @patch("openclaw_direct_chat._wmctrl_current_desktop", return_value=1)
    def test_open_url_with_context_spawns_when_no_anchor(
        self,
        _mock_desktop,
        _mock_windows,
        _mock_anchor,
        _mock_fallback,
        mock_spawn,
    ) -> None:
        with patch("openclaw_direct_chat._load_browser_profile_config", return_value={"_default": {"browser": "chrome", "profile": "diego"}}):
            err = direct_chat._open_url_with_site_context("https://www.youtube.com/", "youtube", session_id="sess")
        self.assertIsInstance(err, str)
        self.assertIn("no abrí nada", err.lower())
        mock_spawn.assert_called_once()

    @patch("openclaw_direct_chat._load_browser_profile_config", return_value={"_default": {"browser": "chrome", "profile": "diego"}})
    @patch("openclaw_direct_chat._expected_profile_directory_for_site", return_value="Profile 1")
    @patch("openclaw_direct_chat._wmctrl_current_desktop", return_value=1)
    @patch("openclaw_direct_chat._wmctrl_windows_for_desktop", return_value=[])
    @patch("openclaw_direct_chat._trusted_or_autodetected_dc_anchor", return_value=(None, "anchor_none"))
    @patch("openclaw_direct_chat._fallback_profiled_chrome_anchor_for_workspace", return_value=("0xabc", "fallback_ok"))
    @patch("openclaw_direct_chat._xdotool_command", return_value=(0, "ok"))
    @patch("openclaw_direct_chat._wait_window_title_contains", return_value=(True, "YouTube - Google Chrome"))
    @patch("openclaw_direct_chat._wmctrl_list", return_value={"0xabc": "YouTube - Google Chrome"})
    @patch("openclaw_direct_chat._wmctrl_active_desktop", return_value=1)
    def test_open_url_with_context_activates_target_window(
        self,
        _mock_active_desk,
        _mock_wmctrl_list,
        _mock_wait_title,
        mock_xdotool,
        _mock_fallback,
        _mock_anchor,
        _mock_windows,
        _mock_desktop,
        _mock_profile,
        _mock_cfg,
    ) -> None:
        err = direct_chat._open_url_with_site_context("https://www.youtube.com/", "youtube", session_id="sess")
        self.assertIsNone(err)
        verbs = [str(c.args[0][0]) for c in mock_xdotool.call_args_list if c.args and c.args[0]]
        self.assertIn("windowactivate", verbs)
        self.assertIn("key", verbs)

    @patch("openclaw_direct_chat._xdotool_command", return_value=(0, "ok"))
    @patch("openclaw_direct_chat._wmctrl_current_desktop_site_windows", return_value=[("0xabc", "YouTube - Google Chrome")])
    @patch("openclaw_direct_chat._pick_active_site_window_id", return_value=(None, "not_active"))
    @patch("openclaw_direct_chat._expected_profile_directory_for_site", return_value="Profile 1")
    def test_youtube_transport_activates_target_window(
        self,
        _mock_profile,
        _mock_pick_active,
        _mock_ws_windows,
        mock_xdotool,
    ) -> None:
        ok, _detail = direct_chat._youtube_transport_action("pause", close_window=False, session_id="sess")
        self.assertTrue(ok)
        verbs = [str(c.args[0][0]) for c in mock_xdotool.call_args_list if c.args and c.args[0]]
        self.assertIn("windowactivate", verbs)
        self.assertIn("key", verbs)

    @patch("openclaw_direct_chat._wmctrl_current_desktop_site_windows", return_value=[])
    @patch("openclaw_direct_chat._pick_active_site_window_id", return_value=(None, "not_active"))
    @patch("openclaw_direct_chat._expected_profile_directory_for_site", return_value="Profile 1")
    def test_youtube_transport_returns_not_found_without_workspace_block(
        self,
        _mock_profile,
        _mock_pick_active,
        _mock_ws_windows,
    ) -> None:
        ok, detail = direct_chat._youtube_transport_action("pause", close_window=False, session_id="sess")
        self.assertFalse(ok)
        self.assertIn("youtube_window_not_found_current_desktop", detail)

    @patch("openclaw_direct_chat._load_browser_profile_config", return_value={"_default": {"browser": "chrome", "profile": "diego"}})
    @patch("openclaw_direct_chat._expected_profile_directory_for_site", return_value="Profile 1")
    @patch("openclaw_direct_chat._wmctrl_current_desktop", return_value=1)
    @patch("openclaw_direct_chat._wmctrl_windows_for_desktop", return_value=[])
    @patch("openclaw_direct_chat._trusted_or_autodetected_dc_anchor", return_value=(None, "anchor_none"))
    @patch("openclaw_direct_chat._fallback_profiled_chrome_anchor_for_workspace", return_value=("0xabc", "fallback_ok"))
    @patch("openclaw_direct_chat._xdotool_command", return_value=(0, "ok"))
    @patch("openclaw_direct_chat._wait_window_title_contains", return_value=(False, "about:blank - Google Chrome"))
    @patch("openclaw_direct_chat._wmctrl_active_desktop", return_value=1)
    def test_open_url_with_context_requires_verified_open(
        self,
        _mock_active_desk,
        _mock_wait_title,
        _mock_xdotool,
        _mock_fallback,
        _mock_anchor,
        _mock_windows,
        _mock_desktop,
        _mock_profile,
        _mock_cfg,
    ) -> None:
        err = direct_chat._open_url_with_site_context("https://www.youtube.com/", "youtube", session_id="sess")
        self.assertIsInstance(err, str)
        self.assertIn("no pude verificar apertura real", err.lower())

    @patch.dict(os.environ, {"DIRECT_CHAT_ISOLATED_WORKSPACE": "1"}, clear=False)
    def test_gemini_write_not_blocked_in_isolated_workspace_mode(self) -> None:
        out = direct_chat._maybe_handle_local_action(
            "en gemini escribi hola equipo",
            {"firefox", "web_search", "web_ask", "desktop", "model"},
            "sess_test",
        )
        self.assertIsNotNone(out)
        self.assertNotIn("gemini_write deshabilitado", str(out.get("reply", "")).lower())


if __name__ == "__main__":
    unittest.main()
