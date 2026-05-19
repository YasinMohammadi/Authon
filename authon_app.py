from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from authon_core import APP_NAME, AuthonError, activate_profile, default_config_path, load_state, normalize_switch_time, save_state


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Authon cross-platform auth.json switcher")
    parser.add_argument("--browser", action="store_true", help="run the browser-based UI")
    parser.add_argument("--tk", action="store_true", help="require the Tk desktop UI")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser tab automatically")
    parser.add_argument("--host", default="127.0.0.1", help="browser UI host")
    parser.add_argument("--port", type=int, default=8765, help="browser UI port, or 0 for a random free port")
    parser.add_argument("--check", action="store_true", help="load config and exit")
    args = parser.parse_args(argv)

    if args.check:
        state = load_state()
        print(f"{APP_NAME} config: {default_config_path()}")
        print(f"profiles: {len(state.get('profiles', []))}")
        return 0

    if args.browser:
        return run_browser_app(args.host, args.port, open_browser=not args.no_browser)

    try:
        return run_tk_app()
    except Exception as exc:
        if args.tk:
            raise
        print(f"Tk desktop UI is unavailable: {exc}", file=sys.stderr)
        print("Starting the portable browser UI instead.", file=sys.stderr)
        return run_browser_app(args.host, args.port, open_browser=not args.no_browser)


def normalize_profile(payload: dict[str, Any]) -> dict[str, str]:
    name = str(payload.get("name", "")).strip()
    path = str(payload.get("path", "")).strip()
    switch_time = normalize_switch_time(str(payload.get("switch_time", "")))

    if not name:
        raise AuthonError("User name is required.")
    if not path:
        raise AuthonError("Auth file is required.")

    return {"name": name, "path": path, "switch_time": switch_time}


def run_tk_app() -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    class ProfileDialog(tk.Toplevel):
        def __init__(self, parent: tk.Tk, title: str, profile: dict[str, str] | None = None) -> None:
            super().__init__(parent)
            self.title(title)
            self.resizable(False, False)
            self.result: dict[str, str] | None = None

            profile = profile or {}
            self.name_var = tk.StringVar(value=profile.get("name", ""))
            self.path_var = tk.StringVar(value=profile.get("path", ""))
            self.time_var = tk.StringVar(value=profile.get("switch_time", ""))

            frame = ttk.Frame(self, padding=16)
            frame.grid(row=0, column=0, sticky="nsew")
            frame.columnconfigure(1, weight=1)

            ttk.Label(frame, text="User name").grid(row=0, column=0, sticky="w", pady=(0, 8))
            ttk.Entry(frame, textvariable=self.name_var, width=42).grid(row=0, column=1, columnspan=2, sticky="ew", pady=(0, 8))

            ttk.Label(frame, text="Auth file").grid(row=1, column=0, sticky="w", pady=(0, 8))
            ttk.Entry(frame, textvariable=self.path_var, width=42).grid(row=1, column=1, sticky="ew", pady=(0, 8))
            ttk.Button(frame, text="Browse", command=self.browse_auth).grid(row=1, column=2, padx=(8, 0), pady=(0, 8))

            ttk.Label(frame, text="Switch time").grid(row=2, column=0, sticky="w", pady=(0, 14))
            ttk.Entry(frame, textvariable=self.time_var, width=10).grid(row=2, column=1, sticky="w", pady=(0, 14))
            ttk.Label(frame, text="Optional HH:MM").grid(row=2, column=2, sticky="w", padx=(8, 0), pady=(0, 14))

            buttons = ttk.Frame(frame)
            buttons.grid(row=3, column=0, columnspan=3, sticky="e")
            ttk.Button(buttons, text="Cancel", command=self.destroy).grid(row=0, column=0, padx=(0, 8))
            ttk.Button(buttons, text="Save", command=self.save).grid(row=0, column=1)

            self.bind("<Return>", lambda _event: self.save())
            self.bind("<Escape>", lambda _event: self.destroy())
            self.transient(parent)
            self.grab_set()
            self.after(50, self._focus_first_entry)

        def _focus_first_entry(self) -> None:
            for child in self.winfo_children()[0].winfo_children():
                if isinstance(child, ttk.Entry):
                    child.focus_set()
                    break

        def browse_auth(self) -> None:
            path = filedialog.askopenfilename(
                parent=self,
                title="Choose user auth.json",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            )
            if path:
                self.path_var.set(path)

        def save(self) -> None:
            try:
                self.result = normalize_profile(
                    {
                        "name": self.name_var.get(),
                        "path": self.path_var.get(),
                        "switch_time": self.time_var.get(),
                    }
                )
            except AuthonError as exc:
                messagebox.showerror(APP_NAME, str(exc), parent=self)
                return
            self.destroy()

    class TkAuthonApp(tk.Tk):
        def __init__(self) -> None:
            super().__init__()
            self.config_path = default_config_path()
            self.state = load_state(self.config_path)
            self.target_var = tk.StringVar(value=self.state.get("target_path", ""))
            self.auto_var = tk.BooleanVar(value=bool(self.state.get("auto_switch", False)))
            self.status_var = tk.StringVar(value=f"Config: {self.config_path}")

            self.title(f"{APP_NAME} - auth particle switcher")
            self.geometry("860x520")
            self.minsize(780, 460)
            self._build_style()
            self._build_ui()
            self.refresh_profiles()
            self.check_schedule()

        def _build_style(self) -> None:
            style = ttk.Style(self)
            if sys.platform.startswith("win") and "vista" in style.theme_names():
                style.theme_use("vista")
            style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
            style.configure("Subtitle.TLabel", foreground="#4b5563")
            style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
            style.configure("Status.TLabel", foreground="#374151")

        def _build_ui(self) -> None:
            root = ttk.Frame(self, padding=18)
            root.grid(row=0, column=0, sticky="nsew")
            root.columnconfigure(0, weight=1)
            root.rowconfigure(2, weight=1)
            self.columnconfigure(0, weight=1)
            self.rowconfigure(0, weight=1)

            header = ttk.Frame(root)
            header.grid(row=0, column=0, sticky="ew", pady=(0, 16))
            header.columnconfigure(0, weight=1)
            ttk.Label(header, text=APP_NAME, style="Title.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Label(header, text="Tiny auth particle switcher", style="Subtitle.TLabel").grid(row=1, column=0, sticky="w")

            target_box = ttk.LabelFrame(root, text="Working auth.json", padding=12)
            target_box.grid(row=1, column=0, sticky="ew", pady=(0, 14))
            target_box.columnconfigure(0, weight=1)
            ttk.Entry(target_box, textvariable=self.target_var).grid(row=0, column=0, sticky="ew")
            ttk.Button(target_box, text="Browse", command=self.browse_target).grid(row=0, column=1, padx=(8, 0))
            ttk.Button(target_box, text="Save", command=self.save_target).grid(row=0, column=2, padx=(8, 0))

            body = ttk.Frame(root)
            body.grid(row=2, column=0, sticky="nsew")
            body.columnconfigure(0, weight=1)
            body.rowconfigure(0, weight=1)

            columns = ("name", "switch_time", "path")
            self.tree = ttk.Treeview(body, columns=columns, show="headings", selectmode="browse")
            self.tree.heading("name", text="User")
            self.tree.heading("switch_time", text="Time")
            self.tree.heading("path", text="Auth file")
            self.tree.column("name", width=170, minwidth=120, stretch=False)
            self.tree.column("switch_time", width=80, minwidth=70, stretch=False, anchor="center")
            self.tree.column("path", width=460, minwidth=220, stretch=True)
            self.tree.grid(row=0, column=0, sticky="nsew")
            self.tree.bind("<Double-1>", lambda _event: self.activate_selected())

            scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
            scrollbar.grid(row=0, column=1, sticky="ns")
            self.tree.configure(yscrollcommand=scrollbar.set)

            actions = ttk.Frame(body)
            actions.grid(row=0, column=2, sticky="ns", padx=(12, 0))
            ttk.Button(actions, text="Add", command=self.add_profile).grid(row=0, column=0, sticky="ew", pady=(0, 8))
            ttk.Button(actions, text="Edit", command=self.edit_profile).grid(row=1, column=0, sticky="ew", pady=(0, 8))
            ttk.Button(actions, text="Remove", command=self.remove_profile).grid(row=2, column=0, sticky="ew", pady=(0, 18))
            ttk.Button(actions, text="Activate", style="Accent.TButton", command=self.activate_selected).grid(row=3, column=0, sticky="ew")
            ttk.Button(actions, text="Backups", command=self.open_backups).grid(row=4, column=0, sticky="ew", pady=(18, 0))

            footer = ttk.Frame(root)
            footer.grid(row=3, column=0, sticky="ew", pady=(14, 0))
            footer.columnconfigure(1, weight=1)
            ttk.Checkbutton(footer, text="Auto switch by time", variable=self.auto_var, command=self.save_auto).grid(row=0, column=0, sticky="w", padx=(0, 12))
            ttk.Label(footer, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=1, sticky="ew")

        def browse_target(self) -> None:
            path = filedialog.askopenfilename(
                parent=self,
                title="Choose working auth.json",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            )
            if path:
                self.target_var.set(path)
                self.save_target()

        def save_target(self) -> None:
            self.state["target_path"] = self.target_var.get().strip()
            save_state(self.state, self.config_path)
            self.set_status("Working auth path saved.")

        def save_auto(self) -> None:
            self.state["auto_switch"] = bool(self.auto_var.get())
            save_state(self.state, self.config_path)
            self.set_status("Auto switch is on." if self.auto_var.get() else "Auto switch is off.")

        def selected_profile(self) -> tuple[int, dict[str, str]] | None:
            selection = self.tree.selection()
            if not selection:
                return None
            index = int(selection[0])
            profiles = self.state.get("profiles", [])
            if index < 0 or index >= len(profiles):
                return None
            return index, profiles[index]

        def refresh_profiles(self) -> None:
            selected = self.selected_profile()
            selected_index = selected[0] if selected else None
            for item in self.tree.get_children():
                self.tree.delete(item)

            active = self.state.get("active_profile", "")
            for index, profile in enumerate(self.state.get("profiles", [])):
                name = profile.get("name", "")
                display_name = f"* {name}" if name == active else name
                self.tree.insert("", "end", iid=str(index), values=(display_name, profile.get("switch_time", ""), profile.get("path", "")))
                if selected_index == index:
                    self.tree.selection_set(str(index))

        def add_profile(self) -> None:
            dialog = ProfileDialog(self, "Add user")
            self.wait_window(dialog)
            if dialog.result:
                self.state.setdefault("profiles", []).append(dialog.result)
                save_state(self.state, self.config_path)
                self.refresh_profiles()
                self.set_status(f"Added {dialog.result['name']}.")

        def edit_profile(self) -> None:
            selected = self.selected_profile()
            if not selected:
                self.set_status("Select a user to edit.")
                return
            index, profile = selected
            dialog = ProfileDialog(self, "Edit user", profile)
            self.wait_window(dialog)
            if dialog.result:
                self.state["profiles"][index] = dialog.result
                save_state(self.state, self.config_path)
                self.refresh_profiles()
                self.tree.selection_set(str(index))
                self.set_status(f"Updated {dialog.result['name']}.")

        def remove_profile(self) -> None:
            selected = self.selected_profile()
            if not selected:
                self.set_status("Select a user to remove.")
                return
            index, profile = selected
            name = profile.get("name", "this user")
            if not messagebox.askyesno(APP_NAME, f"Remove {name}?", parent=self):
                return
            self.state["profiles"].pop(index)
            if self.state.get("active_profile") == name:
                self.state["active_profile"] = ""
            save_state(self.state, self.config_path)
            self.refresh_profiles()
            self.set_status(f"Removed {name}.")

        def activate_selected(self) -> None:
            selected = self.selected_profile()
            if not selected:
                self.set_status("Select a user to activate.")
                return
            self.activate_profile(selected[1], automatic=False)

        def activate_profile(self, profile: dict[str, str], automatic: bool) -> bool:
            try:
                result = activate_profile(Path(profile.get("path", "")), Path(self.target_var.get().strip()), profile.get("name", ""))
            except AuthonError as exc:
                self.set_status(str(exc))
                if not automatic:
                    messagebox.showerror(APP_NAME, str(exc), parent=self)
                return False

            self.state["target_path"] = self.target_var.get().strip()
            self.state["active_profile"] = profile.get("name", "")
            self.state["last_backup"] = str(result.backup_path or "")
            save_state(self.state, self.config_path)
            self.refresh_profiles()
            backup_note = f" Backup: {result.backup_path}" if result.backup_path else " No previous auth to back up."
            prefix = "Auto activated" if automatic else "Activated"
            self.set_status(f"{prefix} {profile.get('name', '')}.{backup_note}")
            return True

        def open_backups(self) -> None:
            target = self.target_var.get().strip()
            if not target:
                self.set_status("Choose the working auth.json path first.")
                return
            backup_dir = Path(target).expanduser().parent / "authon_backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            open_path(backup_dir)

        def check_schedule(self) -> None:
            if self.auto_var.get():
                now = datetime.now()
                current_time = now.strftime("%H:%M")
                today = now.strftime("%Y-%m-%d")
                last_runs = self.state.setdefault("last_auto_runs", {})
                for profile in self.state.get("profiles", []):
                    name = profile.get("name", "")
                    if profile.get("switch_time") == current_time and last_runs.get(name) != today:
                        if self.activate_profile(profile, automatic=True):
                            last_runs[name] = today
                            save_state(self.state, self.config_path)
                        break
            self.after(15000, self.check_schedule)

        def set_status(self, message: str) -> None:
            self.status_var.set(message)

    app = TkAuthonApp()
    app.mainloop()
    return 0


class BrowserAuthonApp:
    def __init__(self) -> None:
        self.config_path = default_config_path()
        self.state = load_state(self.config_path)
        self.lock = threading.RLock()
        self.stop_event = threading.Event()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "config_path": str(self.config_path),
                "target_path": self.state.get("target_path", ""),
                "profiles": self.state.get("profiles", []),
                "active_profile": self.state.get("active_profile", ""),
                "auto_switch": bool(self.state.get("auto_switch", False)),
                "last_backup": self.state.get("last_backup", ""),
            }

    def save(self) -> None:
        save_state(self.state, self.config_path)

    def set_target(self, target_path: str) -> dict[str, Any]:
        with self.lock:
            self.state["target_path"] = target_path.strip()
            self.save()
            return self.snapshot()

    def set_auto(self, enabled: bool) -> dict[str, Any]:
        with self.lock:
            self.state["auto_switch"] = enabled
            self.save()
            return self.snapshot()

    def add_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        profile = normalize_profile(payload)
        with self.lock:
            self.state.setdefault("profiles", []).append(profile)
            self.save()
            return self.snapshot()

    def update_profile(self, index: int, payload: dict[str, Any]) -> dict[str, Any]:
        profile = normalize_profile(payload)
        with self.lock:
            profiles = self.state.setdefault("profiles", [])
            if index < 0 or index >= len(profiles):
                raise AuthonError("Selected user no longer exists.")
            profiles[index] = profile
            self.save()
            return self.snapshot()

    def remove_profile(self, index: int) -> dict[str, Any]:
        with self.lock:
            profiles = self.state.setdefault("profiles", [])
            if index < 0 or index >= len(profiles):
                raise AuthonError("Selected user no longer exists.")
            removed = profiles.pop(index)
            if self.state.get("active_profile") == removed.get("name"):
                self.state["active_profile"] = ""
            self.save()
            return self.snapshot()

    def activate_index(self, index: int, automatic: bool = False) -> dict[str, Any]:
        with self.lock:
            profiles = self.state.setdefault("profiles", [])
            if index < 0 or index >= len(profiles):
                raise AuthonError("Selected user no longer exists.")
            profile = profiles[index]
            target = str(self.state.get("target_path", "")).strip()
            result = activate_profile(Path(profile.get("path", "")), Path(target), profile.get("name", ""))
            self.state["target_path"] = target
            self.state["active_profile"] = profile.get("name", "")
            self.state["last_backup"] = str(result.backup_path or "")
            self.save()
            state = self.snapshot()
            state["message"] = ("Auto activated " if automatic else "Activated ") + profile.get("name", "")
            return state

    def open_backups(self) -> dict[str, Any]:
        with self.lock:
            target = str(self.state.get("target_path", "")).strip()
        if not target:
            raise AuthonError("Choose the working auth.json path first.")
        backup_dir = Path(target).expanduser().parent / "authon_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        open_path(backup_dir)
        state = self.snapshot()
        state["message"] = f"Opened backups: {backup_dir}"
        return state

    def start_scheduler(self) -> None:
        thread = threading.Thread(target=self._schedule_loop, name="authon-scheduler", daemon=True)
        thread.start()

    def _schedule_loop(self) -> None:
        while not self.stop_event.wait(15):
            try:
                self.check_schedule_once()
            except AuthonError:
                pass

    def check_schedule_once(self) -> None:
        with self.lock:
            if not self.state.get("auto_switch"):
                return
            now = datetime.now()
            current_time = now.strftime("%H:%M")
            today = now.strftime("%Y-%m-%d")
            runs = self.state.setdefault("last_auto_runs", {})
            profiles = list(self.state.setdefault("profiles", []))

            for index, profile in enumerate(profiles):
                name = profile.get("name", "")
                if profile.get("switch_time") == current_time and runs.get(name) != today:
                    self.activate_index(index, automatic=True)
                    runs[name] = today
                    self.state["last_auto_runs"] = runs
                    self.save()
                    return


def run_browser_app(host: str, port: int, open_browser: bool) -> int:
    app = BrowserAuthonApp()
    app.start_scheduler()

    handler = make_handler(app)
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{server.server_address[0]}:{server.server_address[1]}/"
    print(f"{APP_NAME} browser UI: {url}")
    print("Press Ctrl+C to stop.")

    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Authon.")
    finally:
        app.stop_event.set()
        server.server_close()
    return 0


def make_handler(app: BrowserAuthonApp) -> type[BaseHTTPRequestHandler]:
    class AuthonHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/" or self.path.startswith("/?"):
                self.send_html(APP_HTML)
                return
            if self.path == "/api/state":
                self.send_json(app.snapshot())
                return
            self.send_error(404)

        def do_POST(self) -> None:
            try:
                payload = self.read_json()
                if self.path == "/api/target":
                    self.send_json(app.set_target(str(payload.get("target_path", ""))))
                elif self.path == "/api/auto":
                    self.send_json(app.set_auto(bool(payload.get("auto_switch", False))))
                elif self.path == "/api/profiles":
                    self.send_json(app.add_profile(payload))
                elif self.path == "/api/profile/update":
                    self.send_json(app.update_profile(int(payload.get("index", -1)), payload))
                elif self.path == "/api/profile/remove":
                    self.send_json(app.remove_profile(int(payload.get("index", -1))))
                elif self.path == "/api/activate":
                    self.send_json(app.activate_index(int(payload.get("index", -1))))
                elif self.path == "/api/open-backups":
                    self.send_json(app.open_backups())
                else:
                    self.send_error(404)
            except AuthonError as exc:
                self.send_json({"error": str(exc)}, status=400)
            except Exception as exc:
                self.send_json({"error": f"Unexpected error: {exc}"}, status=500)

        def read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length == 0:
                return {}
            data = self.rfile.read(length)
            return json.loads(data.decode("utf-8"))

        def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def send_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    return AuthonHandler


def open_path(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
        return
    subprocess.Popen(["xdg-open", str(path)])


APP_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Authon</title>
  <style>
    :root { color-scheme: light; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; background: #f6f7f9; color: #17202a; }
    main { max-width: 1120px; margin: 0 auto; padding: 28px 22px 42px; }
    header { display: flex; justify-content: space-between; gap: 16px; align-items: end; margin-bottom: 22px; }
    h1 { margin: 0; font-size: 32px; letter-spacing: 0; }
    .tagline { margin: 4px 0 0; color: #53606d; }
    .panel { background: #fff; border: 1px solid #dfe4ea; border-radius: 8px; padding: 16px; margin-bottom: 16px; box-shadow: 0 1px 2px rgba(0,0,0,.04); }
    .row { display: flex; gap: 10px; align-items: center; }
    label { display: block; font-size: 13px; color: #53606d; margin-bottom: 6px; }
    input[type="text"] { box-sizing: border-box; width: 100%; padding: 10px 11px; border: 1px solid #cbd3dc; border-radius: 6px; font: inherit; background: #fff; }
    input[type="checkbox"] { inline-size: 16px; block-size: 16px; }
    button { border: 1px solid #b9c3ce; background: #f7f9fb; color: #17202a; border-radius: 6px; padding: 10px 12px; font: inherit; cursor: pointer; white-space: nowrap; }
    button.primary { background: #155e75; border-color: #155e75; color: #fff; font-weight: 650; }
    button.danger { color: #9f1239; }
    button:disabled { opacity: .55; cursor: not-allowed; }
    table { width: 100%; border-collapse: collapse; background: #fff; }
    th, td { border-bottom: 1px solid #edf0f3; padding: 10px; text-align: left; vertical-align: top; }
    th { font-size: 12px; text-transform: uppercase; color: #657282; background: #fbfcfd; }
    td.path { color: #3e4a57; word-break: break-all; }
    .actions { display: flex; gap: 8px; flex-wrap: wrap; }
    .grid { display: grid; grid-template-columns: minmax(160px, 1fr) minmax(260px, 2fr) 120px auto; gap: 10px; align-items: end; }
    .status { min-height: 22px; color: #334155; }
    .muted { color: #64748b; font-size: 13px; }
    .active { font-weight: 750; color: #0f766e; }
    @media (max-width: 760px) {
      header, .row { display: block; }
      .grid { grid-template-columns: 1fr; }
      button { width: 100%; margin-top: 8px; }
      th:nth-child(3), td:nth-child(3) { display: none; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Authon</h1>
        <p class="tagline">Tiny auth particle switcher</p>
      </div>
      <label class="row" style="gap:8px;margin:0;">
        <input id="autoSwitch" type="checkbox">
        <span>Auto switch by time</span>
      </label>
    </header>

    <section class="panel">
      <label for="targetPath">Working auth.json</label>
      <div class="row">
        <input id="targetPath" type="text" placeholder="/path/to/your/app/auth.json">
        <button id="saveTarget">Save</button>
        <button id="openBackups">Backups</button>
      </div>
      <p class="muted">Browser mode uses typed paths. Use the Tk desktop mode for native file pickers when Tk is installed.</p>
    </section>

    <section class="panel">
      <form id="profileForm" class="grid">
        <div>
          <label for="profileName">User</label>
          <input id="profileName" type="text" autocomplete="off" placeholder="Alice">
        </div>
        <div>
          <label for="profilePath">User auth.json</label>
          <input id="profilePath" type="text" autocomplete="off" placeholder="/path/to/alice/auth.json">
        </div>
        <div>
          <label for="profileTime">Time</label>
          <input id="profileTime" type="text" autocomplete="off" placeholder="09:30">
        </div>
        <div class="actions">
          <button id="saveProfile" class="primary" type="submit">Add</button>
          <button id="cancelEdit" type="button" hidden>Cancel</button>
        </div>
      </form>
    </section>

    <section class="panel">
      <table>
        <thead>
          <tr>
            <th>User</th>
            <th>Time</th>
            <th>Auth file</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody id="profiles"></tbody>
      </table>
    </section>

    <p id="status" class="status"></p>
    <p id="configPath" class="muted"></p>
  </main>
  <script>
    let state = null;
    let editIndex = null;

    const $ = (id) => document.getElementById(id);

    async function api(path, payload = null) {
      const options = payload === null ? {} : {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
      };
      const response = await fetch(path, options);
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || response.statusText);
      return data;
    }

    function setStatus(message, isError = false) {
      $("status").textContent = message || "";
      $("status").style.color = isError ? "#be123c" : "#334155";
    }

    async function loadState() {
      state = await api("/api/state");
      render();
    }

    function render() {
      $("targetPath").value = state.target_path || "";
      $("autoSwitch").checked = !!state.auto_switch;
      $("configPath").textContent = "Config: " + state.config_path;
      const body = $("profiles");
      body.innerHTML = "";

      if (!state.profiles.length) {
        const row = document.createElement("tr");
        row.innerHTML = '<td colspan="4" class="muted">No users yet.</td>';
        body.appendChild(row);
        return;
      }

      state.profiles.forEach((profile, index) => {
        const row = document.createElement("tr");
        const active = profile.name === state.active_profile;
        row.innerHTML = `
          <td class="${active ? "active" : ""}">${escapeHtml(active ? "* " + profile.name : profile.name)}</td>
          <td>${escapeHtml(profile.switch_time || "")}</td>
          <td class="path">${escapeHtml(profile.path || "")}</td>
          <td class="actions">
            <button data-action="activate" data-index="${index}">Activate</button>
            <button data-action="edit" data-index="${index}">Edit</button>
            <button class="danger" data-action="remove" data-index="${index}">Remove</button>
          </td>
        `;
        body.appendChild(row);
      });
    }

    function escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    function resetForm() {
      editIndex = null;
      $("profileName").value = "";
      $("profilePath").value = "";
      $("profileTime").value = "";
      $("saveProfile").textContent = "Add";
      $("cancelEdit").hidden = true;
    }

    $("saveTarget").addEventListener("click", async () => {
      try {
        state = await api("/api/target", {target_path: $("targetPath").value});
        render();
        setStatus("Working auth path saved.");
      } catch (error) { setStatus(error.message, true); }
    });

    $("openBackups").addEventListener("click", async () => {
      try {
        state = await api("/api/open-backups", {});
        render();
        setStatus(state.message || "Opened backups.");
      } catch (error) { setStatus(error.message, true); }
    });

    $("autoSwitch").addEventListener("change", async () => {
      try {
        state = await api("/api/auto", {auto_switch: $("autoSwitch").checked});
        render();
        setStatus(state.auto_switch ? "Auto switch is on." : "Auto switch is off.");
      } catch (error) { setStatus(error.message, true); }
    });

    $("profileForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const payload = {
        name: $("profileName").value,
        path: $("profilePath").value,
        switch_time: $("profileTime").value
      };
      try {
        if (editIndex === null) {
          state = await api("/api/profiles", payload);
          setStatus("User added.");
        } else {
          state = await api("/api/profile/update", {...payload, index: editIndex});
          setStatus("User updated.");
        }
        resetForm();
        render();
      } catch (error) { setStatus(error.message, true); }
    });

    $("cancelEdit").addEventListener("click", resetForm);

    $("profiles").addEventListener("click", async (event) => {
      const button = event.target.closest("button");
      if (!button) return;
      const index = Number(button.dataset.index);
      const action = button.dataset.action;
      const profile = state.profiles[index];

      if (action === "edit") {
        editIndex = index;
        $("profileName").value = profile.name || "";
        $("profilePath").value = profile.path || "";
        $("profileTime").value = profile.switch_time || "";
        $("saveProfile").textContent = "Save";
        $("cancelEdit").hidden = false;
        $("profileName").focus();
        return;
      }

      if (action === "remove" && !confirm(`Remove ${profile.name}?`)) return;

      try {
        if (action === "activate") {
          state = await api("/api/activate", {index});
          setStatus(state.message || `Activated ${profile.name}.`);
        } else if (action === "remove") {
          state = await api("/api/profile/remove", {index});
          resetForm();
          setStatus(`Removed ${profile.name}.`);
        }
        render();
      } catch (error) { setStatus(error.message, true); }
    });

    loadState().catch((error) => setStatus(error.message, true));
    setInterval(loadState, 15000);
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(run())
