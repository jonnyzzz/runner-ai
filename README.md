# Runner AI

An experiment in using AI to support marathon training, grounded in an athlete's
activity history, goals, and feedback. The aim is to build reusable tools for my
own training that other runners can adapt.

> This is an experimental project, not professional training or medical advice.
> Use it at your own risk and consult qualified coaches or medical professionals
> where appropriate.

## Current status

The [Nike+ fetcher](nike.md) is implemented and uses the pinned `nrc-exporter`
library. Strava API, MCP integration, and agent coaching remain specifications.

With a separate Git checkout prepared under `data/`, start the Nike library's
login flow and fetch runs:

```sh
uv run --locked src/nike/sync.py --login --timezone Europe/Berlin --log
```

Choose the timezone appropriate for your training history. See
[Nike setup and usage](nike.md#first-fetch) for prerequisites, authentication,
incremental imports, private logs, and limitations.

## Planned workflow

1. Keep code and instructions in this repository. Prepare a separate private
   repository named with a `-data` suffix, such as `runner-ai-data`, checked out
   under `data/`. Repository provisioning is a later milestone.
2. Record goals and planned races in `data/GOALS.md`. Add user-provided context
   about previous races, injuries, major breaks, and missing records.
3. Import runs through one of the integrations below, using its own supported
   authentication and fetching approach.
4. Let an agent analyze source records and ask about missing information. Keep
   generated analysis in the ignored `slop/` directory.
5. Commit source records and explicit user inputs to the private data repository.
   Credential files stay under `data/` but are excluded from Git. Automatic
   commits and pushes by import commands are later work.

## Integration specification

| Technology | Approach | Specification |
| --- | --- | --- |
| Strava API | Independent uv Python script in `src/strava/` | [Custom importer](strava.md#custom-importer-strava-api) |
| Strava MCP | Selected MCP server's tools, configuration, and authentication | [MCP integration](strava.md#mcp-integration) |
| Nike+ / Nike Run Club | Implemented uv Python fetcher in `src/nike/`, using the Nike+ library | [nike.md](nike.md) |

Keep each implementation independent. Prefer [uv Python scripts](https://docs.astral.sh/uv/guides/scripts/)
for local code, with dependencies and a compatible Python version declared per
integration. MCP uses its server's supported runtime. There is no required shared
Python package, common uv project, common CLI, or shared authentication engine.

The requirements below describe common data outcomes. Each technology uses its
own library, protocol, pagination, retry behavior, and configuration. Provider
files own those implementation details and link back to these requirements.

### History and incremental imports

- Initially retain **the most recent 12 calendar months**. Save the initial
  start date for subsequent imports; it is a backfill boundary, not a rolling
  deletion policy. Allow an earlier date or an explicit all-history import.
- Keep repeat imports incremental: reuse valid existing records, retrieve missing
  or failed records, and avoid rewriting identical files. Use the selected
  technology's supported incremental and refresh mechanisms.
- Provide a way to refresh existing records in the selected period. A full
  refresh does not implicitly expand the selected period to all history.
- Account for late uploads and corrections. Document coverage limitations when
  an upstream server or library cannot discover them automatically; do not claim
  that stopping at the first known run establishes complete coverage.
- Preserve completed records on interruption. Report failed or unavailable runs
  and retry them on a later import. Do not mark an incomplete period as fully
  synchronized or treat authentication failure as an empty history.
- Apply the period as early as the integration supports. A library may fetch a
  wider archive before local selection; keep its staging files under `data/`
  and make that limitation explicit.

For planning, prioritize the latest 8–12 weeks and use the year for broader
context. Extend to two years when an earlier training cycle is useful; older
race results and relevant history can be supplied as user inputs. These are
practical defaults, not established minimums: research has examined
[16-week training blocks](https://www.frontiersin.org/journals/physiology/articles/10.3389/fphys.2021.669884/full)
and [training across the preceding year](https://link.springer.com/article/10.1007/s40279-025-02304-4),
without establishing a required archive length for individual planning.

### Run records and layout

Store source records under:

```text
data/run-YYYY-MM-DD-<provider>-<activity-id>/
```

- Import only runs. Exclude unrelated sports from retained run records. Preserve
  manual, treadmill, and GPS-free runs when the integration supplies them; report
  upstream omissions rather than silently claiming complete coverage.
- Use a trustworthy source-local date. If only a UTC instant is available, use
  an explicitly configured athlete timezone and record that fallback. Never
  silently use the computer's timezone for historical runs.
- Identify records by `(provider, activity-id)`, not the date or title. Validate
  IDs used as paths. Reuse an existing folder if its source date is corrected;
  multiple same-day runs remain distinct.
- Preserve the source fields, units, and representation provided by the selected
  integration. Keep factual provenance in `import.json`, including which
  technology supplied the record. Put operational state outside source JSON.
- Keep API and MCP representations of the same Strava activity in the same
  activity folder but in separate source files. They represent one run, not two.
- Validate records before accepting them and write project-owned files
  atomically. Missing GPS or optional metrics alone does not invalidate a run.
  Error responses must not become activity records.
- Preserve athlete notes, `GOALS.md`, and other source files. Never automatically
  delete run folders. Absence from a listing does not prove deletion, and missing
  records mean unknown coverage rather than rest days.
- Preserve both providers' evidence when the same run appears in two services.
  Report potential matches using source links, UTC start, duration, and distance;
  resolve duplicates before counting them in training totals.

### Credential files under data

Store tokens in selected files **inside the private `data/` checkout**. Each
technology owns its credential format, acquisition, renewal, and configuration:

| Integration | Selected storage | Credential owner |
| --- | --- | --- |
| Custom Strava API importer | `data/strava-tokens.json` | The custom OAuth client |
| Nike+ library | `data/nike-tokens.json` | The library's supported token workflow; the launcher only bridges local file storage if needed |
| Strava MCP | `data/strava-mcp/`, using the selected server's native filenames | The MCP server |

The MCP server does not use the custom importer's `strava-tokens.json`. Configure
its own supported credential paths under `data/strava-mcp/` and record the exact
filenames when selecting the server. Use a server that supports this location;
do not silently place its credentials elsewhere or invent its cache format.

The parent repository's `/data/` ignore rule does not exclude files from commits
inside the private data repository. Before credentials are stored, require these
entries in **`data/.gitignore`**. Track the ignore rules as configuration in the
private repository:

```gitignore
/strava-tokens.json
/nike-tokens.json
/strava-mcp/
/.sync-state/
```

Enforce exclusion and permission checks in each local integration: verify the
credential paths are ignored within the data checkout and are not tracked;
restrict secret files to `0600` and private credential directories to `0700` on
systems supporting those permissions. Refuse to persist secrets when these
checks fail. MCP configuration must meet the same storage requirement through
the server's supported settings and security guidance.

Keep tokens out of run files, agent output, logs, and Git history. Store separate
operational state under `data/.sync-state/<integration>/` if the integration needs
it, bound to the account and selected history. Each integration retains its own
state format; account labels alone do not verify authenticated identity.

### Implementation and verification

Implement and verify each integration independently using its provider spec.
Check the common outcomes: selected history, run-only output, stable IDs and
local dates, repeated imports, partial failure and retry, preserved notes,
reported missing metrics, duplicate handling, and credential exclusion and
permissions. Add authentication and compatibility checks appropriate to the
chosen API, MCP server, or library.

The Nike implementation imports available source activity records. Additional
stream requests, conversion/export, agent coaching, repository provisioning, and
Git automation are later work. Declare and lock dependencies separately as
needed and ignore generated Python environments and caches.

## Intended directory layout

The Nike script and its dependency lock are implemented; Strava files are planned.
The data checkout has its own ignore rules.

```text
runner-ai/
├── README.md                    # Common workflow and data requirements
├── strava.md                    # Separate Strava API and MCP flows
├── nike.md                      # Nike+ library integration
├── LICENSE
├── .gitignore
├── src/
│   ├── strava/
│   │   └── sync.py              # Planned custom Strava API uv script
│   └── nike/
│       ├── sync.py              # Implemented Nike+ fetcher
│       └── sync.py.lock         # Pinned upstream library and dependencies
├── tests/nike/                  # Offline fetcher and upstream integration tests
├── data/                        # Separate private repository; ignored here
│   ├── .gitignore               # Explicit credential and state exclusions
│   ├── GOALS.md
│   ├── strava-tokens.json       # Custom OAuth client; untracked
│   ├── nike-tokens.json         # Nike library token material; untracked
│   ├── strava-mcp/              # Server-managed credentials; untracked
│   ├── .sync-state/             # Per-integration operational state; untracked
│   └── run-YYYY-MM-DD-<provider>-<id>/
│       ├── <source-file>.json   # Source representation; see provider spec
│       └── import.json         # Factual source/date provenance
└── slop/                        # Temporary agent output; ignored here
```

Run directories follow `run-YYYY-MM-DD[-suffix]/` with zero-padded dates and a
provider/activity-ID suffix. Cloning this repository does not create `data/` or
`slop/`.

## Data and agent principles

- Shared instructions belong here; source records, notes, and goals belong in
  the private data checkout. Credentials follow the selected file rules above.
- Source records, factual import provenance, and explicit athlete inputs are
  persistent evidence. Agent summaries and recommendations belong in `slop/`.
- Agents must ask about gaps and current circumstances rather than inventing
  facts or treating previous conclusions as evidence. An explicit peer-review
  workflow may review generated output; it is not implemented yet.

## Contributing

Ideas, issues, and pull requests are welcome. Use synthetic or anonymized examples
and keep personal activity data and credentials out of issues and pull requests.

## License

[Apache License 2.0](LICENSE).
