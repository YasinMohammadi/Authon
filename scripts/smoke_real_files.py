from __future__ import annotations

import json
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import authon_app
from authon_core import activate_profile, default_state, save_state


DEMO = ROOT / "demo-real-files"
USERS = DEMO / "users"
WORKING_AUTH = DEMO / "working-app" / "auth.json"
CONFIG_PATH = DEMO / "browser-smoke-config.json"


def main() -> int:
    reset_working_auth()
    try:
        direct_flow()
        browser_flow()
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


def browser_flow() -> None:
    original_default_config_path = authon_app.default_config_path
    authon_app.default_config_path = lambda: CONFIG_PATH
    app = authon_app.BrowserAuthonApp()
    server = ThreadingHTTPServer(("127.0.0.1", 0), authon_app.make_handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        post_json(f"{base}/api/target", {"target_path": str(WORKING_AUTH)})
        post_json(
            f"{base}/api/profiles",
            {
                "name": "Charlie Lab",
                "path": str(USERS / "charlie.auth.json"),
                "switch_time": "18:30",
            },
        )
        post_json(f"{base}/api/activate", {"index": 0})
        active = read_user_id(WORKING_AUTH)
        if active != "charlie-lab":
            raise AssertionError(f"Expected charlie-lab after browser flow, got {active}")
    finally:
        server.shutdown()
        server.server_close()
        authon_app.default_config_path = original_default_config_path


def print_summary() -> None:
    backups = sorted((WORKING_AUTH.parent / "authon_backups").glob("*.json"))
    print(f"working auth: {WORKING_AUTH}")
    print(f"active user: {read_user_id(WORKING_AUTH)}")
    print(f"backup files: {len(backups)}")
    for backup in backups[-5:]:
        print(f"- {backup.name}: {read_user_id(backup)}")


def read_user_id(path: Path) -> str:
    return json.loads(path.read_text(encoding="utf-8"))["user_id"]


def post_json(url: str, payload: dict[str, object]) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
