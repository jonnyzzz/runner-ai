# Fetch runs from Nike+ / Nike Run Club

The [fetcher](src/nike/sync.py) uses
**[yasoob/nrc-exporter](https://github.com/yasoob/nrc-exporter)** for Nike login,
activity listing, and activity details. It handles local credential storage,
history selection, caching, and the [run-folder layout](README.md#run-records-and-layout).
It does not implement Nike endpoints or a separate authentication flow.

## First fetch

You need [uv](https://docs.astral.sh/uv/getting-started/installation/), Git, and a
Nike account. uv installs the script's Python 3.11 environment and locked
dependencies automatically on the first invocation.

From the repository root, prepare `data/` as a **separate private Git checkout**.
Use your existing private data repository, or initialize a local one and add a
private remote later:

```sh
mkdir -p data
git -C data init
```

Then run:

```sh
uv run --locked src/nike/sync.py --login --timezone Europe/Berlin --log
```

Choose an IANA timezone appropriate for your history. The source timezone is used
when present; otherwise this explicit fallback determines the folder date.
Historical runs recorded while traveling may need a different timezone.

The launcher invokes the library's manual login flow:

1. Run the command above in an interactive terminal. When the library says
   `Press 'y' to open up the login url`, type `y` and press **Enter**.
2. Sign in on Nike's website in the browser that opens. Follow the
   [library's token extraction instructions](https://github.com/yasoob/nrc-exporter#heavy_dollar_sign-extracting-access-tokens)
   to find the `access_token` in browser developer tools. You can also copy the
   value of an authenticated Nike request's `Authorization` header.
3. Switch back to the terminal. At `Nike access token (hidden):`, paste the token
   and press **Enter**. Both the token alone and `Bearer <token>` are accepted.
   **The terminal displays no characters or asterisks when you paste.** This is
   expected; press Enter once after pasting to submit it.
4. The fetch starts with `Listing runs through nrc-exporter...`. Its log filename
   is printed at startup; periodic counts show progress after listing completes.

Keep the token out of chat and shell commands. Login stops if the terminal cannot
hide input. The launcher removes a copied `Bearer ` prefix and saves the token
in **`data/nike-tokens.json`** with the local account label. It also corrects that
prefix in previously saved token files. It does not pass the token in process
arguments or write it into run records. No Strava credentials are needed.

Before storing credentials, the script adds the
[required exclusions](README.md#credential-files-under-data) to `data/.gitignore`,
checks that the Nike token and sync state are untracked, and enforces private
file/directory permissions where supported. Commit the updated `.gitignore` to
your private data repository yourself; fetching does not commit or push files.
The token file is `0600` and state directories are `0700` on POSIX systems.

The first fetch selects the preceding 12 calendar months. It saves this start
date and timezone for later invocations and writes selected runs as:

```text
data/run-YYYY-MM-DD-nike-<activity-id>/
├── nike.json       # Original activity details
└── import.json     # Library revision, source ID, account label, and date basis
```

## Subsequent fetches and token renewal

```sh
# Reuse the saved token, start date, timezone, and downloaded details.
uv run --locked src/nike/sync.py --log

# Renew through the library when the saved token is rejected or expires.
uv run --locked src/nike/sync.py --login

# Refresh existing runs in the selected period to pick up corrections.
uv run --locked src/nike/sync.py --full
```

Login requires an interactive terminal. Token acquisition and renewal remain the
library's responsibility; the launcher does not promise automatic token refresh.
The selected token file contains `account` and `access_token` fields. Keep it
local and ignored. An account label is local bookkeeping, not verified Nike
identity; use a separate data checkout for another athlete.

Every fetch asks the library for IDs again, allowing newly uploaded backdated
runs to be discovered. Cached details are reused. Changes to already downloaded
activities require `--full`; full refresh leaves identical files unchanged and
preserves the existing folder when a run's source date changes.

## Options

| Option | Behavior |
| --- | --- |
| `--since YYYY-MM-DD` | Set and save an inclusive UTC start date. Earlier dates backfill from cache or Nike. |
| `--all-history` | Remove the saved date boundary. Cannot be combined with `--since`. |
| `--full` | Download fresh details for existing runs in the selected period; does not expand the period. |
| `--timezone Europe/Berlin` | Set and save a timezone fallback for records without a source timezone. |
| `--data-dir PATH` | Use another separate data checkout. The default is this repository's `data/`, regardless of the shell's working directory. |
| `--account LABEL` | Select a local account label; default `athlete`. A saved token with another label is rejected. |
| `--login` | Run the library's login flow and replace the token in the selected file. |
| `--log` | Also write a private, redacted log under `data/.sync-state/nike/logs/`. The filename is printed at startup. |
| `--timeout SECONDS` | Bound each detail operation; default 60 seconds. Listing is bounded by at least 300 seconds. |

Examples:

```sh
uv run --locked src/nike/sync.py --since 2024-11-02
uv run --locked src/nike/sync.py --all-history --full
```

## Progress, recovery, and limitations

- **Logs:** `--log` captures progress and sanitized errors. Log files are `0600`
  and their directory is `0700` on POSIX systems. Known tokens are redacted from
  captured output, and upstream HTTP debug logging is disabled. Logs may contain
  activity IDs and local paths, so keep them private. No log is committed or
  pushed by the fetcher.
- **First-fetch cost:** the pinned library lists IDs without dates. Uncached
  details, including older runs, must be fetched before local date selection.
  They remain in the ignored cache at
  `data/.sync-state/nike/<account>/activities/`; later fetches reuse them. The
  cache can therefore contain more history than the retained run folders.
- **Upstream coverage:** this library revision excludes manually entered runs.
  The fetcher reports that limitation. GPS-free or missing-metric runs supplied
  by the library are retained; GPX conversion is not run, so missing `metrics`
  alone does not reproduce the old converter failure.
- **Recovery:** successful records survive interruption. Per-run failures remain
  pending, and incomplete scans do not advance the successful checkpoint. The
  script stops after three consecutive failures rather than repeatedly using a
  rejected token. A cached record with no source timezone needs `--timezone`.
- **Retries and timeouts:** isolated worker processes call the upstream library
  without modifying its HTTP implementation. Transient worker failures get one
  retry. Rejected credentials need the library's `--login` flow. Increase
  `--timeout` if an unusually long listing exceeds its limit.
- **Inspection:** configuration, pending IDs, successful coverage, and possible
  Strava duplicate hints are in
  `data/.sync-state/nike/<account>/state.json`. No tokens are stored there.
  Duplicate hints compare nearby start times and durations where available;
  they do not merge or delete either source record.
- **Exit status:** `0` means the library-reported selection completed; `1` means
  failure or unresolved records; `130` means interruption. The printed
  `incomplete` count is a subset of retained runs with missing metric streams,
  rather than a failed download count.

Existing notes and `GOALS.md` are preserved. A Git checkout, valid JSON source
responses, safe filenames, and credential exclusions are checked before records
are accepted. Simultaneous Nike imports into the same checkout are blocked.

## Dependency and verification

The upstream library is pinned to revision
[`a4447c8c65b3f0d404f8f1441fded35e83871405`](https://github.com/yasoob/nrc-exporter/commit/a4447c8c65b3f0d404f8f1441fded35e83871405).
The adjacent `sync.py.lock` pins its dependencies. Local uv overrides select
patched Requests and Selenium releases despite the upstream package's older
bounds; filelock also has a patched lower bound. The manual login path is tested
with those versions. Automated Selenium login is not used by this launcher.
Login and protocol fixes belong upstream. The published PyPI version predates
the required fixes.

### Security review, 2026-11-02

The pre-fetch review covered credential entry and persistence, terminal and file
logs, filesystem paths, Git exclusions, the library calls used by this launcher,
and the locked dependencies. It found and fixed two issues:

- The library's manual token prompt used echoed input. The local input bridge now
  uses Python's [hidden input](https://docs.python.org/3/library/getpass.html) and
  refuses its echoed fallback. The library still controls the login flow.
- The original lock contained dependencies with published advisories. The lock
  now selects patched versions, including fixes for
  [Requests credential leakage](https://github.com/psf/requests/security/advisories/GHSA-9hjg-9r4m-mvj7)
  and [filelock lock-file handling](https://github.com/tox-dev/filelock/security/advisories/GHSA-69hj-f68j-2879).

`pip-audit` reported no known vulnerabilities in the **23 registry packages** in
the updated lock. The pinned Git library was reviewed separately; it is outside
that registry scan. This is a point-in-time result. The offline tests include
the actual pinned library's manual login path with synthetic input, hidden-input
failure, token redaction, log permissions, and incremental recovery. Additional
checks cover copied `Bearer ` prefixes and reject embedded whitespace or control
characters before a token reaches the library.

The fetch path invokes the library's read operations over HTTPS. Its bearer token
is supplied by Nike's login session; the launcher cannot request a narrower OAuth
scope or guarantee that the token itself permits only reads. Treat it as a
credential for your Nike account. The data checkout and local machine remain
trusted storage; Git ignores and file permissions do not encrypt the files.

To run the offline checks, first populate the locked script environment, then run
the tests. Fixtures contain synthetic tokens and block Nike HTTP calls:

```sh
uv run --locked src/nike/sync.py --help
uv run --with 'filelock>=4.2.1,<5' python -m unittest discover -s tests/nike -v
```

Tests cover the real pinned library through mocked HTTP, incremental imports,
late uploads, wider history, UTC and local dates, missing metrics, retry and
checkpoint behavior, token protection, duplicate hints, and note preservation.
Authenticated fetching against a real Nike account still requires your login.
