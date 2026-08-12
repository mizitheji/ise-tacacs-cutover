# Changelog

## [0.3.0]
### Fixed
- `disable-radius` no longer attempts to set `authenticationSettings.networkProtocol`
  (not a valid enum on most ISE ERS versions, causes a 400 "Cannot deserialize
  value of type NetworkDevice$NetworkProtocol"). It now removes the entire
  `authenticationSettings` block, matching how `disable-tacacs` already
  handles `tacacsSettings`.
- `disable-radius` now auto-backs up the removed RADIUS settings to
  `backups/radius_settings_backup_<timestamp>.json` before removing them.
- `enable-radius` can restore from that backup file via `--radius-backup`,
  or build a fresh block from a `radius_shared_secret` CSV column.
- All `[FAIL]` output now includes the full ISE ERS response body, not just
  the HTTP status line, to make debugging 400s possible without re-running
  with a debugger attached.

### Added
- `--name` flag on every command to target specific devices within a batch
  CSV without editing the file.
- `disable-tacacs` and `enable-radius` commands (previously only
  `enable-tacacs` and `disable-radius` existed).

## [0.2.0]
### Changed
- Simplified from a three-stage (`stage`/`cutover`/`rollback`) model to a
  direct `enable-tacacs` / `disable-radius` model, since switch-side config
  push is handled externally (e.g. Cisco Catalyst Center) rather than by
  this tool.

## [0.1.0]
### Added
- Initial version: `backup`, `stage`, `cutover`, `rollback` commands using
  the ISE ERS API, built around per-site CSV batches.
