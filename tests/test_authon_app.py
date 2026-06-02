from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

import authon_app
import authon_cli
from authon_core import AuthonError, normalize_profile, save_state


class AuthonAppTests(unittest.TestCase):
    def test_run_check_prints_config_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_default_config_path = authon_app.default_config_path
            config_path = Path(tmp) / "config.json"
            save_state({"target_path": "", "profiles": [], "active_profile": ""}, config_path)
            authon_app.default_config_path = lambda: config_path

            try:
                output = io.StringIO()
                with redirect_stdout(output):
                    exit_code = authon_app.run(["--check"])
            finally:
                authon_app.default_config_path = original_default_config_path

        self.assertEqual(exit_code, 0)
        self.assertIn("Authon config:", output.getvalue())
        self.assertIn("profiles: 0", output.getvalue())

    def test_normalize_profile(self) -> None:
        profile = normalize_profile(
            {"name": " Alice ", "path": " /tmp/alice/auth.json ", "switch_time": "9:05", "expires_on": " 2026-12-31 "}
        )

        self.assertEqual(profile["name"], "Alice")
        self.assertEqual(profile["path"], "/tmp/alice/auth.json")
        self.assertEqual(profile["switch_time"], "09:05")
        self.assertEqual(profile["expires_on"], "2026-12-31")

        with self.assertRaises(AuthonError):
            normalize_profile({"name": "", "path": "/tmp/auth.json", "switch_time": ""})
        with self.assertRaises(AuthonError):
            normalize_profile(
                {"name": "Alice", "path": "/tmp/auth.json", "switch_time": "", "expires_on": "31/12/2026"}
            )

    def test_cli_dashboard_renders_accounts_and_expiration(self) -> None:
        dashboard = authon_cli.render_cli_dashboard(
            {
                "target_path": "/tmp/app/auth.json",
                "active_profile": "Alice",
                "profiles": [
                    {
                        "name": "Alice",
                        "path": "/tmp/alice/auth.json",
                        "switch_time": "09:30",
                        "expires_on": "2999-12-31",
                    }
                ],
            },
            Path("/tmp/authon/config.json"),
            color_enabled=False,
            width=96,
        )

        self.assertIn("Authon", dashboard)
        self.assertIn("Linux terminal account switcher", dashboard)
        self.assertIn("Alice", dashboard)
        self.assertIn("2999-12-31", dashboard)
        self.assertIn("days left", dashboard)
        self.assertIn("Expiry:", dashboard)
        self.assertIn("No urgent expirations", dashboard)

    def test_cli_scroll_tracks_selected_row(self) -> None:
        self.assertEqual(authon_cli._normalize_scroll(selected=0, scroll=0, page_size=4, total=10), 0)
        self.assertEqual(authon_cli._normalize_scroll(selected=4, scroll=0, page_size=4, total=10), 1)
        self.assertEqual(authon_cli._normalize_scroll(selected=9, scroll=4, page_size=4, total=10), 6)
        self.assertEqual(authon_cli._normalize_scroll(selected=2, scroll=5, page_size=4, total=10), 2)
        self.assertEqual(authon_cli._normalize_scroll(selected=0, scroll=0, page_size=4, total=0), 0)

    def test_cli_expiry_summary_counts_urgent_accounts(self) -> None:
        profiles = [
            {"name": "Expired", "expires_on": "2026-06-01"},
            {"name": "Soon", "expires_on": "2026-06-12"},
            {"name": "Later", "expires_on": "2999-12-31"},
            {"name": "Open"},
        ]

        self.assertEqual(authon_cli._expiry_summary(profiles, today=date(2026, 6, 2)), "1 expired, 1 expiring soon")


if __name__ == "__main__":
    unittest.main()
