# Runner AI

An experiment in using AI to support marathon training, grounded in an athlete's
activity history, goals, and feedback. The aim is to build reusable tools for my
own training that other runners can adapt.

> This is an experimental project, not professional training or medical advice.
> Use it at your own risk and consult qualified coaches or medical professionals
> where appropriate.

## Current status

The project is at the design stage. This repository currently contains this
README, a license, and ignore rules for personal data and generated output.
Importers, agent skills, and training workflows are not implemented yet;
`src/strava/` does not exist in this checkout. The sections below describe the
intended design. Commands in the Strava specification are the planned interface,
not runnable instructions yet.

## Planned workflow

1. **Set up private storage.** Use a separate, private Git repository with the
   same name plus a `-data` suffix, such as `runner-ai-data`, checked out under
   `data/`. Setup tooling should create that repository if it does not exist.
2. **Record goals.** Keep current training goals and planned marathons in
   `data/GOALS.md`.
3. **Import activities.** Fetch runs into dated directories, keeping the source
   records for each run together. Implement Strava first, following the
   specification below; Nike+ is a later integration.
4. **Review with an agent.** Use repository instructions and skills to guide
   analysis. The agent must ask follow-up questions when information is missing
   and record the athlete's answers rather than inventing details.
5. **Persist source data.** Commit and push imported activity records and explicit
   user inputs to the private data repository. Keep generated analysis in
   `slop/`, outside Git history.

## Strava importer specification

The first implementation will be a standalone Python script at
`src/strava/sync.py`, run with [uv](https://docs.astral.sh/uv/guides/scripts/).
Declare Python 3.12+ and any dependencies using inline script metadata, so no
manual virtual-environment setup is needed.

### Planned command

From the repository root:

```sh
# Authenticate if necessary, then import runs incrementally.
uv run src/strava/sync.py

# Rescan and refresh the entire accessible run history.
uv run src/strava/sync.py --full
```

The user must register a [Strava API application](https://www.strava.com/settings/api).
Follow the [Strava Getting Started guide](https://developers.strava.com/docs/getting-started/)
to create an app and obtain credentials. **A Strava subscription is required**
to access certain activity data (including private "Only You" runs). 

Supply `STRAVA_CLIENT_ID` and `STRAVA_CLIENT_SECRET` through the environment.
Resolve the default `data/` path relative to the repository root, regardless of
the shell's working directory. This milestone imports source files; private
repository provisioning and automatic Git commits or pushes are separate work.

### OAuth login and credentials

- **Create tokens:** Register an app at
  [Strava API Settings](https://www.strava.com/settings/api), set the
  Authorization Callback Domain/redirect to a loopback URL (or follow the
  [Getting Started](https://developers.strava.com/docs/getting-started/) flow).
  Complete the OAuth authorization to obtain access and refresh tokens. **A
  Strava subscription is necessary** to access private activities (including
  "Only You" runs).
- **Alternative: Strava MCP.** You can also connect via a Strava MCP server
  instead of running the custom importer. This approach also requires a Strava
  subscription for access to private runs.
- Start a loopback-only HTTP listener before opening the browser. Let the OS
  assign a free port by binding port `0`, and use
  `http://localhost:<assigned-port>/callback` as the redirect URI.
- Open Strava's authorization page in the default browser; also print the
  authorization URL if the browser cannot be opened. Use the authorization-code
  flow with an unpredictable `state`, and validate the callback path and state
  before accepting a code. Handle denial, missing permissions, and a bounded
  timeout, then close the listener.
- Request **only `activity:read_all`**, to include the athlete's private
  “Only You” runs. The narrower `activity:read` omits those runs. Request no
  profile or write permissions. Strava has no run-only scope; filter activities
  locally rather than retaining unrelated sports.
- Exchange the code for tokens and verify the granted scope. Reuse valid tokens
  on later runs, refresh expired access tokens, and atomically save the latest
  returned refresh token. Reauthorize when access has been revoked.
- **Store tokens under `data/`:** Save tokens in a file under the `data/`
  directory (e.g., `data/strava-tokens.json`). The `data/` directory is in a
  separate private Git repository and is ignored by this repository. Restrict
  file permissions to the current user (e.g., `0600`). Never write client
  secrets, codes, or tokens into activity JSON, `slop/`, logs, or commit them to
  Git. Bind saved credentials and sync state to the authenticated athlete to
  avoid mixing accounts.

The redirect rules, scopes, and token lifecycle follow
[Strava's authentication documentation](https://developers.strava.com/docs/authentication/).

### Run selection and source files

List activities using `GET /api/v3/athlete/activities`, then accept only
`sport_type` values `Run`, `TrailRun`, and `VirtualRun`. Treadmill activities
classified as `Run` are included. Skip all other or unknown types before fetching
details or creating folders; do not save unfiltered activity-list responses.
Use `GET /api/v3/activities/{id}` for each selected run's source details. The
endpoints and sport types are defined in the
[Strava API reference](https://developers.strava.com/docs/reference/).

Store each run at:

```text
data/run-YYYY-MM-DD-strava-<activity-id>/strava.json
```

For new folders, use the activity's `start_date_local` calendar date, not the
computer's timezone or the import date. Always include the stable Strava activity
ID as the suffix, so multiple runs on the same day have distinct folders. Match
existing records by activity ID before creating a folder. If Strava later
corrects the date, reuse the existing directory and update its JSON without
renaming the folder. Preserve the source fields, write JSON atomically, and leave
identical files unchanged. Never overwrite athlete notes, `GOALS.md`, or another
importer's files, and never delete run folders automatically.

### Incremental fetching and recovery

Capture a UTC scan-start timestamp before making activity requests and use it as
`before` for every page, including the first import and full rescans.

1. **First import:** paginate the accessible activity history and fetch missing
   runs. Reuse complete existing records when resuming an interrupted initial
   import.
2. **Later imports:** set `after` to the previous successful scan's start time
   minus seven days. Refresh run details in this overlap window to pick up recent
   corrections, without downloading all older runs again.
3. **Pagination:** continue until the API returns an empty activity page, even
   when intermediate pages contain only unrelated sports. Deduplicate by Strava
   activity ID across pages, retries, and repeated invocations.
4. **Checkpoint:** save the scan's start time only after all pages and selected
   runs have been processed successfully, including scans with no runs. Keep
   checkpoints and any index in user-local state outside Git, keyed by athlete
   and target data checkout. Preserve completed files and the previous checkpoint
   on failure, so rerunning is safe.
5. **Full rescan:** `--full` ignores the incremental date boundary and refreshes
   all accessible runs, while preserving user-authored files.

Strava's `after` and `before` filters apply to when an activity took place, not
when it was uploaded or edited. The seven-day overlap is a practical default,
not a guarantee of finding older changes; use `--full` for backdated uploads and
corrections outside that window. See the
[activity-list parameters](https://developers.strava.com/docs/reference/#api-Activities-getLoggedInAthleteActivities).

Use HTTP timeouts and bounded retries for transient failures. Respect Strava's
[rate limits](https://developers.strava.com/docs/rate-limits/); if the sync cannot
finish, report the failure and exit nonzero without advancing the checkpoint.
Print a summary of imported, updated, unchanged, and skipped activities without
exposing credentials.

### Implementation plan

1. Add the uv script, environment configuration, and command-line interface.
2. Implement browser OAuth, callback validation, token storage, and refresh.
3. Add paginated listing, the run allowlist, and deterministic source-file writes.
4. Add incremental checkpoints, the overlap window, `--full`, and failure recovery.
5. Verify with offline tests covering denied or invalid callbacks, token rotation,
   mixed and run-free pages, same-day runs, activity-local dates, repeated imports,
   interrupted syncs, and preservation of athlete notes.

The initial importer retrieves activity details only. Streams, GPX export,
Nike+, agent analysis, and repository automation are later work.

## Intended directory layout

```text
runner-ai/
├── README.md
├── LICENSE
├── .gitignore
├── src/                                  # Planned shared source code
│   └── strava/
│       └── sync.py                       # Planned uv script
├── data/                                 # Separate private repository; ignored
│   ├── GOALS.md                          # Athlete's goals and planned marathons
│   └── run-YYYY-MM-DD-strava-<id>/
│       └── strava.json                   # Imported activity details
└── slop/                                 # Temporary agent output; ignored
```

Run directories follow `run-YYYY-MM-DD[-suffix]/` with zero-padded dates. The
Strava importer always uses its activity ID suffix as specified above. The
`data/` and `slop/` directories are excluded by this repository's `.gitignore`;
they are not created by cloning it.

## Data and agent principles

- **Keep personal data private.** Shared scripts and instructions belong in this
  repository. Activity records, athlete notes, and goals belong in the separate
  private data repository. Do not commit credentials or access tokens to either.
- **Keep evidence separate from generated analysis.** Imported records and the
  athlete's own inputs are the source of truth. Agent summaries, recommendations,
  and intermediate output belong in `slop/`.
- **Start each analysis from the evidence.** Agents should not treat their earlier
  conclusions as new facts. An explicit peer-review workflow may use generated
  output as material to review, but that workflow is not implemented yet.

## Contributing

Ideas, issues, and pull requests are welcome. Useful starting points include
activity importers, the run data format, and agent instructions. Use synthetic or
anonymized examples and keep personal activity data and credentials out of issues
and pull requests.

## License

[Apache License 2.0](LICENSE).
