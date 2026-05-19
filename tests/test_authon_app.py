from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import authon_app
from authon_core import AuthonError


class AuthonAppTests(unittest.TestCase):
    def test_normalize_profile(self) -> None:
        profile = authon_app.normalize_profile(
            {"name": " Alice ", "path": " /tmp/alice/auth.json ", "switch_time": "9:05"}
        )

        self.assertEqual(profile["name"], "Alice")
        self.assertEqual(profile["path"], "/tmp/alice/auth.json")
        self.assertEqual(profile["switch_time"], "09:05")

        with self.assertRaises(AuthonError):
            authon_app.normalize_profile({"name": "", "path": "/tmp/auth.json", "switch_time": ""})

    def test_browser_state_and_target_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_default_config_path = authon_app.default_config_path
            authon_app.default_config_path = lambda: Path(tmp) / "config.json"
            app = authon_app.BrowserAuthonApp()
            server = ThreadingHTTPServer(("127.0.0.1", 0), authon_app.make_handler(app))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                base_url = f"http://127.0.0.1:{server.server_address[1]}"
                state = self.read_json(f"{base_url}/api/state")
                self.assertEqual(state["profiles"], [])

                target_path = str(Path(tmp) / "auth.json")
                updated = self.post_json(f"{base_url}/api/target", {"target_path": target_path})
                self.assertEqual(updated["target_path"], target_path)
            finally:
                server.shutdown()
                server.server_close()
                authon_app.default_config_path = original_default_config_path

    def read_json(self, url: str) -> dict[str, object]:
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def post_json(self, url: str, payload: dict[str, object]) -> dict[str, object]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
