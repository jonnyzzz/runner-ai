# Nike+ / Nike Run Club importer specification

Planned implementation: `src/nike/`, with entry point `src/nike/sync.py`.
This adapter is not implemented yet.

Use the [shared importer specification](README.md#importer-specification) for
architecture, CLI options, history selection, incrementality, storage, failure
recovery, and credential handling. Those requirements are implemented once in
`src/runner_ai/`; this file defines the Nike-specific behavior.

## Planned command

From the repository root:

```sh
uv run src/nike/sync.py --account athlete
```

Use the [common options](README.md#history-selection-and-common-options) for an
earlier cutoff, full refresh, or a timezone fallback. Importing the oldest years
is optional; the default history window must be enforced before detail requests.
The account label selects local state and does not verify the Nike account;
use the label for the account whose token is being supplied.

## Integration basis and evidence

Use Nike's existing browser-session bearer token with its private activity API.
This is an unofficial integration, not a documented consumer OAuth application
flow. Do not invent a localhost OAuth callback, client-registration process, or
run-specific permission prompt for this adapter.

The protocol is grounded in these implementations, researched on 2 November 2026:

- [yasoob/nrc-exporter](https://github.com/yasoob/nrc-exporter), including the
  [updated pagination](https://github.com/yasoob/nrc-exporter/pull/23) and
  [May 2026 login fix](https://github.com/yasoob/nrc-exporter/pull/28).
- [running_page's Python adapter](https://github.com/yihong0618/running_page/blob/master/run_page/nike_sync.py).
- [2026-nrc-to-strava's downloader](https://github.com/jajyll/2026-nrc-to-strava/blob/main/nike-download.js),
  whose author reports a successful export in October 2026.

These establish a plausible protocol, not a successful authenticated test against
this athlete's account. Validate a small sample before relying on it for a full
import. The [PyPI nrc-exporter release](https://pypi.org/project/nrc-exporter/) is
still version 0.0.7 from July 2020 and does not contain the later GitHub fixes;
do not use that package as the implementation dependency.

## Login and credentials

1. Ask the user to sign in normally at [nike.com](https://www.nike.com/).
2. In browser developer tools, find the local-storage entry whose key starts
   with `oidc.user:https://accounts.nike.com:` and obtain its `access_token`.
   The exact client-specific key may change; do not hard-code a legacy key or
   depend on the retired `unite.nike.com` login page.
3. Accept the token through `NIKE_ACCESS_TOKEN` or an interactive hidden prompt,
   not a command-line token argument. Use it only as an HTTPS bearer credential
   to Nike's API. Never ask for the account password or automate password login.
4. Apply the [shared credential rules](README.md#private-data-credentials-and-state)
   to any cached token under `data/.runner-ai/nike/`. Use a provider account ID
   when the response supplies one. Otherwise require an explicit account label
   through `--account` for state and cache selection, and report that identity
   could not be verified automatically. Do not infer identity from a token's
   text or reuse another account's checkpoint.
5. When a token expires or is rejected, preserve progress and explain how to
   supply a fresh browser token. A `403` may reflect access restrictions rather
   than expiry; report the status accurately. Do not assume the old refresh-token
   endpoint works with current web login, or retry rejected credentials blindly.

Do not assume a fixed token lifetime for this private protocol; use expiry
information when available and handle rejection. Keep authentication failure
separate from an empty activity history.

## Activity API and pagination adapter

Send authenticated read requests to `https://api.nike.com`.

First listing request:

```text
GET /plus/v3/activities/before_id/v3/*?limit=30&types=run%2Cjogging&include_deleted=false
```

Follow the returned `paging.before_id`, substituting that opaque cursor for `*`
on the next request with the same query parameters. Validate the `activities`
array and paging structure. A missing activities array, invalid JSON, or repeated
cursor is an error, not successful completion. Finish when the API indicates
there is no next cursor; do not stop merely because a page has no selected runs.

For an accepted activity in the selected history window, fetch:

```text
GET /sport/v3/me/activity/<activity-id>?metrics=ALL
```

This details endpoint is used by the original exporter and the October 2026
implementation. Other tools use `/plus/v3/activity/<activity-id>?metrics=ALL`;
introduce compatibility fallbacks only after validating their schema and account
behavior, not as blind retries after authentication failures.

The listing has no verified equivalent of the shared UTC date filters. Filter
summary timestamps locally and follow all required cursors, even when that means
reading summaries older than the cutoff. Do not assume UUID order is time order
or terminate on the first old or known record. The
[shared sync engine](README.md#incremental-fetching-and-recovery) decides which
in-window details are missing or due for refresh; the adapter must not implement
its own incremental state or duplicate detection.

## Run selection and source data

- Accept activity `type` values `run` and `jogging`; exclude deleted activities,
  unrelated types, and Nike Training Club workouts. Recheck classification on
  detail responses and report unknown types instead of guessing.
- Retain manual, indoor, treadmill, and GPS-free runs. Do not copy the original
  exporter's exclusion of `com.nike.running.runtype=manual`, or require latitude
  and longitude to accept a run.
- Use the stable Nike activity ID as source identity. Compare `start_epoch_ms`
  with the shared UTC bounds after converting milliseconds correctly. For a
  new folder, use a trustworthy source timezone/offset if present; otherwise
  require `--timezone` and record the fallback as defined in the
  [shared source-record rules](README.md#source-records-and-identity).
- Preserve the complete returned JSON, including original summaries, metric
  types, timestamps, units, and tags. Metric streams and `metrics` itself may be
  absent on a valid run. Keep available data and report those limitations.
  An HTTP error or malformed response must not be mistaken for such a run.
- Preserve ascent and descent fields as supplied; do not reinterpret them as
  absolute altitude. Conversion to GPX or FIT is unnecessary for the initial
  source import and must not determine which runs are retained.

With provider name `nike`, the shared layout becomes
`data/run-YYYY-MM-DD-nike-<activity-id>/nike.json`. Keep existing folders by ID
and apply the shared atomic-write and note-preservation rules.

## Alternatives and later work

The official [Nike-to-Strava connection](https://support.strava.com/en-us/articles/15401850-nike-and-strava)
forwards newly recorded activities after accounts are linked; it does not
backfill historical activities. If enabled, account for the resulting duplicate
source records using the shared identity and planning rules.

[Nike's privacy form](https://www.nike.com/help/privacy) provides an export-request
route if direct API access fails. Archive-file import, including existing raw
Nike JSON or a supplied TCX archive, is a later adapter extension through the
same shared writer. Inspect the actual format and preserve original files;
do not assume every archive has identical fields or complete GPS data.

## Provider-specific verification

In addition to the shared contract suite, verify cursor pagination, valid end of
pagination, malformed or repeated cursors, rejected and expired tokens,
account-label isolation, run-only selection, manual and GPS-free runs, missing
metrics, malformed detail responses, millisecond timestamps, timezone fallback,
and histories spanning the cutoff.

For live validation, check at least a known outdoor run and an indoor or manual
run if the account has one. Compare source ID, time, distance, and available
metrics with the account. Missing older records must not block importing a valid
selected period; failures inside that period must be reported for retry.
