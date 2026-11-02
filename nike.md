# Nike+ / Nike Run Club library specification

Planned implementation: `src/nike/sync.py`, an independent uv Python launcher
using **[yasoob/nrc-exporter](https://github.com/yasoob/nrc-exporter)**. Use the
library for Nike access and follow the
[common data requirements](README.md#integration-specification) for retained runs.
The launcher is not implemented yet.

## Planned command and dependency

From the repository root:

```sh
uv run src/nike/sync.py
```

Prefer uv Python with its own dependency declaration and a Python version
compatible with the library. Pin a tested GitHub revision containing the current
fixes. The [PyPI release](https://pypi.org/project/nrc-exporter/) remains version
0.0.7 from July 2020; the GitHub source has later fixes, including the
[updated login flow](https://github.com/yasoob/nrc-exporter/pull/28).

Keep the launcher small: invoke the library through supported interfaces, select
local files, and organize its output. Let the library own its Nike API access,
authentication flow, pagination, and token renewal behavior. Do not implement a
parallel Nike HTTP client, custom browser-token extraction, or custom refresh
flow, and do not require shared Python code with Strava or an MCP server.

## Library authentication and token file

- Follow the selected library version's documented authentication instructions.
  Token acquisition and renewal belong to the library's workflow. If that
  workflow requires manual input, use it; do not promise automatic refresh the
  library does not provide.
- Store reusable Nike token material in **`data/nike-tokens.json`**, following the
  [data-repository exclusions and permission checks](README.md#credential-files-under-data).
  Use the library's supported credential/token input interface. If it does not
  manage a cache file, the launcher may bridge reading and saving this selected
  local file without implementing login or renewal itself. Do not assume the
  library already supports a configurable cache or invent a new auth protocol.
- Do not use Strava credentials or MCP token files. Preserve progress when the
  library reports rejected credentials, and follow its documented recovery flow.
  Avoid verbose/debug modes that expose credentials in library output.

## Importing library output

Use the library's supported export and incremental features. Its working and
staging directories must be under `data/`, so downloaded personal files never
land in this public repository's source directories.

Apply the [history and refresh requirements](README.md#history-and-incremental-imports)
using library options where supported. If the library fetches a wider archive,
select the retained period from its output and document the extra download;
do not reimplement private endpoints to add an unsupported date filter.

Retain available raw activity JSON as
`data/run-YYYY-MM-DD-nike-<id>/nike.json` using stable Nike IDs. Preserve library
fields and record the library revision and any timezone fallback in
`import.json`. Reuse valid exported records and preserve notes on subsequent
imports. Conversion to GPX is not required to retain a source run.

Check the selected version's actual behavior for manual, indoor, GPS-free, and
missing-metric activities. Report library exclusions and failures rather than
silently treating missing activities as rest days or claiming complete coverage.
Compatibility and Nike authentication fixes should be handled upstream; the
launcher should surface limitations without growing a competing client.

## Verification and scope

Smoke-test the pinned library version with uv, its credential-file bridge, and
its documented login or renewal flow. Verify ignored token files and permissions,
private staging paths, source IDs, date selection, reruns, incomplete records,
and preservation of notes. Validate available outdoor and indoor/manual examples
without requiring the oldest archive to succeed.

Use the library's own documentation for Nike protocol details. This spec does
not reproduce its endpoints or token-extraction instructions. Archive-file
support or another library can be evaluated separately if the selected library
cannot supply the required data.
