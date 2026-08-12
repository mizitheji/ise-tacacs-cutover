# ise-tacacs-cutover

![CI](https://github.com/<your-org>/ise-tacacs-cutover/actions/workflows/ci.yml/badge.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)

A small, careful CLI tool for migrating Cisco ISE Network Device objects from
RADIUS to TACACS+ device administration — in batches, with automatic
backups, a dry validation gate, and per-device rollback.

Built for a real migration of 100+ devices where switch-side `aaa` config is
pushed separately by Cisco Catalyst Center (DNAC). This tool only touches
the **ISE side** (Network Device objects via the ERS API) — it does not
touch switches directly.

## Why this exists

Migrating AAA protocols across a large device fleet is exactly the kind of
change where a slip can lock you out of your own network gear. This tool is
built around three principles:

1. **Never disable a working protocol until the new one is proven.** Every
   command defaults to additive changes; nothing destructive happens without
   an explicit step and (for the risky ones) a confirmation prompt.
2. **Always back up before changing state.** `enable-tacacs` and
   `disable-radius` write a timestamped JSON snapshot before touching
   anything, so you can restore exactly what was there.
3. **Batch by site, not by device count.** Target one location/NDG group at
   a time via CSV files, so a bad batch affects one site, not your whole
   estate.

## Requirements

- Python 3.8+
- An ISE ERS API account (Administration > System > Admin Access >
  Administrators, with the ERS Admin role) and ERS enabled
  (Administration > System > Settings > ERS Settings)
- Network reachability to ISE on TCP/9060

## Installation

```bash
git clone https://github.com/mizitheji/ise-tacacs-cutover.git
cd ise-tacacs-cutover
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Quick start

```bash
# 1. Confirm the ERS JSON schema matches this tool's assumptions
python3 ise_tacacs_cutover.py --ise-host https://ise.example.com:9060 \
  --user ise-api-svc inspect --name SOME-TEST-DEVICE

# 2. Enable TACACS+ for a site batch (RADIUS stays on as fallback)
python3 ise_tacacs_cutover.py --ise-host https://ise.example.com:9060 \
  --user ise-api-svc enable-tacacs --csv examples/central.csv.example

# 3. Hand off to your network config tool (e.g. Catalyst Center) to push
#    the new aaa config to that batch's switches, then check ISE Live Logs
#    for successful TACACS+ authentications.

# 4. Once verified, disable RADIUS for that batch
python3 ise_tacacs_cutover.py --ise-host https://ise.example.com:9060 \
  --user ise-api-svc disable-radius --csv examples/central.csv.example
```

## CSV format

One row per device. Only the columns a given command needs are read; extra
columns are ignored, so a single CSV per batch works for every command.

```csv
device_name,tacacs_shared_secret,radius_shared_secret
CORE-SW-01,Tac@cs2026Central,
SW-CENTRAL-02,Tac@cs2026Central,
```

- `device_name` — must exactly match the **Name** field of the Network
  Device object in ISE (case-sensitive).
- `tacacs_shared_secret` — required by `enable-tacacs`. Must match the key
  pushed to the device's `tacacs-server key`.
- `radius_shared_secret` — optional, only used by `enable-radius` as a
  fallback if no `--radius-backup` file is supplied.

See `examples/central.csv.example` for a template.

## Commands

| Command           | What it does                                                        | Destructive? |
|-------------------|----------------------------------------------------------------------|:---:|
| `inspect`         | Prints raw JSON for one device — run this first to verify schema     | No |
| `enable-tacacs`   | Adds TACACS+ settings; auto-backs up first; RADIUS untouched         | No |
| `disable-tacacs`  | Removes TACACS+ settings; RADIUS untouched                           | Yes |
| `enable-radius`   | Restores/adds RADIUS settings; TACACS+ untouched                     | No |
| `disable-radius`  | Removes RADIUS settings; auto-backs up first; asks for confirmation  | Yes |
| `rollback`        | Restores full device state from a backup JSON file                  | No |

Every command accepts an optional `--name` flag to target specific devices
within a CSV, space-separated, without editing the file:

```bash
python3 ise_tacacs_cutover.py --ise-host https://ise.example.com:9060 \
  --user ise-api-svc enable-tacacs --csv examples/central.csv.example --name CORE-SW-01
```

Omit `--name` to process every row in the CSV.

## Recommended rollout sequence per site

```
inspect (once)
   |
   v
enable-tacacs  --------> auto-backup written to backups/
   |
   v
[Catalyst Center pushes new aaa config to that batch's switches]
   |
   v
Verify in ISE Live Logs: TACACS+ auth passing?
   |
  yes                              no
   |                                |
   v                                v
disable-radius                 rollback (from the backup written
                                by enable-tacacs)
```

## Rollback

Two ways to undo a change:

**Full snapshot restore** (exact pre-migration state, written automatically
by `enable-tacacs`):

```bash
python3 ise_tacacs_cutover.py --ise-host https://ise.example.com:9060 \
  --user ise-api-svc rollback --csv examples/central.csv.example \
  --backup backups/pre_migration_20260810_143012.json
```

**Single-field restore** (RADIUS settings only, written automatically by
`disable-radius`):

```bash
python3 ise_tacacs_cutover.py --ise-host https://ise.example.com:9060 \
  --user ise-api-svc enable-radius --csv examples/central.csv.example \
  --radius-backup backups/radius_settings_backup_20260810_150501.json
```

Both accept `--name` to restore a single device instead of the whole batch.

## Out-of-band fallback

This tool can only help if you can still reach ISE's API and the network
device is still reachable at all. Before starting each site's cutover,
confirm console/OOB access and local enable credentials work on a sample
device in that batch — that's your last resort if a device becomes
completely unreachable over the network.

## Known ISE ERS quirks

- `authenticationSettings.networkProtocol` is **not** a settable enum on
  most ISE versions for toggling RADIUS on/off — attempting to PUT a value
  like `"TACACS"` into it returns a 400 with `Cannot deserialize value of
  type NetworkDevice$NetworkProtocol`. This tool instead adds/removes the
  entire `authenticationSettings` block, mirroring how `tacacsSettings` is
  handled. Always run `inspect` on your own ISE version first — field names
  have shifted across ISE 2.x/3.x and ERS vs. the newer OpenAPI
  (`/api/v1/network-device`).

## Security notes

- Never commit CSV files containing real shared secrets, or files under
  `backups/`, to version control. Both are excluded in `.gitignore`.
- Consider per-device or per-site TACACS+/RADIUS secrets rather than one
  shared key across your whole estate — a single leaked key otherwise
  exposes every migrated device at once.
- The script disables TLS certificate verification (`verify=False`) to
  accommodate common self-signed ISE deployments. If your ISE has a valid
  CA-signed certificate, remove that line and get proper verification.

## License

MIT — see [LICENSE](LICENSE).

## Security

See [SECURITY.md](SECURITY.md) for how secrets are handled and how to
report a vulnerability.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
