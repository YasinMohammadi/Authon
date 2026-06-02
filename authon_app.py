from __future__ import annotations

import argparse

from authon_cli import run_cli_app
from authon_core import APP_NAME, default_config_path, load_state


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Authon terminal auth.json switcher")
    parser.add_argument("--cli", action="store_true", help="run the terminal UI; this is the default")
    parser.add_argument("--check", action="store_true", help="load config and exit")
    args = parser.parse_args(argv)

    if args.check:
        config_path = default_config_path()
        state = load_state(config_path)
        print(f"{APP_NAME} config: {config_path}")
        print(f"profiles: {len(state.get('profiles', []))}")
        return 0

    return run_cli_app()


if __name__ == "__main__":
    raise SystemExit(run())
