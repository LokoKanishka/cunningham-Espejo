import os
import sqlite3
import sys
import unittest
from unittest.mock import patch
import tempfile
from pathlib import Path


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

    @patch("openclaw_direct_chat.web_search.searxng_search")
    @patch("openclaw_direct_chat.subprocess.run")
    @patch("openclaw_direct_chat.shutil.which", return_value="/usr/bin/yt-dlp")
    def test_pick_first_youtube_video_url_latest_prefers_ytdlp_date_mode(
        self,
        _mock_which,
        mock_run,
        mock_search,
    ) -> None:
        mock_run.return_value.stdout = "abc123xyz\n"
        mock_run.return_value.returncode = 0
        url, reason = direct_chat._pick_first_youtube_video_url("ultimo video de memorias de pez")
        self.assertEqual(url, "https://www.youtube.com/watch?v=abc123xyz&autoplay=1")
        self.assertEqual(reason, "ok_ytdlp:ytsearchdate1")
        self.assertEqual(mock_search.call_count, 0)
        called = [str(x) for x in (mock_run.call_args.args[0] if mock_run.call_args else [])]
        self.assertIn("ytsearchdate1:ultimo video de memorias de pez", called)

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

    def test_looks_like_youtube_play_request_accepts_abrilo(self) -> None:
        normalized = direct_chat._normalize_text("busca el ultimo video de memorias de pez en youtube y abrilo")
        self.assertTrue(direct_chat._looks_like_youtube_play_request(normalized))

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
        with patch("openclaw_direct_chat._guardrail_check", return_value=(True, "GUARDRAIL_OK")):
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
        calls = {"n": 0}

        def _wins(_desk_idx: int):
            calls["n"] += 1
            if calls["n"] <= 1:
                return []
            return [("0xnew", "101", "YouTube - Google Chrome")]

        _mock_windows.side_effect = _wins
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

    @patch("openclaw_direct_chat._xdotool_command", return_value=(0, "ok"))
    @patch(
        "openclaw_direct_chat._wmctrl_current_desktop_site_windows",
        return_value=[
            ("0xbad", "youtube.com/watch?v=abc123xyz - Google Chrome"),
            ("0xgood", "TODO ES GEOPOLITICA - YouTube - Google Chrome"),
        ],
    )
    @patch("openclaw_direct_chat._pick_active_site_window_id", return_value=(None, "not_active"))
    @patch("openclaw_direct_chat._expected_profile_directory_for_site", return_value="Profile 1")
    def test_youtube_transport_prefers_loaded_video_window_over_raw_url_title(
        self,
        _mock_profile,
        _mock_pick_active,
        _mock_ws_windows,
        mock_xdotool,
    ) -> None:
        ok, detail = direct_chat._youtube_transport_action("pause", close_window=False, session_id="sess")
        self.assertTrue(ok)
        self.assertIn("win=0xgood", detail)
        first_activate = next((c.args[0] for c in mock_xdotool.call_args_list if c.args and c.args[0] and c.args[0][0] == "windowactivate"), [])
        self.assertIn("0xgood", first_activate)

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
        calls = {"n": 0}

        def _wins(_desk_idx: int):
            calls["n"] += 1
            if calls["n"] <= 1:
                return []
            return [("0xnew", "101", "YouTube - Google Chrome")]

        _mock_windows.side_effect = _wins
        err = direct_chat._open_url_with_site_context("https://www.youtube.com/", "youtube", session_id="sess")
        self.assertIsInstance(err, str)
        self.assertIn("no pude verificar apertura real", err.lower())

    def test_open_url_with_context_spawned_window_retries_manual_navigation(self) -> None:
        with (
            patch("openclaw_direct_chat._load_browser_profile_config", return_value={"_default": {"browser": "chrome", "profile": "diego"}}),
            patch("openclaw_direct_chat._expected_profile_directory_for_site", return_value="Profile 1"),
            patch("openclaw_direct_chat._wmctrl_current_desktop", return_value=1),
            patch("openclaw_direct_chat._wmctrl_windows_for_desktop", return_value=[]),
            patch("openclaw_direct_chat._trusted_or_autodetected_dc_anchor", return_value=(None, "anchor_none")),
            patch("openclaw_direct_chat._fallback_profiled_chrome_anchor_for_workspace", return_value=(None, "fallback_none")),
            patch("openclaw_direct_chat._spawn_profiled_chrome_anchor_for_workspace", return_value=("0xnew", "spawn_profiled_chrome_ok")),
            patch("openclaw_direct_chat._xdotool_command", return_value=(0, "ok")) as mock_xdotool,
            patch(
                "openclaw_direct_chat._wait_window_title_contains",
                side_effect=[
                    (False, "publico - google auth platform - consola de google cloud - google chrome"),
                    (True, "youtube - google chrome"),
                ],
            ) as mock_wait_title,
            patch("openclaw_direct_chat._wmctrl_list", return_value={"0xnew": "YouTube - Google Chrome"}),
            patch("openclaw_direct_chat.time.sleep", return_value=None),
        ):
            err = direct_chat._open_url_with_site_context("https://www.youtube.com/", "youtube")
        self.assertIsNone(err)
        self.assertEqual(mock_wait_title.call_count, 2)
        key_calls = [c.args[0] for c in mock_xdotool.call_args_list if c.args and c.args[0] and c.args[0][0] == "key"]
        self.assertTrue(any("ctrl+l" in str(cmd) for cmd in key_calls))

    def test_open_url_with_context_does_not_reuse_dc_anchor_when_new_window_not_detected(self) -> None:
        with (
            patch("openclaw_direct_chat._load_browser_profile_config", return_value={"_default": {"browser": "chrome", "profile": "diego"}}),
            patch("openclaw_direct_chat._expected_profile_directory_for_site", return_value="Profile 1"),
            patch("openclaw_direct_chat._wmctrl_current_desktop", return_value=1),
            patch("openclaw_direct_chat._wmctrl_windows_for_desktop", return_value=[]),
            patch("openclaw_direct_chat._trusted_or_autodetected_dc_anchor", return_value=(None, "anchor_none")),
            patch("openclaw_direct_chat._fallback_profiled_chrome_anchor_for_workspace", return_value=("0xabc", "fallback_ok")),
            patch("openclaw_direct_chat._spawn_profiled_chrome_anchor_for_workspace", return_value=(None, "spawn_none")),
            patch("openclaw_direct_chat._xdotool_command", return_value=(0, "ok")) as mock_xdotool,
            patch("openclaw_direct_chat.time.sleep", return_value=None),
        ):
            err = direct_chat._open_url_with_site_context("https://www.youtube.com/watch?v=abc123xyz", "youtube")
        self.assertIsInstance(err, str)
        self.assertIn("nueva ventana segura", str(err).lower())
        type_calls = [c.args[0] for c in mock_xdotool.call_args_list if c.args and c.args[0] and c.args[0][0] == "type"]
        self.assertEqual(type_calls, [])

    def test_site_title_looks_loaded_youtube_rejects_raw_watch_title(self) -> None:
        self.assertFalse(
            direct_chat._site_title_looks_loaded(
                "youtube",
                "https://www.youtube.com/watch?v=abc123xyz",
                "youtube.com/watch?v=abc123xyz - Google Chrome",
            )
        )
        self.assertTrue(
            direct_chat._site_title_looks_loaded(
                "youtube",
                "https://www.youtube.com/watch?v=abc123xyz",
                "Todo Es Geopolitica - YouTube - Google Chrome",
            )
        )

    def test_open_url_with_context_spawned_window_provisional_title_forces_manual_navigation(self) -> None:
        with (
            patch("openclaw_direct_chat._load_browser_profile_config", return_value={"_default": {"browser": "chrome", "profile": "diego"}}),
            patch("openclaw_direct_chat._expected_profile_directory_for_site", return_value="Profile 1"),
            patch("openclaw_direct_chat._wmctrl_current_desktop", return_value=1),
            patch("openclaw_direct_chat._wmctrl_windows_for_desktop", return_value=[]),
            patch("openclaw_direct_chat._trusted_or_autodetected_dc_anchor", return_value=(None, "anchor_none")),
            patch("openclaw_direct_chat._fallback_profiled_chrome_anchor_for_workspace", return_value=(None, "fallback_none")),
            patch("openclaw_direct_chat._spawn_profiled_chrome_anchor_for_workspace", return_value=("0xnew", "spawn_profiled_chrome_ok")),
            patch("openclaw_direct_chat._xdotool_command", return_value=(0, "ok")) as mock_xdotool,
            patch(
                "openclaw_direct_chat._wait_window_title_contains",
                side_effect=[
                    (True, "youtube.com/watch?v=abc123xyz - google chrome"),
                    (True, "todo es geopolitica - youtube - google chrome"),
                ],
            ) as mock_wait_title,
            patch("openclaw_direct_chat._wmctrl_list", return_value={"0xnew": "Todo Es Geopolitica - YouTube - Google Chrome"}),
            patch("openclaw_direct_chat.time.sleep", return_value=None),
        ):
            err = direct_chat._open_url_with_site_context("https://www.youtube.com/watch?v=abc123xyz", "youtube")
        self.assertIsNone(err)
        self.assertEqual(mock_wait_title.call_count, 2)
        key_calls = [c.args[0] for c in mock_xdotool.call_args_list if c.args and c.args[0] and c.args[0][0] == "key"]
        self.assertTrue(any("ctrl+l" in str(cmd) for cmd in key_calls))

    def test_open_url_with_context_youtube_provisional_title_is_soft_accepted(self) -> None:
        with (
            patch("openclaw_direct_chat._load_browser_profile_config", return_value={"_default": {"browser": "chrome", "profile": "diego"}}),
            patch("openclaw_direct_chat._expected_profile_directory_for_site", return_value="Profile 1"),
            patch("openclaw_direct_chat._wmctrl_current_desktop", return_value=1),
            patch("openclaw_direct_chat._wmctrl_windows_for_desktop", return_value=[]),
            patch("openclaw_direct_chat._trusted_or_autodetected_dc_anchor", return_value=(None, "anchor_none")),
            patch("openclaw_direct_chat._fallback_profiled_chrome_anchor_for_workspace", return_value=(None, "fallback_none")),
            patch("openclaw_direct_chat._spawn_profiled_chrome_anchor_for_workspace", return_value=("0xnew", "spawn_profiled_chrome_ok")),
            patch("openclaw_direct_chat._xdotool_command", return_value=(0, "ok")),
            patch(
                "openclaw_direct_chat._wait_window_title_contains",
                side_effect=[
                    (False, "youtube.com/watch?v=abc123xyz - google chrome"),
                    (False, "youtube.com/watch?v=abc123xyz - google chrome"),
                ],
            ),
            patch("openclaw_direct_chat.time.sleep", return_value=None),
        ):
            err = direct_chat._open_url_with_site_context("https://www.youtube.com/watch?v=abc123xyz", "youtube")
        self.assertIsNone(err)

    @patch.dict(os.environ, {"DIRECT_CHAT_ISOLATED_WORKSPACE": "1"}, clear=False)
    def test_gemini_write_not_blocked_in_isolated_workspace_mode(self) -> None:
        out = direct_chat._maybe_handle_local_action(
            "en gemini escribi hola equipo",
            {"firefox", "web_search", "web_ask", "desktop", "model"},
            "sess_test",
        )
        self.assertIsNotNone(out)
        self.assertNotIn("gemini_write deshabilitado", str(out.get("reply", "")).lower())

    @patch("openclaw_direct_chat._open_gemini_client_flow", return_value=(["https://gemini.google.com/app"], None))
    @patch("openclaw_direct_chat._open_url_with_site_context", return_value=None)
    @patch("openclaw_direct_chat._load_browser_profile_config")
    def test_open_site_urls_gemini_uses_firefox_when_configured(
        self,
        mock_cfg,
        mock_open_url,
        mock_gemini_flow,
    ) -> None:
        mock_cfg.return_value = {
            "_default": {"browser": "chrome", "profile": "diego"},
            "gemini": {"browser": "firefox", "profile": "Diego"},
        }
        opened, error = direct_chat._open_site_urls([("gemini", "https://gemini.google.com/app")], session_id="sess")
        self.assertIsNone(error)
        self.assertEqual(opened, ["https://gemini.google.com/app"])
        mock_open_url.assert_called_once()
        mock_gemini_flow.assert_not_called()

    @patch("openclaw_direct_chat.subprocess.Popen")
    @patch("openclaw_direct_chat._resolve_firefox_profile_name", return_value="Diego")
    @patch("openclaw_direct_chat._load_browser_profile_config")
    def test_open_url_with_site_context_firefox_uses_profile(
        self,
        mock_cfg,
        _mock_profile,
        mock_popen,
    ) -> None:
        mock_cfg.return_value = {
            "_default": {"browser": "chrome", "profile": "diego"},
            "gemini": {"browser": "firefox", "profile": "Diego"},
        }
        err = direct_chat._open_url_with_site_context("https://gemini.google.com/app", "gemini", session_id="sess")
        self.assertIsNone(err)
        argv = [str(x) for x in (mock_popen.call_args.args[0] if mock_popen.call_args else [])]
        self.assertIn("firefox", argv[0] if argv else "")
        self.assertIn("-P", argv)
        self.assertIn("Diego", argv)
        self.assertIn("--new-window", argv)

    @patch("openclaw_direct_chat._guardrail_check", return_value=(True, "GUARDRAIL_OK"))
    @patch("openclaw_direct_chat._open_site_urls", return_value=(["https://gemini.google.com/app"], None))
    @patch("openclaw_direct_chat._open_gemini_client_flow", return_value=(["https://www.google.com/", "https://gemini.google.com/app"], None))
    @patch("openclaw_direct_chat._load_browser_profile_config")
    def test_local_action_open_gemini_respects_firefox_config(
        self,
        mock_cfg,
        mock_gemini_flow,
        mock_open_urls,
        _mock_guardrail,
    ) -> None:
        mock_cfg.return_value = {
            "_default": {"browser": "chrome", "profile": "diego"},
            "gemini": {"browser": "firefox", "profile": "Diego"},
        }
        out = direct_chat._maybe_handle_local_action(
            "abrí gemini",
            {"firefox", "web_search", "web_ask", "desktop", "model"},
            "sess_test",
        )
        self.assertIsNotNone(out)
        self.assertIn("abrí gemini en firefox", str(out.get("reply", "")).lower())
        mock_open_urls.assert_called_once()
        mock_gemini_flow.assert_not_called()

    @patch("openclaw_direct_chat._load_browser_profile_config")
    def test_local_action_gemini_write_blocks_when_not_chrome(self, mock_cfg) -> None:
        mock_cfg.return_value = {
            "_default": {"browser": "chrome", "profile": "diego"},
            "gemini": {"browser": "firefox", "profile": "Diego"},
        }
        out = direct_chat._maybe_handle_local_action(
            "en gemini escribi hola equipo",
            {"firefox", "web_search", "web_ask", "desktop", "model"},
            "sess_test",
        )
        self.assertIsNotNone(out)
        self.assertIn("requiere gemini en chrome", str(out.get("reply", "")).lower())

    def test_resolve_firefox_profile_name_from_profile_groups(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pg = root / "Profile Groups"
            pg.mkdir(parents=True, exist_ok=True)
            db = pg / "group.sqlite"
            con = sqlite3.connect(str(db))
            try:
                con.execute(
                    "CREATE TABLE Profiles (id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, name TEXT NOT NULL, avatar TEXT NOT NULL, themeId TEXT NOT NULL, themeFg TEXT NOT NULL, themeBg TEXT NOT NULL)"
                )
                con.execute(
                    "INSERT INTO Profiles (id, path, name, avatar, themeId, themeFg, themeBg) VALUES (1, ?, ?, 'a', 't', 'fg', 'bg')",
                    ("STX7CwNy.Perfil 2", "Diego"),
                )
                con.commit()
            finally:
                con.close()
            with patch("openclaw_direct_chat._firefox_profile_roots", return_value=[root]):
                self.assertEqual(direct_chat._resolve_firefox_profile_name("Diego"), "Diego")
                self.assertEqual(direct_chat._resolve_firefox_profile_name("STX7CwNy.Perfil 2"), "Diego")

    @patch("openclaw_direct_chat._guardrail_check", return_value=(True, "GUARDRAIL_OK"))
    @patch("openclaw_direct_chat._open_site_urls", return_value=(["https://www.google.com/search?q=mariposas"], None))
    def test_local_action_google_search_open_page_routes_local(self, mock_open_urls, _mock_guardrail) -> None:
        out = direct_chat._maybe_handle_local_action(
            "busca en google sobre mariposas, abri la pagina de la busqueda",
            {"firefox", "web_search", "web_ask", "desktop", "model"},
            "sess_test",
        )
        self.assertIsNotNone(out)
        reply = str(out.get("reply", "")).lower()
        self.assertIn("resultados de google", reply)
        self.assertIn("mariposas", reply)
        self.assertIn("google.com/search?q=mariposas", reply)
        mock_open_urls.assert_called_once()

    @patch("openclaw_direct_chat._guardrail_check", return_value=(True, "GUARDRAIL_OK"))
    @patch("openclaw_direct_chat._pick_first_youtube_video_url", return_value=("https://www.youtube.com/watch?v=abc123xyz", "ok"))
    @patch("openclaw_direct_chat._open_site_urls", return_value=(["https://www.youtube.com/watch?v=abc123xyz"], None))
    @patch("openclaw_direct_chat._youtube_transport_action", return_value=(True, "ok action=play"))
    def test_local_action_youtube_natural_language_search_and_play(
        self, mock_play, mock_open_urls, mock_pick_video, _mock_guardrail
    ) -> None:
        out = direct_chat._maybe_handle_local_action(
            "abri youtube y busca noticias de geopolitica de hoy en español, abrilo y dale play",
            {"firefox", "web_search", "web_ask", "desktop", "model"},
            "sess_test",
        )
        self.assertIsNotNone(out)
        reply = str(out.get("reply", "")).lower()
        self.assertIn("reproduzco un video de youtube", reply)
        self.assertIn("geopolitica", reply)
        q = str((mock_pick_video.call_args.args[0] if mock_pick_video.call_args else "")).lower()
        self.assertIn("geopolitica", q)
        mock_open_urls.assert_called_once_with(
            [("youtube", "https://www.youtube.com/watch?v=abc123xyz")],
            session_id="sess_test",
        )
        mock_play.assert_called_once_with("play", close_window=False, session_id="sess_test")

    @patch("openclaw_direct_chat._guardrail_check", return_value=(True, "GUARDRAIL_OK"))
    @patch("openclaw_direct_chat._pick_first_youtube_video_url", return_value=("https://www.youtube.com/watch?v=abc123xyz", "ok"))
    @patch("openclaw_direct_chat._open_site_urls", return_value=(["https://www.youtube.com/watch?v=abc123xyz"], None))
    @patch("openclaw_direct_chat._youtube_transport_action", return_value=(True, "ok action=play"))
    def test_local_action_youtube_encontra_video_with_play(
        self, mock_play, mock_open_urls, mock_pick_video, _mock_guardrail
    ) -> None:
        out = direct_chat._maybe_handle_local_action(
            "abrí youtube y encontrá un video de contexto geopolitico actual en espanol, ponelo en play",
            {"firefox", "web_search", "web_ask", "desktop", "model"},
            "sess_test",
        )
        self.assertIsNotNone(out)
        reply = str(out.get("reply", "")).lower()
        self.assertIn("reproduzco un video de youtube", reply)
        q = str((mock_pick_video.call_args.args[0] if mock_pick_video.call_args else "")).lower()
        self.assertIn("contexto geopolitico actual en espanol", q)
        mock_open_urls.assert_called_once_with(
            [("youtube", "https://www.youtube.com/watch?v=abc123xyz")],
            session_id="sess_test",
        )
        mock_play.assert_called_once_with("play", close_window=False, session_id="sess_test")

    @patch("openclaw_direct_chat._guardrail_check", return_value=(True, "GUARDRAIL_OK"))
    @patch("openclaw_direct_chat._pick_first_youtube_video_url", return_value=("https://www.youtube.com/watch?v=abc123xyz", "ok"))
    @patch("openclaw_direct_chat._open_site_urls", return_value=(["https://www.youtube.com/watch?v=abc123xyz"], None))
    @patch("openclaw_direct_chat._youtube_transport_action", return_value=(True, "ok action=play"))
    def test_local_action_youtube_busca_abrilo_without_play_word_still_opens_and_plays(
        self, mock_play, mock_open_urls, mock_pick_video, _mock_guardrail
    ) -> None:
        out = direct_chat._maybe_handle_local_action(
            "busca el ultimo video de memorias de pez en youtube y abrilo",
            {"firefox", "web_search", "web_ask", "desktop", "model"},
            "sess_test",
        )
        self.assertIsNotNone(out)
        reply = str(out.get("reply", "")).lower()
        self.assertIn("reproduzco un video de youtube", reply)
        q = str((mock_pick_video.call_args.args[0] if mock_pick_video.call_args else "")).lower()
        self.assertIn("ultimo video de memorias de pez", q)
        mock_open_urls.assert_called_once_with(
            [("youtube", "https://www.youtube.com/watch?v=abc123xyz")],
            session_id="sess_test",
        )
        mock_play.assert_called_once_with("play", close_window=False, session_id="sess_test")

    @patch("openclaw_direct_chat._youtube_try_skip_ads", side_effect=[(1, "ad_skipped"), (0, "no_ad_detected")])
    @patch("openclaw_direct_chat._youtube_is_progressing", side_effect=[(False, "clock_stalled_0_to_0"), (True, "clock_advanced_0_to_1")])
    @patch("openclaw_direct_chat._xdotool_command", return_value=(0, "ok"))
    @patch("openclaw_direct_chat._wmctrl_current_desktop_site_windows", return_value=[("0xabc", "YouTube - Google Chrome")])
    @patch("openclaw_direct_chat._pick_active_site_window_id", return_value=(None, "not_active"))
    @patch("openclaw_direct_chat._expected_profile_directory_for_site", return_value="Profile 1")
    def test_youtube_transport_play_attempts_skip_ads_then_toggles(
        self,
        _mock_profile,
        _mock_pick_active,
        _mock_ws_windows,
        mock_xdotool,
        mock_progress,
        mock_skip_ads,
    ) -> None:
        ok, detail = direct_chat._youtube_transport_action("play", close_window=False, session_id="sess")
        self.assertTrue(ok)
        self.assertIn("skip_clicks=1", detail)
        self.assertIn("progress_detail=", detail)
        self.assertGreaterEqual(mock_skip_ads.call_count, 2)
        self.assertEqual(mock_progress.call_count, 2)
        verbs = [str(c.args[0][0]) for c in mock_xdotool.call_args_list if c.args and c.args[0]]
        self.assertIn("windowactivate", verbs)
        self.assertIn("key", verbs)
        k_calls = [c.args[0] for c in mock_xdotool.call_args_list if c.args and c.args[0] and c.args[0][0] == "key" and "k" in c.args[0]]
        self.assertGreaterEqual(len(k_calls), 1)

    @patch("openclaw_direct_chat._youtube_visual_progress", side_effect=[(False, "visual_static"), (True, "visual_changed")])
    @patch(
        "openclaw_direct_chat._youtube_try_skip_ads",
        side_effect=[(0, "ad_detected_skip_not_available"), (0, "ad_detected_skip_not_available"), (0, "no_ad_detected")],
    )
    @patch(
        "openclaw_direct_chat._youtube_is_progressing",
        side_effect=[(False, "clock_unreadable_t1"), (False, "clock_unreadable_t1"), (False, "clock_unreadable_t1")],
    )
    @patch("openclaw_direct_chat._xdotool_command", return_value=(0, "ok"))
    @patch("openclaw_direct_chat._wmctrl_current_desktop_site_windows", return_value=[("0xabc", "YouTube - Google Chrome")])
    @patch("openclaw_direct_chat._pick_active_site_window_id", return_value=(None, "not_active"))
    @patch("openclaw_direct_chat._expected_profile_directory_for_site", return_value="Profile 1")
    def test_youtube_transport_play_ad_static_uses_rescue_toggle(
        self,
        _mock_profile,
        _mock_pick_active,
        _mock_ws_windows,
        mock_xdotool,
        _mock_progress,
        _mock_skip_ads,
        _mock_visual,
    ) -> None:
        ok, detail = direct_chat._youtube_transport_action("play", close_window=False, session_id="sess")
        self.assertTrue(ok)
        self.assertIn("toggle_count=1", detail)
        self.assertIn("visual_changed", detail)
        k_calls = [c.args[0] for c in mock_xdotool.call_args_list if c.args and c.args[0] and c.args[0][0] == "key" and "k" in c.args[0]]
        self.assertGreaterEqual(len(k_calls), 1)

    @patch("openclaw_direct_chat._youtube_visual_progress", return_value=(True, "visual_changed"))
    @patch(
        "openclaw_direct_chat._youtube_try_skip_ads",
        side_effect=[(0, "no_ad_detected"), (0, "no_ad_detected"), (0, "ad_detected_skip_not_available")],
    )
    @patch(
        "openclaw_direct_chat._youtube_is_progressing",
        side_effect=[(False, "clock_unreadable_t1"), (False, "clock_unreadable_t1")],
    )
    @patch("openclaw_direct_chat._xdotool_command", return_value=(0, "ok"))
    @patch("openclaw_direct_chat._wmctrl_current_desktop_site_windows", return_value=[("0xabc", "YouTube - Google Chrome")])
    @patch("openclaw_direct_chat._pick_active_site_window_id", return_value=(None, "not_active"))
    @patch("openclaw_direct_chat._expected_profile_directory_for_site", return_value="Profile 1")
    def test_youtube_transport_visual_progress_rejected_when_ad_still_detected(
        self,
        _mock_profile,
        _mock_pick_active,
        _mock_ws_windows,
        _mock_xdotool,
        _mock_progress,
        _mock_skip_ads,
        _mock_visual,
    ) -> None:
        ok, detail = direct_chat._youtube_transport_action("play", close_window=False, session_id="sess")
        self.assertFalse(ok)
        self.assertIn("youtube_play_not_confirmed", detail)
        self.assertIn("ad_still_detected", detail)

    @patch("openclaw_direct_chat._close_recorded_browser_windows", return_value=(1, []))
    def test_local_action_close_web_human_phrase_without_window_word(self, _mock_close) -> None:
        out = direct_chat._maybe_handle_local_action(
            "cerrá lo que abriste recién en la web",
            {"firefox", "web_search", "web_ask", "desktop", "model"},
            "sess_test",
        )
        self.assertIsNotNone(out)
        reply = str(out.get("reply", "")).lower()
        self.assertIn("cerré 1 ventana", reply)

    @patch("openclaw_direct_chat._guardrail_check", return_value=(True, "GUARDRAIL_OK"))
    @patch(
        "openclaw_direct_chat.web_search.searxng_search",
        return_value={
            "ok": True,
            "results": [
                {
                    "title": "Mariposa, California - Wikipedia",
                    "url": "https://en.wikipedia.org/wiki/Mariposa,_California",
                    "content": "Mariposa is a county seat in California.",
                }
            ],
        },
    )
    @patch(
        "openclaw_direct_chat._open_site_urls",
        return_value=(["https://en.wikipedia.org/wiki/Mariposa,_California"], None),
    )
    def test_local_action_wikipedia_open_single_result_routes_local(
        self, mock_open_urls, _mock_search, _mock_guardrail
    ) -> None:
        out = direct_chat._maybe_handle_local_action(
            "busca en wikipedia mariposa, abri la pagina del resultado",
            {"firefox", "web_search", "web_ask", "desktop", "model"},
            "sess_test",
        )
        self.assertIsNotNone(out)
        reply = str(out.get("reply", "")).lower()
        self.assertIn("primer resultado", reply)
        self.assertIn("mariposa", reply)
        self.assertIn("en.wikipedia.org/wiki/mariposa,_california", reply)
        mock_open_urls.assert_called_once_with(
            [("wikipedia", "https://en.wikipedia.org/wiki/Mariposa,_California")],
            session_id="sess_test",
        )


if __name__ == "__main__":
    unittest.main()
