# Contributing

Contributions are welcome, especially:

- Support for the newer ISE OpenAPI (`/api/v1/network-device`) as an
  alternative to the legacy ERS API, since Cisco is deprecating ERS in
  favor of OpenAPI on newer versions.
- Reports of ISE ERS schema differences across versions — if `inspect`
  shows different field names than this tool expects on your version,
  please open an issue with the (secret-redacted) JSON output.
- Tests. There currently are none; this was built and validated against a
  live ISE deployment during an active migration rather than with a test
  harness. A mocked-ERS test suite would be a genuinely useful contribution.

## Before submitting a PR

1. Run `python3 -m py_compile ise_tacacs_cutover.py` to confirm it's
   syntactically valid.
2. Update `CHANGELOG.md` with what changed and why.
3. Don't include real device names, IPs, or secrets in examples or commit
   history — use the placeholder style already in `examples/`
   (`CORE-SW-01`, `BRANCH-SW-02`, etc.).

## Reporting schema mismatches

If a command fails with a `400` from ISE, the tool now prints the full ERS
response body. Please include that (with any secret values redacted) in
your issue — it's usually enough to identify the exact field name or enum
value that differs on your ISE version.
