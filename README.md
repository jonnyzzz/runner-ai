# Runner AI

An experiment in using AI to support marathon training, grounded in an athlete's
activity history, goals, and feedback. The aim is to build reusable tools for my
own training that other runners can adapt.

> This is an experimental project, not professional training or medical advice.
> Use it at your own risk and consult qualified coaches or medical professionals
> where appropriate.

## Current status

The project is at the specification stage. The source tree, importers, and agent
workflows below are planned, not implemented. The command examples describe the
intended interface and are not runnable yet.

## Planned workflow

1. Keep shared code and instructions in this repository. Prepare a separate,
   private repository named with a `-data` suffix, such as `runner-ai-data`,
   checked out under `data/`. Repository provisioning is a later milestone.
2. Record training goals and planned races in `data/GOALS.md`. Add user-provided
   context about previous races, injuries, major breaks, and missing records.
3. Import runs using either provider below. Both implementations must use the
   same shared importer contract and source-file layout.
4. Let an agent analyze the source records and ask questions where information
   is missing. Keep generated analysis in the ignored `slop/` directory.
5. Commit source records and explicit user inputs to the private data repository.
   Import commands write files; automatic Git commits and pushes are later work.

## Importer specification

| Provider | Planned entry point | Provider-specific specification |
| --- | --- | --- |
| Strava | `src/strava/sync.py` | [strava.md](strava.md) |
| Nike+ / Nike Run Club | `src/nike/sync.py` | [nike.md](nike.md) |

Authentication, API endpoints, pagination formats, and activity-type mappings
belong in the provider specifications. The shared requirements below apply to
both providers; provider adapters must not copy or redefine them.

### Shared architecture

Use Python 3.12+ and one [uv project](https://docs.astral.sh/uv/concepts/projects/layout/)
with dependencies declared in `pyproject.toml` and locked in `uv.lock`. Configure
the project to install the shared and provider packages from `src/`, so imports
work without manually setting `PYTHONPATH` or creating a virtual environment.

The entry points are thin wrappers around a shared `runner_ai` package in
`src/runner_ai/`:

- **Shared code:** CLI options, history selection, sync decisions, retries,
  validation, date handling, atomic file writes, state, locking, and reporting.
- **Provider adapters:** authentication, account identity, paginated activity
  summaries, run classification, source timestamps, and activity-detail requests.

Run the entry points with `uv run src/<provider>/sync.py` from the repository
root. Use project dependencies rather than isolated inline script metadata,
which [bypasses the project's dependencies](https://docs.astral.sh/uv/guides/scripts/#declaring-script-dependencies).
Resolve `data/` relative to the repository location, not the shell's working
directory. Both adapters must exercise the same sync engine and storage code.

### History selection and common options

Initially import **the most recent 12 calendar months**. Persist that initial
start date per provider/account/checkout and reuse it on subsequent invocations;
it is a backfill boundary, not a rolling deletion policy.

| Option | Shared behavior |
| --- | --- |
| `--since YYYY-MM-DD` | Set an inclusive UTC start date; persist this choice for later syncs. An earlier date backfills missing records. |
| `--all-history` | Explicitly remove the start-date boundary. Mutually exclusive with `--since`. |
| `--full` | Refresh all runs in the selected history window, including existing records. It does not override the start-date boundary. |
| `--timezone IANA_NAME` | Supply the athlete's timezone when a source lacks a trustworthy local date or offset. Persist the choice; never assume the computer's timezone. |
| `--account LABEL` | Select an account/cache label when needed, including when a provider cannot supply a stable account ID. |

Explicit `--since` and `--all-history` choices replace the saved history window;
`--full` applies only to the current invocation. Validate conflicting flags,
dates, and timezone names before authenticating or changing files.

For planning, prioritize the latest 8–12 weeks and use the year for broader
training context. Extend the import to two years when an earlier training cycle
is useful; older race results and relevant history can be supplied as user
inputs. These are practical data defaults, not established minimums: research
has examined [16-week training blocks](https://www.frontiersin.org/journals/physiology/articles/10.3389/fphys.2021.669884/full)
and [training across the preceding year](https://link.springer.com/article/10.1007/s40279-025-02304-4),
without establishing a required archive length for individual planning.

### Incremental fetching and recovery

Both adapters use this algorithm. Provider differences affect how pages are
obtained, not how records are selected, stored, refreshed, or retried.

1. **Fix the window.** Capture a UTC scan-start timestamp. Select activities
   whose start is on or after the configured lower boundary and before scan
   start. Use API date filters where supported and enforce the bounds locally.
2. **Enumerate summaries.** On every invocation, revisit the listings covering
   the selected window. Follow the provider's pagination protocol, deduplicate
   activity IDs, and filter out unrelated sports before detail requests or run
   folder creation. Continue through pages containing no selected runs. Detect
   repeated cursors or pages instead of looping or reporting false completion.
3. **Fetch incrementally.** Download missing, invalid, or previously failed run
   records. Refresh existing runs that started within seven days before the
   previous successful scan start; on a first import, reuse complete existing
   records. `--full` refreshes every selected run. Leave unchanged files alone.
4. **Find late uploads.** Re-enumerating summaries discovers previously unseen,
   backdated runs inside the selected window, even outside the refresh overlap.
   Older edits to already imported runs require `--full`. Do not stop at the
   first known ID or use the newest run's date as proof that history is complete.
5. **Validate and write.** Check HTTP status, JSON shape, run type, activity ID,
   and usable timestamps before accepting a record. Never save an API error body
   as activity data. Write each successful source file atomically. Continue with
   other records after an individual failure and retain completed files.
6. **Checkpoint completion.** Advance the successful-scan checkpoint only when
   enumeration and all required writes finish without unresolved errors,
   including a successful scan containing no runs. Preserve the old checkpoint
   and record failed IDs on partial failure. Bind state to provider, account,
   target checkout, and the selected coverage; widening history must not skip
   backfill. Rebuild the existing-record index from source files if local state
   is missing, and prevent overlapping syncs for the same account and provider.
7. **Report the outcome.** Use HTTP timeouts, bounded retries, backoff, and
   provider rate-limit signals. Stop retrying rejected credentials blindly.
   Report imported, updated, unchanged, excluded, incomplete, and failed records;
   exit nonzero on unresolved failures without printing secrets.

Listing summaries again is intentional: incrementality avoids repeated detail
downloads and file changes while still discovering late uploads.

### Source records and identity

Store each activity in:

```text
data/run-YYYY-MM-DD-<provider>-<activity-id>/<provider>.json
```

- Use a source-local date when trustworthy. Otherwise require the configured
  athlete timezone, convert the source UTC instant, and record that date basis
  as import metadata. A fallback timezone may not describe historical travel.
- The stable identity is `(provider, activity-id)`, not the date or activity
  title. Validate IDs before using them as path components. Multiple same-day
  runs have distinct folders. If a source date is corrected, reuse the existing
  folder by ID and update its source JSON without renaming the folder.
- Preserve original source fields and units. Store provenance or date-fallback
  metadata in a separate `import.json`. Operational timestamps belong in local
  state so an unchanged import does not generate Git changes.
- A valid run without GPS, heart rate, or detailed metric streams is still a
  run. Retain available source data and report missing fields. Invalid responses
  remain failures to retry, rather than becoming successful incomplete records.
- Never overwrite athlete notes, `GOALS.md`, another provider's files, or delete
  source folders automatically. Report remote deletions or reclassification when
  observed; absence from a listing alone does not prove deletion. Missing
  records mean unknown coverage, not automatically rest days.
- Preserve both source records when the same run appears through two providers.
  Report potential duplicates using source links, UTC start, duration, and
  distance; do not silently merge or discard approximate matches. The planning
  workflow must resolve duplicates before counting them toward training totals.

### Private data, credentials, and state

`data/` is a separate private checkout. The parent repository's ignore rule does
not protect files from commits made inside that checkout.

Keep credentials, checkpoints, pending IDs, and locks under `data/.runner-ai/`,
separate from the run folders. Before storing secrets, require a separate data
checkout and add `/.runner-ai/` to its local Git exclude rules. Verify these files
are ignored inside the data checkout and refuse to persist secrets already
tracked by Git. Restrict the directory to the current user (`0700`) and secret
files to `0600`; write credential updates atomically.

Keep client secrets supplied through the environment out of persisted state.
Never include credentials, authorization codes, request headers, or tokens in
source JSON, generated analysis, or logs. Confirm the provider account before
reusing a checkout; do not mix different athletes' records. Provider files define
how to obtain account identity and credentials. An account label namespaces
state; it is not proof of authenticated identity. Reject a changed provider
account ID for an existing label. Where no ID can be verified, require an explicit
account label and report that identity could not be verified automatically.

### Implementation and verification

1. Establish the uv project, shared package, common CLI, and adapter interface.
2. Implement authentication and source adapters as specified in
   [strava.md](strava.md) and [nike.md](nike.md).
3. Implement the common history, sync, storage, credential, and reporting rules
   once, then connect both entry points to them.
4. Run a shared contract suite against both adapters, covering history bounds,
   same-day runs, source-local dates, corrected dates, unknown activity types,
   pages without runs, duplicate IDs, late uploads, older edits, missing metrics,
   retries, interruption, state loss, wider backfills, and note preservation.
5. Verify credentials are excluded by the private checkout, checkpoints do not
   advance on partial failure, and repeated imports leave identical files
   unchanged. Add the provider-specific checks listed in each provider file.

The first milestone imports source activity details only. Separate stream
requests, file conversion/export, agent coaching, repository provisioning, and
Git automation are later work. Implementation must also ignore generated Python
environments and caches before creating them.

## Intended directory layout

All source files and dependency files below are planned.

```text
runner-ai/
├── README.md                    # Shared requirements and workflow
├── strava.md                    # Provider-specific specification
├── nike.md                      # Provider-specific specification
├── LICENSE
├── .gitignore
├── pyproject.toml               # Shared uv project and src package configuration
├── uv.lock
├── src/
│   ├── runner_ai/               # Shared CLI, sync, storage, state, and HTTP logic
│   ├── strava/
│   │   └── sync.py              # Thin provider entry point and adjacent adapter
│   └── nike/
│       └── sync.py              # Thin provider entry point and adjacent adapter
├── tests/                       # Shared contract and provider tests
├── data/                        # Separate private repository; ignored here
│   ├── GOALS.md
│   ├── .runner-ai/              # Credentials/state; excluded inside data as well
│   └── run-YYYY-MM-DD-<provider>-<id>/
│       ├── <provider>.json      # Original activity details
│       └── import.json         # Factual source/date provenance
└── slop/                        # Temporary agent output; ignored here
```

Run directories follow `run-YYYY-MM-DD[-suffix]/` with zero-padded dates. Both
providers always use their name and activity ID as the suffix. Cloning this
repository does not create `data/` or `slop/`.

## Data and agent principles

- **Keep personal data private.** Shared scripts and instructions belong here;
  source records, athlete notes, and goals belong in the private data checkout.
  Credentials and local state follow the exclusions above.
- **Separate evidence from generated analysis.** Source records, factual import
  provenance, and explicit athlete inputs are persistent evidence. Agent
  summaries, recommendations, and intermediate output belong in `slop/`.
- **Start each analysis from evidence.** Agents must ask about gaps and current
  circumstances rather than inventing facts or treating previous conclusions as
  evidence. An explicit peer-review workflow may review generated output; it is
  not implemented yet.

## Contributing

Ideas, issues, and pull requests are welcome. Useful starting points include
activity adapters, the common importer, and agent instructions. Use synthetic or
anonymized examples and keep personal activity data and credentials out of issues
and pull requests.

## License

[Apache License 2.0](LICENSE).
