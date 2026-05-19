# Authon

Authon is a tiny cross-platform desktop switcher for apps that use one active `auth.json`.

You keep one `auth.json` per user somewhere on disk. Authon lets you choose a user profile and copies that user's auth file into your app's working `auth.json` path. Before every replacement, it backs up the previous working auth file.

## Run On Windows

Double-click:

```text
Run Authon.cmd
```

Or run from PowerShell/cmd:

```powershell
cd C:\Projects\Authon
python authon.py
```

## Run On Linux

```bash
cd /path/to/Authon
python3 authon.py
```

You can also run:

```bash
chmod +x run-authon.sh
./run-authon.sh
```

## Run On macOS

```bash
cd /path/to/Authon
python3 authon.py
```

For Finder launch:

```bash
chmod +x "Run Authon.command"
```

Then double-click `Run Authon.command`.

## UI Modes

Authon first tries to open a native Tk desktop window. If Tk is not installed or is broken, it starts a local browser UI instead.

Force browser mode:

```bash
python3 authon.py --browser
```

No external Python packages are required.

## How To Use

1. Set **Working auth.json** to the auth file your real app reads.
2. Click **Add** and create one profile per user.
3. For each profile, choose that user's saved `auth.json`.
4. Select a user and click **Activate**.

Optional: set a profile switch time as `HH:MM` and enable **Auto switch by time**. Authon must be running for scheduled switching to happen.

In browser mode, enter file paths manually because browsers do not expose real local paths through file picker controls.

## Safety

- Authon validates the selected user file as JSON before replacing anything.
- The working auth file is backed up to `authon_backups` beside the working `auth.json`.
- Authon stores paths and profile names only. It does not copy auth contents into its own config.
- Backup files may still contain private auth data, so keep the working auth folder secure.

## Test

```powershell
cd C:\Projects\Authon
python authon.py --check
python -m unittest discover -s tests
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\test_authon.ps1
```

Real-file smoke test with fake demo auth files:

```powershell
python scripts\smoke_real_files.py
```

The demo files live in `demo-real-files`. They use fake token values only.
