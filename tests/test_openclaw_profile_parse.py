import os
import sys
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))


import openclaw_direct_chat as direct_chat  # noqa: E402


class TestProfileParse(unittest.TestCase):
    def test_parse_profile_directory_equals_form(self) -> None:
        args = [
            "/opt/google/chrome/chrome",
            "--user-data-dir=/home/user/.config/google-chrome",
            "--profile-directory=Profile 1",
            "--new-window",
        ]
        self.assertEqual(direct_chat._profile_directory_from_args(args), "Profile 1")

    def test_parse_profile_directory_split_form(self) -> None:
        args = [
            "/opt/google/chrome/chrome",
            "--user-data-dir",
            "/home/user/.config/google-chrome",
            "--profile-directory",
            "diego",
        ]
        self.assertEqual(direct_chat._profile_directory_from_args(args), "diego")

    def test_parse_profile_directory_missing(self) -> None:
        args = ["/opt/google/chrome/chrome", "--new-window", "https://gemini.google.com/app"]
        self.assertEqual(direct_chat._profile_directory_from_args(args), "")


if __name__ == "__main__":
    unittest.main()
