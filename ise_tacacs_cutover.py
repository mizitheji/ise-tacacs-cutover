#!/usr/bin/env python3
"""
ISE-only RADIUS -> TACACS+ cutover tool
========================================

Scope: ISE Network Device objects only. Switch-side aaa config push is
handled separately by Catalyst Center - not this script.

RECOMMENDED SEQUENCE per device/site batch:
  1. python3 ise_tacacs_cutover.py enable-tacacs --csv batch1.csv
       -> Adds TACACS+ settings. RADIUS is left ENABLED (this is your live fallback
          while Catalyst Center pushes the new switch config).
  2. [Catalyst Center pushes new aaa config to that batch's switches]
  3. Check ISE Live Logs for successful TACACS+ auth from those devices.
  4. python3 ise_tacacs_cutover.py disable-radius --csv batch1.csv
       -> Only run this once step 3 is confirmed. This is the point of no easy
          return without rollback, so don't skip verification.

TARGETING SPECIFIC DEVICES WITHIN A CSV (without editing the file):
  Every command accepts an optional --name flag, space-separated, e.g.:
    python3 ise_tacacs_cutover.py enable-tacacs --csv central.csv --name CORE-SW-01
    python3 ise_tacacs_cutover.py enable-tacacs --csv central.csv --name CORE-SW-01 BRANCH-SW-02
  If --name is omitted, every row in the CSV is processed (original behavior).

ALL SIX COMMANDS:
  inspect          Print raw JSON for one device (schema check, run first)
  enable-tacacs    Add TACACS+ settings, auto-backs up first, RADIUS stays on
  disable-tacacs   Remove TACACS+ settings, RADIUS untouched
  enable-radius    Re-enable RADIUS settings, TACACS+ untouched (optional
                    radius_shared_secret column in CSV to also reset the secret)
  disable-radius   Disable RADIUS (run only after validating TACACS+ works)
  rollback         Restore devices to an exact prior snapshot from a backup file

IF SOMETHING BREAKS AT ANY POINT:
  python3 ise_tacacs_cutover.py rollback --csv batch1.csv --backup backups/pre_migration_<ts>.json
       -> Restores the exact original RADIUS+TACACS state for those devices from
          the backup taken automatically on first run of enable-tacacs.
  OR, for a quick single-protocol flip without a full backup file:
       python3 ise_tacacs_cutover.py enable-radius --csv batch1.csv
       python3 ise_tacacs_cutover.py disable-tacacs --csv batch1.csv

OUT-OF-BAND FALLBACK (independent of this script):
  If a device becomes completely unreachable via AAA (both ISE-side rollback
  and Catalyst Center are irrelevant if you can't reach the box at all), you
  need console/OOB access and local enable credentials as the last resort.
  Confirm those work BEFORE starting the migration on each site, not after.

VERIFY SCHEMA FIRST:
  python3 ise_tacacs_cutover.py inspect --name SOME-TEST-DEVICE
  Confirm field names (authenticationSettings.*, tacacsSettings.*) match this
  script - ISE ERS schema differs slightly by version.

Requires: pip install requests --break-system-packages
"""

import argparse
import csv
import getpass
import json
import os
import sys
from datetime import datetime

import requests
from requests.auth import HTTPBasicAuth

requests.packages.urllib3.disable_warnings()

ISE_BASE = None
HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}
BACKUP_DIR = "backups"
DEFAULT_TACACS_CONNECT_MODE = "ON_LEGACY"  # verify via `inspect`


def api_session(user, password):
    s = requests.Session()
    s.auth = HTTPBasicAuth(user, password)
    s.headers.update(HEADERS)
    s.verify = False
    return s


def find_device_id_by_name(session, name):
    r = session.get(f"{ISE_BASE}/ers/config/networkdevice?filter=name.EQ.{name}")
    r.raise_for_status()
    resources = r.json().get("SearchResult", {}).get("resources", [])
    return resources[0]["id"] if resources else None


def get_device(session, device_id):
    r = session.get(f"{ISE_BASE}/ers/config/networkdevice/{device_id}")
    r.raise_for_status()
    return r.json()["NetworkDevice"]


def put_device(session, device_id, payload):
    r = session.put(
        f"{ISE_BASE}/ers/config/networkdevice/{device_id}",
        data=json.dumps({"NetworkDevice": payload}),
    )
    r.raise_for_status()
    return r


def _read_csv(path, names=None):
    """Read the batch CSV. If `names` is given, only return rows whose device_name
    matches one of those names (case-sensitive, must match ISE device name exactly)."""
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    if names:
        wanted = set(names)
        rows = [r for r in rows if r.get("device_name") in wanted]
        found = {r["device_name"] for r in rows}
        missing = wanted - found
        for m in missing:
            print(f"  [WARN] {m}: not found in {path}, skipping")
    return rows


def _backup_devices(session, names, label):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(BACKUP_DIR, f"{label}_{ts}.json")
    snapshot = []
    for name in names:
        device_id = find_device_id_by_name(session, name)
        if device_id:
            snapshot.append(get_device(session, device_id))
        else:
            print(f"  [WARN] {name}: not found, skipped in backup")
    with open(path, "w") as f:
        json.dump(snapshot, f, indent=2)
    print(f"Backup written: {path}")
    return path


def _backup_field(session, names, field_name, label):
    """Save just one field (e.g. 'authenticationSettings') per device to a small JSON
    file, keyed by device name, so it can be restored precisely later without a full
    device snapshot."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(BACKUP_DIR, f"{label}_{ts}.json")
    snapshot = {}
    for name in names:
        device_id = find_device_id_by_name(session, name)
        if not device_id:
            continue
        device = get_device(session, device_id)
        if device.get(field_name):
            snapshot[name] = device[field_name]
    with open(path, "w") as f:
        json.dump(snapshot, f, indent=2)
    print(f"Backup of '{field_name}' written: {path}")
    return path


def cmd_inspect(session, args):
    device_id = find_device_id_by_name(session, args.name)
    if not device_id:
        print(f"Device '{args.name}' not found.")
        sys.exit(1)
    print(json.dumps(get_device(session, device_id), indent=2))


def cmd_enable_tacacs(session, args):
    rows = _read_csv(args.csv, args.name)
    names = [r["device_name"] for r in rows]
    print(f"Backing up {len(names)} devices before making any change...")
    _backup_devices(session, names, "pre_migration")

    for row in rows:
        name, secret = row["device_name"], row["tacacs_shared_secret"]
        device_id = find_device_id_by_name(session, name)
        if not device_id:
            print(f"  [SKIP] {name}: not found in ISE")
            continue
        device = get_device(session, device_id)
        device["tacacsSettings"] = {
            "sharedSecret": secret,
            "connectModeOptions": DEFAULT_TACACS_CONNECT_MODE,
        }
        # RADIUS settings intentionally left untouched here - that's the fallback
        try:
            put_device(session, device_id, device)
            print(f"  [OK]   {name}: TACACS+ enabled, RADIUS still active as fallback")
        except requests.HTTPError as e:
            print(f"  [FAIL] {name}: {e}\n         Response: {e.response.text if e.response is not None else '(no body)'}")


def cmd_disable_radius(session, args):
    rows = _read_csv(args.csv, args.name)
    print("Have you confirmed successful TACACS+ auth in Live Logs for these devices? (yes/no)")
    if input("> ").strip().lower() != "yes":
        print("Aborted. Verify in Live Logs first.")
        return

    names = [r["device_name"] for r in rows]
    backup_path = _backup_field(session, names, "authenticationSettings", "radius_settings_backup")

    for row in rows:
        name = row["device_name"]
        device_id = find_device_id_by_name(session, name)
        if not device_id:
            print(f"  [SKIP] {name}: not found in ISE")
            continue
        device = get_device(session, device_id)
        device.pop("authenticationSettings", None)
        try:
            put_device(session, device_id, device)
            print(f"  [OK]   {name}: RADIUS disabled")
        except requests.HTTPError as e:
            print(f"  [FAIL] {name}: {e}\n         Response: {e.response.text if e.response is not None else '(no body)'}")
    print(f"(RADIUS settings backed up to {backup_path} - use with `enable-radius --radius-backup` to restore exactly)")


def cmd_disable_tacacs(session, args):
    """Remove/disable TACACS+ settings on devices in the CSV. RADIUS is left untouched."""
    rows = _read_csv(args.csv, args.name)
    for row in rows:
        name = row["device_name"]
        device_id = find_device_id_by_name(session, name)
        if not device_id:
            print(f"  [SKIP] {name}: not found in ISE")
            continue
        device = get_device(session, device_id)
        device.pop("tacacsSettings", None)  # verify via `inspect` whether your ISE needs a null/empty object instead
        try:
            put_device(session, device_id, device)
            print(f"  [OK]   {name}: TACACS+ disabled")
        except requests.HTTPError as e:
            print(f"  [FAIL] {name}: {e}\n         Response: {e.response.text if e.response is not None else '(no body)'}")


def cmd_enable_radius(session, args):
    """Re-enable RADIUS settings on devices in the CSV. TACACS+ is left untouched.

    Two ways to provide the RADIUS settings to restore:
      1. --radius-backup <file>  : exact restore from a file written by `disable-radius`
      2. radius_shared_secret column in the CSV : builds a minimal fresh authenticationSettings block
    If neither is available for a device, that device is skipped with a warning.
    """
    rows = _read_csv(args.csv, args.name)
    backup_data = {}
    if args.radius_backup:
        with open(args.radius_backup) as f:
            backup_data = json.load(f)

    for row in rows:
        name = row["device_name"]
        radius_secret = row.get("radius_shared_secret")
        device_id = find_device_id_by_name(session, name)
        if not device_id:
            print(f"  [SKIP] {name}: not found in ISE")
            continue
        device = get_device(session, device_id)

        if name in backup_data:
            device["authenticationSettings"] = backup_data[name]
        elif radius_secret:
            device["authenticationSettings"] = {"radiusSharedSecret": radius_secret}
        else:
            print(f"  [SKIP] {name}: no --radius-backup entry and no radius_shared_secret column value")
            continue

        try:
            put_device(session, device_id, device)
            print(f"  [OK]   {name}: RADIUS enabled")
        except requests.HTTPError as e:
            print(f"  [FAIL] {name}: {e}\n         Response: {e.response.text if e.response is not None else '(no body)'}")


def cmd_rollback(session, args):
    with open(args.backup) as f:
        backup_list = json.load(f)
    backup_by_name = {d["name"]: d for d in backup_list}

    rows = _read_csv(args.csv, args.name)
    for row in rows:
        name = row["device_name"]
        original = backup_by_name.get(name)
        if not original:
            print(f"  [SKIP] {name}: not in backup file")
            continue
        try:
            put_device(session, original["id"], original)
            print(f"  [OK]   {name}: restored to pre-migration state")
        except requests.HTTPError as e:
            print(f"  [FAIL] {name}: {e}\n         Response: {e.response.text if e.response is not None else '(no body)'}")


def main():
    global ISE_BASE
    parser = argparse.ArgumentParser(description="ISE-only RADIUS -> TACACS+ cutover")
    parser.add_argument("--ise-host", required=True, help="e.g. https://ise.example.com:9060")
    parser.add_argument("--user", required=True)
    sub = parser.add_subparsers(dest="command", required=True)

    p_i = sub.add_parser("inspect", help="Print raw JSON for one device (run FIRST)")
    p_i.add_argument("--name", required=True)

    p_e = sub.add_parser("enable-tacacs", help="Add TACACS+ settings, auto-backs up first, RADIUS stays on")
    p_e.add_argument("--csv", required=True)
    p_e.add_argument("--name", nargs="+", default=None,
                      help="Optional: only process these device_name(s) from the CSV, space-separated. Default: all rows.")

    p_d = sub.add_parser("disable-radius", help="Disable RADIUS (run only after validating TACACS+)")
    p_d.add_argument("--csv", required=True)
    p_d.add_argument("--name", nargs="+", default=None,
                      help="Optional: only process these device_name(s) from the CSV, space-separated. Default: all rows.")

    p_dt = sub.add_parser("disable-tacacs", help="Disable TACACS+, leave RADIUS untouched")
    p_dt.add_argument("--csv", required=True)
    p_dt.add_argument("--name", nargs="+", default=None,
                       help="Optional: only process these device_name(s) from the CSV, space-separated. Default: all rows.")

    p_er = sub.add_parser("enable-radius", help="Re-enable RADIUS, leave TACACS+ untouched")
    p_er.add_argument("--csv", required=True)
    p_er.add_argument("--radius-backup", default=None,
                       help="Path to a radius_settings_backup_<ts>.json file written by `disable-radius`, for exact restore")
    p_er.add_argument("--name", nargs="+", default=None,
                       help="Optional: only process these device_name(s) from the CSV, space-separated. Default: all rows.")

    p_r = sub.add_parser("rollback", help="Restore devices from a backup JSON file")
    p_r.add_argument("--csv", required=True)
    p_r.add_argument("--backup", required=True)
    p_r.add_argument("--name", nargs="+", default=None,
                      help="Optional: only process these device_name(s) from the CSV, space-separated. Default: all rows.")

    args = parser.parse_args()
    ISE_BASE = args.ise_host.rstrip("/")
    password = getpass.getpass(f"ERS password for {args.user}: ")
    session = api_session(args.user, password)

    {
        "inspect": cmd_inspect,
        "enable-tacacs": cmd_enable_tacacs,
        "disable-radius": cmd_disable_radius,
        "disable-tacacs": cmd_disable_tacacs,
        "enable-radius": cmd_enable_radius,
        "rollback": cmd_rollback,
    }[args.command](session, args)


if __name__ == "__main__":
    main()
