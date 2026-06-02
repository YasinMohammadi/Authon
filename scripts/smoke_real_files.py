from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from authon_core import activate_profile, default_state, normalize_profile, save_state


DEMO = ROOT / "demo-real-files"
USERS = DEMO / "users"
WORKING_AUTH = DEMO / "working-app" / "auth.json"
CONFIG_PATH = DEMO / "cli-smoke-config.json"


def main() -> int:
    reset_working_auth()
    try:
        direct_flow()
        config_flow()
        print_summary()
    finally:
        reset_working_auth()
    return 0


def reset_working_auth() -> None:
    WORKING_AUTH.parent.mkdir(parents=True, exist_ok=True)
    WORKING_AUTH.write_text((USERS / "initial.auth.json").read_text(encoding="utf-8"), encoding="utf-8")
    if CONFIG_PATH.exists():
        CONFIG_PATH.unlink()
    save_state(default_state(), CONFIG_PATH)


def direct_flow() -> None:
    activate_profile(USERS / "alice.auth.json", WORKING_AUTH, "Alice Lab")
    activate_profile(USERS / "bob.auth.json", WORKING_AUTH, "Bob Lab")
    active = read_user_id(WORKING_AUTH)
    if active != "bob-lab":
        raise AssertionError(f"Expected bob-lab after direct flow, got {active}")


def config_flow() -> None:
    state = default_state()
    state["target_path"] = str(WORKING_AUTH)
    state["profiles"] = [
        normalize_profile(
            {
                "name": "Charlie Lab",
                "path": str(USERS / "charlie.auth.json"),
                "switch_time": "18:30",
                "expires_on": "2999-12-31",
            }
        )
    ]
    save_state(state, CONFIG_PATH)
    activate_profile(Path(state["profiles"][0]["path"]), WORKING_AUTH, state["profiles"][0]["name"])
    active = read_user_id(WORKING_AUTH)
    if active != "charlie-lab":
        raise AssertionError(f"Expected charlie-lab after config flow, got {active}")


def print_summary() -> None:
    backups = sorted((WORKING_AUTH.parent / "authon_backups").glob("*.json"))
    print(f"working auth: {WORKING_AUTH}")
    print(f"active user: {read_user_id(WORKING_AUTH)}")
    print(f"backup files: {len(backups)}")
    for backup in backups[-5:]:
        print(f"- {backup.name}: {read_user_id(backup)}")


def read_user_id(path: Path) -> str:
    return json.loads(path.read_text(encoding="utf-8"))["user_id"]


if __name__ == "__main__":
    raise SystemExit(main())
