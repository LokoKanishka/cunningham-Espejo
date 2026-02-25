import os
import sys
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))


from molbot_direct_chat import stt_local  # noqa: E402


class TestSttLocalFilters(unittest.TestCase):
    def test_effective_segment_threshold_clamps_low_values(self) -> None:
        thr = stt_local._effective_segment_threshold(0.001, [])
        self.assertGreaterEqual(thr, 0.006)

    def test_effective_segment_threshold_uses_noise_floor(self) -> None:
        thr = stt_local._effective_segment_threshold(0.002, [0.004, 0.005, 0.006, 0.005])
        self.assertGreaterEqual(thr, 0.015)

    def test_filter_transcript_allows_short_whitelisted_words(self) -> None:
        txt, reason = stt_local._filter_transcript_text("¡hola!", min_chars=8)
        self.assertEqual(reason, "")
        self.assertEqual(txt, "¡hola")

    def test_filter_transcript_accepts_normal_text(self) -> None:
        txt, reason = stt_local._filter_transcript_text("  hola mundo  ", min_chars=3)
        self.assertEqual(reason, "")
        self.assertEqual(txt, "hola mundo")

    def test_filter_transcript_rejects_only_numbers_symbols(self) -> None:
        txt, reason = stt_local._filter_transcript_text("### 1234 --", min_chars=3)
        self.assertEqual(txt, "")
        self.assertIn(reason, ("text_no_letters", "text_noise_mostly_non_letters"))

    def test_filter_transcript_rejects_single_letter_spam(self) -> None:
        txt, reason = stt_local._filter_transcript_text("a b c d", min_chars=3)
        self.assertEqual(txt, "")
        self.assertEqual(reason, "text_noise_single_chars")

    def test_filter_transcript_keeps_reader_commands_with_digits(self) -> None:
        txt, reason = stt_local._filter_transcript_text("leer libro 1", min_chars=3)
        self.assertEqual(reason, "")
        self.assertEqual(txt, "leer libro 1")

    def test_segment_hysteresis_hangover_avoids_flicker_short_drop_in_chat_mode(self) -> None:
        cfg = stt_local.STTConfig(
            frame_ms=30,
            min_speech_ms=220,
            chat_min_speech_ms=180,
            max_silence_ms=350,
            rms_speech_threshold=0.016,
            rms_min_frames=2,
            segment_hysteresis_off_ratio=0.65,
            segment_hangover_ms=250,
            chat_mode=True,
        )
        speech_rms = [
            0.020,
            0.018,
            0.008,
            0.017,
            0.019,
            0.009,
            0.018,
            0.019,
            0.008,
            0.018,
            0.019,
            0.009,
            0.018,
            0.020,
            0.017,
            0.018,
        ]
        silence_rms = [0.003] * 14
        rms_values = speech_rms + silence_rms
        vad_values = [
            True,
            True,
            False,
            True,
            True,
            False,
            True,
            True,
            False,
            True,
            True,
            False,
            True,
            True,
            True,
            True,
        ] + ([False] * 14)
        emitted, dropped = stt_local._simulate_segments_for_test(rms_values, cfg=cfg, vad_values=vad_values)
        self.assertTrue(emitted)
        self.assertGreaterEqual(int(emitted[0]), 400)
        self.assertNotIn("segment_too_short", dropped)


if __name__ == "__main__":
    unittest.main()
