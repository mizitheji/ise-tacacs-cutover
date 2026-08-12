# Security Policy

## Reporting a vulnerability

If you find a security issue in this tool itself (e.g. how it handles
credentials, TLS, or API responses), please **do not open a public issue**.
Instead, email the maintainer directly or use GitHub's private vulnerability
reporting (Security tab > Report a vulnerability) so it can be addressed
before details are public.

## Handling of secrets — please read before using this tool

This tool is designed for operators who already hold valid ISE ERS
credentials and TACACS+/RADIUS shared secrets. It does not store, transmit,
or log credentials anywhere except:

- The ERS password is prompted interactively (`getpass`) and held only in
  memory for the life of the process.
- TACACS+/RADIUS shared secrets you supply via CSV are sent to the ISE ERS
  API over HTTPS and are also written to local backup JSON files under
  `backups/` so they can be restored later. **These backup files and any
  CSV containing real secrets must never be committed to version control**
  — both are excluded by `.gitignore`, but you are responsible for not
  overriding that or copying them elsewhere insecurely.

## TLS verification

The script disables certificate verification (`verify=False`) by default to
accommodate the common case of a self-signed ISE deployment. If your ISE
has a CA-signed certificate, remove that line in `ise_tacacs_cutover.py` and
verify properly — running with verification disabled against an untrusted
network path exposes your ERS credentials and shared secrets to interception.

## Scope

This tool only modifies ISE Network Device objects via the ERS API. It does
not touch switches, routers, or any other network infrastructure directly.
