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


if __name__ == "__main__":
    unittest.main()
