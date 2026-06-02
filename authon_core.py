from __future__ import annotations

import json
import os
import platform
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


APP_NAME = "Authon"


class AuthonError(Exception):
    """Raised for user-fixable Authon problems."""


@dataclass(frozen=True)
class ActivationResult:
    source_path: Path
    target_path: Path
    backup_path: Path | None


def default_config_path() -> Path:
    system = platform.system()
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / APP_NAME / "config.json"
        return Path.home() / "AppData" / "Roaming" / APP_NAME / "config.json"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME / "config.json"

    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        return Path(config_home) / "authon" / "config.json"
    return Path.home() / ".config" / "authon" / "config.json"


def default_state() -> dict[str, Any]:
    return {
        "target_path": "",
        "profiles": [],
        "active_profile": "",
        "auto_switch": False,
        "last_auto_runs": {},
        "last_backup": "",
    }


def load_state(config_path: Path | None = None) -> dict[str, Any]:
    path = config_path or default_config_path()
    if not path.exists():
        return default_state()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthonError(f"Could not read Authon config: {exc}") from exc

    state = default_state()
    if isinstance(data, dict):
        state.update({key: data.get(key, value) for key, value in state.items()})

    if not isinstance(state["profiles"], list):
        state["profiles"] = []
    if not isinstance(state["last_auto_runs"], dict):
        state["last_auto_runs"] = {}
    return state


def save_state(state: dict[str, Any], config_path: Path | None = None) -> Path:
    path = config_path or default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    return path


def validate_auth_json(path: Path) -> None:
    if not str(path).strip():
        raise AuthonError("Choose an auth.json file first.")
    if not path.exists():
        raise AuthonError(f"Auth file does not exist: {path}")
    if not path.is_file():
        raise AuthonError(f"Auth path is not a file: {path}")

    try:
        json.loads(path.read_text(encoding="utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise AuthonError(f"Auth file is not valid UTF-8 text: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AuthonError(f"Auth file is not valid JSON: {path} ({exc})") from exc


def normalize_switch_time(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""

    parts = cleaned.split(":")
    if len(parts) != 2:
        raise AuthonError("Switch time must be HH:MM, for example 09:30.")

    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise AuthonError("Switch time must use numbers, for example 09:30.") from exc

    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise AuthonError("Switch time must be between 00:00 and 23:59.")
    return f"{hour:02d}:{minute:02d}"


def normalize_profile(payload: dict[str, Any]) -> dict[str, str]:
    name = str(payload.get("name", "")).strip()
    path = str(payload.get("path", "")).strip()
    switch_time = normalize_switch_time(str(payload.get("switch_time", "")))
    expires_on = normalize_expiration_date(str(payload.get("expires_on", "")))

    if not name:
        raise AuthonError("User name is required.")
    if not path:
        raise AuthonError("Auth file is required.")

    return {"name": name, "path": path, "switch_time": switch_time, "expires_on": expires_on}


def normalize_expiration_date(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""

    try:
        parsed = date.fromisoformat(cleaned)
    except ValueError as exc:
        raise AuthonError("Expiration date must be YYYY-MM-DD, for example 2026-12-31.") from exc

    return parsed.isoformat()


def expiration_status(expires_on: str, today: date | None = None) -> str:
    cleaned = expires_on.strip()
    if not cleaned:
        return "No expiry"

    try:
        expiry = date.fromisoformat(cleaned)
    except ValueError:
        return "Invalid date"

    delta = (expiry - (today or date.today())).days
    if delta < 0:
        return "Expired"
    if delta == 0:
        return "Expires today"
    if delta == 1:
        return "1 day left"
    return f"{delta} days left"


def activate_profile(source_path: Path, target_path: Path, profile_name: str = "") -> ActivationResult:
    source = source_path.expanduser().resolve()
    target = target_path.expanduser().resolve()

    validate_auth_json(source)

    if not target.name:
        raise AuthonError("Choose the working auth.json path.")
    if source == target:
        raise AuthonError("Source auth file and working auth file are the same path.")
    if target.exists() and not target.is_file():
        raise AuthonError(f"Working auth path is not a file: {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    backup_path = backup_target(target, profile_name) if target.exists() else None

    temp_path = target.with_name(f".{target.name}.authon-{uuid.uuid4().hex}.tmp")
    try:
        shutil.copyfile(source, temp_path)
        os.replace(temp_path, target)
    except OSError as exc:
        raise AuthonError(f"Could not activate auth file: {exc}") from exc
    finally:
        if temp_path.exists():
            temp_path.unlink()

    return ActivationResult(source_path=source, target_path=target, backup_path=backup_path)


def backup_target(target: Path, profile_name: str = "") -> Path:
    backup_dir = target.parent / "authon_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    stem = target.stem or "auth"
    suffix = target.suffix or ".json"
    profile = _safe_filename_part(profile_name)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    unique = uuid.uuid4().hex[:8]
    parts = [stem]
    if profile:
        parts.append(profile)
    parts.extend([timestamp, unique])

    backup_path = backup_dir / (".".join(parts) + suffix)
    shutil.copy2(target, backup_path)
    return backup_path


def _safe_filename_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip()).strip("-")
    return cleaned[:40]
