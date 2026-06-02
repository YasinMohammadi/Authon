# Authon

Authon is a small Linux terminal account switcher for apps that read one active `auth.json`.

You keep one saved `auth.json` per account. Authon lets you choose an account in the terminal, copies that account's auth file into the working `auth.json` path, and backs up the previous working file before every replacement.

## Run

```bash
cd /path/to/Authon
python3 authon.py
```

You can also run:

```bash
chmod +x run-authon.sh
./run-authon.sh
```

`python3 authon.py --cli` is accepted too, but CLI mode is the default.

## Controls

- Up/Down arrows: move between accounts.
- Enter: activate the selected account.
- `n`: add an account.
- `e`: edit the selected account.
- `r`: remove the selected account.
- `t`: set the working `auth.json` path.
- `b`: show the backups folder path.
- `q`: quit.

If Authon is run without an interactive terminal, it prints a read-only dashboard instead.

## Account Fields

- `Name`: label shown in the account list.
- `User auth.json`: saved auth file for that account.
- `Expires`: optional `YYYY-MM-DD` date for tracking account expiration.
- `Switch time`: optional `HH:MM` value retained for stored profile metadata.

## Safety

- Authon validates the selected account file as JSON before replacing anything.
- The working auth file is backed up to `authon_backups` beside the working `auth.json`.
- Authon stores paths, profile names, optional expiration dates, and optional switch times only. It does not copy auth contents into its own config.
- Backup files may still contain private auth data, so keep the working auth folder secure.

## Test

```bash
cd /path/to/Authon
python3 authon.py --check
python3 -m unittest discover -s tests
python3 scripts/smoke_real_files.py
```

The smoke test uses fake demo auth files in `demo-real-files`.
