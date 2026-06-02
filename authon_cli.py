from __future__ import annotations

import os
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any

from authon_core import (
    AuthonError,
    activate_profile,
    default_config_path,
    expiration_status,
    load_state,
    normalize_profile,
    save_state,
)


ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "blue": "\033[34m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "purple": "\033[35m",
    "cyan": "\033[36m",
}


def run_cli_app() -> int:
    config_path = default_config_path()
    state = load_state(config_path)
    color_enabled = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

    if not sys.stdin.isatty():
        print(render_cli_dashboard(state, config_path, color_enabled=color_enabled))
        return 0

    try:
        import curses
    except ImportError:
        return _run_prompt_cli(state, config_path, color_enabled)

    try:
        return curses.wrapper(lambda screen: _run_curses_cli(screen, state, config_path, curses))
    except curses.error as exc:
        print(f"Terminal UI is unavailable: {exc}", file=sys.stderr)
        return _run_prompt_cli(state, config_path, color_enabled)


def render_cli_dashboard(
    state: dict[str, Any],
    config_path: Path,
    status: str = "",
    color_enabled: bool = True,
    width: int | None = None,
) -> str:
    terminal_width = width or shutil.get_terminal_size((104, 28)).columns
    width = max(82, min(terminal_width, 122))
    inner = width - 4
    target = str(state.get("target_path", "")).strip() or "Not set"
    active = str(state.get("active_profile", "")).strip() or "None"
    profiles = list(state.get("profiles", []))
    expiry_summary = _expiry_summary(profiles)
    line = "+" + "-" * (width - 2) + "+"

    rows = [
        line,
        _frame_line(
            _paint("Authon", "bold", color_enabled)
            + "  "
            + _paint("Linux terminal account switcher", "cyan", color_enabled),
            width,
        ),
        _frame_line("Target: " + _shorten(target, inner - 8), width),
        _frame_line("Active: " + _paint(active, "green" if active != "None" else "dim", color_enabled), width),
        _frame_line("Expiry: " + _paint(expiry_summary, _expiry_summary_color(expiry_summary), color_enabled), width),
        _frame_line("Config: " + _shorten(str(config_path), inner - 8), width),
        line,
        _table_header(width, color_enabled),
        _table_rule(width),
    ]

    if not profiles:
        rows.append(_frame_line(_paint("No accounts yet. Press n to add one.", "dim", color_enabled), width))
    else:
        for index, profile in enumerate(profiles, start=1):
            rows.append(_format_profile_row(index, profile, active, width, color_enabled))

    rows.extend(
        [
            line,
            _frame_line(
                "Commands: "
                + _paint("Up/Down", "bold", color_enabled)
                + " move  "
                + _paint("Enter", "bold", color_enabled)
                + " activate  "
                + _paint("n/e/r/t/b/q", "bold", color_enabled)
                + " actions",
                width,
            ),
            _frame_line("Status: " + (status or "Ready."), width),
            line,
        ]
    )
    return "\n".join(rows)


def _run_prompt_cli(state: dict[str, Any], config_path: Path, color_enabled: bool) -> int:
    status = "Ready."
    while True:
        _clear_screen()
        print(render_cli_dashboard(state, config_path, status=status, color_enabled=color_enabled))
        choice = _prompt(
            "\nChoose: [a]ctivate  [n]ew  [e]dit  [r]emove  [t]arget  [b]ackups  [q]uit",
            color_enabled=color_enabled,
        ).lower()

        try:
            if choice in {"q", "quit", "exit"}:
                print(_paint("Goodbye.", "dim", color_enabled))
                return 0
            if choice in {"", "refresh"}:
                status = "Refreshed."
            elif choice in {"a", "activate"}:
                status = _prompt_activate_profile(state, config_path, color_enabled)
            elif choice in {"n", "new", "add"}:
                status = _prompt_add_profile(state, config_path, color_enabled)
            elif choice in {"e", "edit"}:
                status = _prompt_edit_profile(state, config_path, color_enabled)
            elif choice in {"r", "remove", "delete"}:
                status = _prompt_remove_profile(state, config_path, color_enabled)
            elif choice in {"t", "target"}:
                status = _prompt_set_target(state, config_path, color_enabled)
            elif choice in {"b", "backups"}:
                status = _show_backups(state)
            else:
                status = "Unknown command."
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        except AuthonError as exc:
            status = str(exc)


def _run_curses_cli(screen: Any, state: dict[str, Any], config_path: Path, curses: Any) -> int:
    screen.keypad(True)
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    _init_curses_colors(curses)

    selected = 0
    scroll = 0
    status = "Use arrow keys to choose an account. Press Enter to activate."

    while True:
        profiles = state.setdefault("profiles", [])
        if profiles:
            selected = max(0, min(selected, len(profiles) - 1))
        else:
            selected = 0
            scroll = 0

        height, _width = screen.getmaxyx()
        page_size = max(1, height - 9)
        scroll = _normalize_scroll(selected, scroll, page_size, len(profiles))
        _draw_curses_dashboard(screen, state, config_path, selected, scroll, status, curses)

        key = screen.getch()
        if key in {ord("q"), ord("Q"), 27}:
            return 0
        if key in {curses.KEY_UP, ord("k")} and profiles:
            selected -= 1
        elif key in {curses.KEY_DOWN, ord("j")} and profiles:
            selected += 1
        elif key == curses.KEY_HOME and profiles:
            selected = 0
        elif key == curses.KEY_END and profiles:
            selected = len(profiles) - 1
        elif key == curses.KEY_PPAGE and profiles:
            selected -= page_size
        elif key == curses.KEY_NPAGE and profiles:
            selected += page_size
        elif key in {curses.KEY_ENTER, 10, 13}:
            try:
                status = _activate_profile_at_index(state, config_path, selected)
            except AuthonError as exc:
                status = str(exc)
        elif key in {ord("n"), ord("N")}:
            try:
                profile = _curses_profile_dialog(screen, curses, "New account", None)
            except AuthonError as exc:
                status = str(exc)
                continue
            if profile:
                profiles.append(profile)
                selected = len(profiles) - 1
                save_state(state, config_path)
                status = f"Added {profile['name']}."
        elif key in {ord("e"), ord("E")}:
            if not profiles:
                status = "No accounts are configured yet."
            else:
                try:
                    profile = _curses_profile_dialog(screen, curses, "Edit account", profiles[selected])
                except AuthonError as exc:
                    status = str(exc)
                    continue
                if profile:
                    profiles[selected] = profile
                    save_state(state, config_path)
                    status = f"Updated {profile['name']}."
        elif key in {ord("r"), ord("R")}:
            if not profiles:
                status = "No accounts are configured yet."
            elif _curses_confirm(screen, curses, f"Remove {profiles[selected].get('name', '')}?"):
                removed = profiles.pop(selected)
                if state.get("active_profile") == removed.get("name"):
                    state["active_profile"] = ""
                selected = max(0, selected - 1)
                save_state(state, config_path)
                status = f"Removed {removed.get('name', '')}."
            else:
                status = "Remove cancelled."
        elif key in {ord("t"), ord("T")}:
            target = _curses_prompt_with_default(screen, curses, "Working auth.json path", str(state.get("target_path", "")))
            if target is not None:
                state["target_path"] = target
                save_state(state, config_path)
                status = "Working auth path saved."
        elif key in {ord("b"), ord("B")}:
            try:
                status = _show_backups(state)
            except AuthonError as exc:
                status = str(exc)
        elif key in {ord("?"), ord("h"), ord("H")}:
            status = "Keys: Up/Down move, Enter activate, n new, e edit, r remove, t target, b backups, q quit."
        else:
            status = "Unknown key. Press ? for help."


def _draw_curses_dashboard(
    screen: Any,
    state: dict[str, Any],
    config_path: Path,
    selected: int,
    scroll: int,
    status: str,
    curses: Any,
) -> None:
    screen.erase()
    height, width = screen.getmaxyx()
    if height < 10 or width < 58:
        _curses_add(screen, 0, 0, "Authon needs a larger terminal.", _curses_attr(curses, "danger"))
        screen.refresh()
        return

    profiles = list(state.get("profiles", []))
    active = str(state.get("active_profile", ""))
    target = str(state.get("target_path", "")).strip() or "Not set"
    expiry_summary = _expiry_summary(profiles)
    visible_count = max(1, height - 9)
    path_width = max(10, width - 72)

    _curses_add(screen, 0, 0, " " * width, _curses_attr(curses, "title"))
    _curses_add(screen, 0, 1, "Authon", _curses_attr(curses, "title") | curses.A_BOLD)
    _curses_add(screen, 0, 10, "Linux account switcher", _curses_attr(curses, "title"))
    _curses_add(screen, 0, max(0, width - 44), "Enter activate  q quit  ? help", _curses_attr(curses, "title"))
    _curses_add(screen, 1, 1, "Target", curses.A_BOLD)
    _curses_add(screen, 1, 9, _shorten(target, width - 11))
    _curses_add(screen, 2, 1, "Active", curses.A_BOLD)
    _curses_add(screen, 2, 9, active or "None", _curses_attr(curses, "good" if active else "muted"))
    _curses_add(screen, 2, 30, "Expiry", curses.A_BOLD)
    _curses_add(screen, 2, 38, _shorten(expiry_summary, width - 40), _curses_attr(curses, _expiry_summary_curses_style(expiry_summary)))
    _curses_add(screen, 3, 1, "Config", curses.A_BOLD)
    _curses_add(screen, 3, 9, _shorten(str(config_path), width - 11), _curses_attr(curses, "muted"))

    header = f"{'':1} {'#':>2} {'A':1} {'Account':20} {'Expires':10} {'Status':16} {'Time':5} {'Auth file':{path_width}}"
    _curses_add(screen, 4, 0, " " * width, _curses_attr(curses, "header"))
    _curses_add(screen, 4, 1, _shorten(header, width - 2), _curses_attr(curses, "header") | curses.A_BOLD)

    if not profiles:
        _curses_add(screen, 6, 2, "No accounts yet. Press n to add one.", _curses_attr(curses, "muted"))
    else:
        for visual_index, profile in enumerate(profiles[scroll : scroll + visible_count], start=scroll):
            row = 5 + visual_index - scroll
            name = profile.get("name", "")
            is_selected = visual_index == selected
            is_active = name == active
            expires_on = profile.get("expires_on", "") or "-"
            exp_status = expiration_status(profile.get("expires_on", ""))
            row_text = (
                f"{'>' if is_selected else ' '} "
                f"{visual_index + 1:>2} "
                f"{'*' if is_active else ' '} "
                f"{_shorten(name, 20):20} "
                f"{_shorten(expires_on, 10):10} "
                f"{_shorten(exp_status, 16):16} "
                f"{_shorten(profile.get('switch_time', '') or '-', 5):5} "
                f"{_shorten(profile.get('path', '') or '-', path_width):{path_width}}"
            )
            row_attr = curses.A_REVERSE if is_selected else 0
            if is_active and not is_selected:
                row_attr |= _curses_attr(curses, "good")
            _curses_add(screen, row, 0, " " * width, row_attr)
            _curses_add(screen, row, 1, _shorten(row_text, width - 2), row_attr)
            if not is_selected:
                status_column = _curses_status_column()
                _curses_add(
                    screen,
                    row,
                    status_column,
                    f"{_shorten(exp_status, 16):16}",
                    _curses_attr(curses, _expiration_curses_style(exp_status)),
                )

    footer_y = height - 2
    _curses_add(screen, footer_y, 0, " " * width, _curses_attr(curses, "footer"))
    _curses_add(
        screen,
        footer_y,
        1,
        "Up/Down navigate  Enter activate  n new  e edit  r remove  t target  b backups  q quit",
        _curses_attr(curses, "footer"),
    )
    _curses_add(screen, height - 1, 0, " " * width, _curses_attr(curses, "status"))
    _curses_add(screen, height - 1, 1, _shorten(status, width - 2), _curses_attr(curses, "status"))
    screen.refresh()


def _prompt_activate_profile(state: dict[str, Any], config_path: Path, color_enabled: bool) -> str:
    profiles = list(state.get("profiles", []))
    index = _choose_profile_index(profiles, "Activate account", color_enabled)
    return _activate_profile_at_index(state, config_path, index)


def _activate_profile_at_index(state: dict[str, Any], config_path: Path, index: int) -> str:
    profiles = state.setdefault("profiles", [])
    if not profiles:
        raise AuthonError("No accounts are configured yet.")
    if index < 0 or index >= len(profiles):
        raise AuthonError("Selected account does not exist.")

    profile = profiles[index]
    target = str(state.get("target_path", "")).strip()
    result = activate_profile(Path(profile.get("path", "")), Path(target), profile.get("name", ""))
    state["target_path"] = target
    state["active_profile"] = profile.get("name", "")
    state["last_backup"] = str(result.backup_path or "")
    save_state(state, config_path)
    if result.backup_path:
        return f"Activated {profile.get('name', '')}. Backup: {result.backup_path}"
    return f"Activated {profile.get('name', '')}. No previous auth to back up."


def _prompt_add_profile(state: dict[str, Any], config_path: Path, color_enabled: bool) -> str:
    print(_section_title("New account", color_enabled))
    profile = normalize_profile(
        {
            "name": _prompt("Name", color_enabled=color_enabled),
            "path": _prompt("User auth.json path", color_enabled=color_enabled),
            "expires_on": _prompt("Expires YYYY-MM-DD (optional)", color_enabled=color_enabled),
            "switch_time": _prompt("Switch time HH:MM (optional)", color_enabled=color_enabled),
        }
    )
    state.setdefault("profiles", []).append(profile)
    save_state(state, config_path)
    return f"Added {profile['name']}."


def _prompt_edit_profile(state: dict[str, Any], config_path: Path, color_enabled: bool) -> str:
    profiles = state.setdefault("profiles", [])
    index = _choose_profile_index(profiles, "Edit account", color_enabled)
    current = profiles[index]
    print(_section_title(f"Edit {current.get('name', '')}", color_enabled))
    profile = normalize_profile(
        {
            "name": _prompt_with_default("Name", current.get("name", ""), color_enabled),
            "path": _prompt_with_default("User auth.json path", current.get("path", ""), color_enabled),
            "expires_on": _prompt_with_default("Expires YYYY-MM-DD", current.get("expires_on", ""), color_enabled),
            "switch_time": _prompt_with_default("Switch time HH:MM", current.get("switch_time", ""), color_enabled),
        }
    )
    profiles[index] = profile
    save_state(state, config_path)
    return f"Updated {profile['name']}."


def _prompt_remove_profile(state: dict[str, Any], config_path: Path, color_enabled: bool) -> str:
    profiles = state.setdefault("profiles", [])
    index = _choose_profile_index(profiles, "Remove account", color_enabled)
    profile = profiles[index]
    answer = _prompt(f"Remove {profile.get('name', '')}? Type yes", color_enabled=color_enabled).lower()
    if answer != "yes":
        return "Remove cancelled."
    removed = profiles.pop(index)
    if state.get("active_profile") == removed.get("name"):
        state["active_profile"] = ""
    save_state(state, config_path)
    return f"Removed {removed.get('name', '')}."


def _prompt_set_target(state: dict[str, Any], config_path: Path, color_enabled: bool) -> str:
    current = str(state.get("target_path", ""))
    state["target_path"] = _prompt_with_default("Working auth.json path", current, color_enabled)
    save_state(state, config_path)
    return "Working auth path saved."


def _show_backups(state: dict[str, Any]) -> str:
    target = str(state.get("target_path", "")).strip()
    if not target:
        raise AuthonError("Choose the working auth.json path first.")
    backup_dir = Path(target).expanduser().parent / "authon_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return f"Backups folder: {backup_dir}"


def _choose_profile_index(profiles: list[dict[str, str]], title: str, color_enabled: bool) -> int:
    if not profiles:
        raise AuthonError("No accounts are configured yet.")
    print(_section_title(title, color_enabled))
    for index, profile in enumerate(profiles, start=1):
        expires = expiration_status(profile.get("expires_on", ""))
        print(f"{index:>2}. {profile.get('name', '')}  [{expires}]")
    value = _prompt("Account number", color_enabled=color_enabled)
    try:
        selected = int(value)
    except ValueError as exc:
        raise AuthonError("Enter an account number.") from exc
    if selected < 1 or selected > len(profiles):
        raise AuthonError("Selected account does not exist.")
    return selected - 1


def _format_profile_row(
    index: int,
    profile: dict[str, str],
    active_profile: str,
    width: int,
    color_enabled: bool,
) -> str:
    path_width = max(12, width - 70)
    name = profile.get("name", "")
    active = "*" if name == active_profile else " "
    status = expiration_status(profile.get("expires_on", ""))
    status_color = _expiration_color(status)
    values = [
        f"{index:>2}",
        active,
        _shorten(name, 20),
        _shorten(profile.get("expires_on", "") or "-", 10),
        _shorten(_paint(status, status_color, color_enabled), 16 + _ansi_overhead(status, status_color, color_enabled)),
        _shorten(profile.get("switch_time", "") or "-", 5),
        _shorten(profile.get("path", "") or "-", path_width),
    ]
    widths = [2, 1, 20, 10, 16, 5, path_width]
    padded = [_pad_ansi(value, widths[position]) for position, value in enumerate(values)]
    return "| " + "  ".join(padded) + " |"


def _expiry_summary(profiles: list[dict[str, str]], today: date | None = None) -> str:
    expired = 0
    soon = 0
    for profile in profiles:
        status = expiration_status(profile.get("expires_on", ""), today=today)
        if status == "Expired":
            expired += 1
        elif status == "Expires today":
            soon += 1
        elif status.endswith("day left") or status.endswith("days left"):
            try:
                days = int(status.split()[0])
            except ValueError:
                continue
            if days <= 14:
                soon += 1
    if expired or soon:
        return f"{expired} expired, {soon} expiring soon"
    return "No urgent expirations"


def _expiry_summary_color(summary: str) -> str:
    if summary == "No urgent expirations":
        return "green"
    if not summary.startswith("0 expired"):
        return "red"
    if "expiring soon" in summary and not summary.endswith("0 expiring soon"):
        return "yellow"
    return "green"


def _expiry_summary_curses_style(summary: str) -> str:
    color = _expiry_summary_color(summary)
    if color == "red":
        return "danger"
    if color == "yellow":
        return "warning"
    return "good"


def _curses_status_column() -> int:
    # x=1 plus marker, number, active flag, account, and expiry columns.
    return 40


def _table_header(width: int, color_enabled: bool) -> str:
    path_width = max(12, width - 70)
    labels = ["##", "A", "Account", "Expires", "Status", "Time", "Auth file"]
    widths = [2, 1, 20, 10, 16, 5, path_width]
    return "| " + "  ".join(_pad_ansi(_paint(label, "bold", color_enabled), widths[index]) for index, label in enumerate(labels)) + " |"


def _table_rule(width: int) -> str:
    return "|" + "-" * (width - 2) + "|"


def _normalize_scroll(selected: int, scroll: int, page_size: int, total: int) -> int:
    if total <= 0:
        return 0
    scroll = max(0, min(scroll, max(0, total - page_size)))
    if selected < scroll:
        return selected
    if selected >= scroll + page_size:
        return selected - page_size + 1
    return scroll


def _init_curses_colors(curses: Any) -> None:
    if not curses.has_colors():
        return
    curses.start_color()
    try:
        curses.use_default_colors()
    except curses.error:
        pass
    color_specs = {
        1: (curses.COLOR_WHITE, curses.COLOR_BLUE),
        2: (curses.COLOR_BLACK, curses.COLOR_CYAN),
        3: (curses.COLOR_BLACK, curses.COLOR_WHITE),
        4: (curses.COLOR_GREEN, -1),
        5: (curses.COLOR_YELLOW, -1),
        6: (curses.COLOR_RED, -1),
        7: (curses.COLOR_MAGENTA, -1),
        8: (curses.COLOR_CYAN, -1),
        9: (curses.COLOR_WHITE, -1),
    }
    for pair, spec in color_specs.items():
        try:
            curses.init_pair(pair, *spec)
        except curses.error:
            pass


def _curses_attr(curses: Any, style: str) -> int:
    if not curses.has_colors():
        if style in {"title", "header", "footer", "status"}:
            return curses.A_REVERSE
        if style == "muted":
            return curses.A_DIM
        return 0

    pairs = {
        "title": 1,
        "header": 2,
        "footer": 3,
        "good": 4,
        "warning": 5,
        "danger": 6,
        "purple": 7,
        "status": 8,
        "muted": 9,
    }
    attr = curses.color_pair(pairs.get(style, 0))
    if style == "muted":
        attr |= curses.A_DIM
    return attr


def _curses_add(screen: Any, y: int, x: int, text: str, attr: int = 0) -> None:
    height, width = screen.getmaxyx()
    if y < 0 or y >= height or x < 0 or x >= width:
        return
    text = text[: max(0, width - x - 1)]
    try:
        screen.addstr(y, x, text, attr)
    except Exception:
        return


def _expiration_curses_style(status: str) -> str:
    color = _expiration_color(status)
    if color == "red":
        return "danger"
    if color == "yellow":
        return "warning"
    if color == "purple":
        return "purple"
    if color == "dim":
        return "muted"
    return "good"


def _curses_profile_dialog(
    screen: Any,
    curses: Any,
    title: str,
    profile: dict[str, str] | None,
) -> dict[str, str] | None:
    current = profile or {}
    values = {
        "name": _curses_prompt_with_default(screen, curses, f"{title} - name", current.get("name", "")),
        "path": None,
        "expires_on": None,
        "switch_time": None,
    }
    if values["name"] is None:
        return None
    values["path"] = _curses_prompt_with_default(screen, curses, f"{title} - user auth.json", current.get("path", ""))
    if values["path"] is None:
        return None
    values["expires_on"] = _curses_prompt_with_default(screen, curses, f"{title} - expires YYYY-MM-DD", current.get("expires_on", ""))
    if values["expires_on"] is None:
        return None
    values["switch_time"] = _curses_prompt_with_default(screen, curses, f"{title} - switch time HH:MM", current.get("switch_time", ""))
    if values["switch_time"] is None:
        return None
    return normalize_profile(values)


def _curses_prompt_with_default(screen: Any, curses: Any, label: str, default: str) -> str | None:
    suffix = f" [{default}]" if default else " [- clears]"
    value = _curses_prompt(screen, curses, label + suffix)
    if value is None:
        return None
    if value == "-":
        return ""
    return value if value else default


def _curses_confirm(screen: Any, curses: Any, question: str) -> bool:
    value = _curses_prompt(screen, curses, question + " Type yes")
    return bool(value and value.lower() == "yes")


def _curses_prompt(screen: Any, curses: Any, label: str) -> str | None:
    buffer: list[str] = []
    try:
        curses.curs_set(1)
    except curses.error:
        pass

    while True:
        height, width = screen.getmaxyx()
        y = height - 1
        prompt = label + ": " + "".join(buffer)
        _curses_add(screen, y, 0, " " * width, _curses_attr(curses, "status"))
        _curses_add(screen, y, 1, _shorten(prompt, width - 2), _curses_attr(curses, "status"))
        screen.move(y, min(width - 2, len(label) + 3 + len(buffer)))
        screen.refresh()
        key = screen.getch()
        if key == 27:
            _hide_cursor(curses)
            return None
        if key in {curses.KEY_ENTER, 10, 13}:
            _hide_cursor(curses)
            return "".join(buffer).strip()
        if key in {curses.KEY_BACKSPACE, 8, 127}:
            if buffer:
                buffer.pop()
            continue
        if 32 <= key <= 126:
            buffer.append(chr(key))


def _hide_cursor(curses: Any) -> None:
    try:
        curses.curs_set(0)
    except curses.error:
        pass


def _section_title(title: str, color_enabled: bool) -> str:
    return "\n" + _paint(title, "bold", color_enabled)


def _prompt(label: str, color_enabled: bool) -> str:
    return input(_paint(label + ": ", "blue", color_enabled)).strip()


def _prompt_with_default(label: str, default: str, color_enabled: bool) -> str:
    suffix = f" [{default}]" if default else " [- to clear]"
    value = input(_paint(label + suffix + ": ", "blue", color_enabled)).strip()
    if value == "-":
        return ""
    return value if value else default


def _clear_screen() -> None:
    if sys.stdout.isatty():
        print("\033[H\033[J", end="")


def _frame_line(content: str, width: int) -> str:
    return "| " + _pad_ansi(content, width - 4) + " |"


def _paint(text: str, color: str, enabled: bool) -> str:
    if not enabled:
        return text
    return ANSI.get(color, "") + text + ANSI["reset"]


def _expiration_color(status: str) -> str:
    if status in {"Expired", "Invalid date"}:
        return "red"
    if status == "Expires today":
        return "purple"
    if status == "No expiry":
        return "dim"
    if status.endswith("day left") or status.endswith("days left"):
        try:
            days = int(status.split()[0])
        except ValueError:
            return "green"
        return "yellow" if days <= 14 else "green"
    return "green"


def _shorten(value: str, max_width: int) -> str:
    if len(value) <= max_width:
        return value
    if max_width <= 3:
        return value[:max_width]
    head = max(1, (max_width - 3) // 2)
    tail = max_width - 3 - head
    return value[:head] + "..." + value[-tail:]


def _pad_ansi(value: str, width: int) -> str:
    plain_length = _visible_length(value)
    if plain_length >= width:
        return value
    return value + " " * (width - plain_length)


def _visible_length(value: str) -> int:
    length = 0
    index = 0
    while index < len(value):
        if value[index] == "\033":
            end = value.find("m", index)
            if end == -1:
                break
            index = end + 1
            continue
        length += 1
        index += 1
    return length


def _ansi_overhead(value: str, color: str, enabled: bool) -> int:
    if not enabled:
        return 0
    return len(_paint(value, color, True)) - len(value)
