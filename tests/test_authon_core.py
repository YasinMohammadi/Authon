from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from authon_core import AuthonError, activate_profile, normalize_switch_time


class AuthonCoreTests(unittest.TestCase):
    def test_activate_profile_copies_source_and_backs_up_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "alice-auth.json"
            target = root / "auth.json"
            source.write_text(json.dumps({"token": "alice"}), encoding="utf-8")
            target.write_text(json.dumps({"token": "old"}), encoding="utf-8")

            result = activate_profile(source, target, "Alice")

            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"token": "alice"})
            self.assertIsNotNone(result.backup_path)
            self.assertTrue(result.backup_path.exists())
            self.assertEqual(json.loads(result.backup_path.read_text(encoding="utf-8")), {"token": "old"})

    def test_invalid_json_does_not_overwrite_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "bad-auth.json"
            target = root / "auth.json"
            source.write_text("{bad", encoding="utf-8")
            target.write_text(json.dumps({"token": "old"}), encoding="utf-8")

            with self.assertRaises(AuthonError):
                activate_profile(source, target, "Bad")

            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"token": "old"})

    def test_source_and_target_cannot_be_same_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "auth.json"
            path.write_text(json.dumps({"token": "same"}), encoding="utf-8")

            with self.assertRaises(AuthonError):
                activate_profile(path, path, "Same")

    def test_normalize_switch_time(self) -> None:
        self.assertEqual(normalize_switch_time("9:05"), "09:05")
        self.assertEqual(normalize_switch_time(""), "")
        with self.assertRaises(AuthonError):
            normalize_switch_time("25:00")


if __name__ == "__main__":
    unittest.main()
