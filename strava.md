# Strava importer specification

Planned implementation: `src/strava/`, with entry point `src/strava/sync.py`.
This adapter is not implemented yet.

Use the [shared importer specification](README.md#importer-specification) for
architecture, CLI options, history selection, incrementality, storage, failure
recovery, and credential handling. Those requirements are implemented once in
`src/runner_ai/`; this file defines the Strava-specific behavior.

## Planned command and setup

From the repository root:

```sh
uv run src/strava/sync.py
```

Use the [common options](README.md#history-selection-and-common-options) to change
the history window or force a refresh. `--full` refreshes the selected window;
combine it with `--all-history` only when the entire accessible archive is wanted.

Register an application at [Strava API Settings](https://www.strava.com/settings/api),
following the [Getting Started guide](https://developers.strava.com/docs/getting-started/).
Strava currently requires a subscription to create an API application. Set
**Authorization Callback Domain** to `localhost`, without a scheme, path, or port.
Supply `STRAVA_CLIENT_ID` and `STRAVA_CLIENT_SECRET` through the environment.

App subscription requirements and OAuth permissions are separate: access to
private activities requires the scope below. Do not describe a subscription as a
replacement for permission, or assume that any future MCP server has identical
account requirements.

## OAuth login

1. Start a loopback-only HTTP listener, requesting port `0` so the OS assigns an
   available port. Ensure it is reachable as `localhost`; never bind to all
   network interfaces. Use `http://localhost:<assigned-port>/callback` as the
   redirect URI.
2. Open `https://www.strava.com/oauth/authorize` in the default browser with the
   client ID, redirect URI, `response_type=code`, an unpredictable `state`, and
   **only `scope=activity:read_all`**. Print the authorization URL as a fallback
   when browser launch is unavailable.
3. Accept only the expected callback path with matching state. Handle denial,
   missing or declined scopes, malformed callbacks, and a bounded timeout. Close
   the listener after completion, cancellation, or timeout.
4. Exchange the code at `POST https://www.strava.com/oauth/token`. Confirm the
   required scope was granted. Cache the access token, refresh token, expiry,
   and athlete ID under `data/.runner-ai/strava/`, subject to the
   [shared credential rules](README.md#private-data-credentials-and-state).
5. Reuse valid tokens without opening a browser. Refresh according to the stored
   expiry, atomically retain the latest returned refresh token, and retry an
   expired-token request at most once after refresh. Ask for authorization again
   if refresh credentials are rejected; keep existing source data and sync state.

`activity:read_all` includes private “Only You” runs; `activity:read` excludes
them. Request no profile or write scopes. Strava offers no run-only permission,
so apply the activity filter below. The flow, localhost redirect support, scopes,
and refresh behavior follow [Strava's authentication documentation](https://developers.strava.com/docs/authentication/).

## Activity API and selection

Use these authenticated read endpoints:

| Purpose | Endpoint |
| --- | --- |
| Paginated activity summaries | `GET /api/v3/athlete/activities` |
| Selected activity details | `GET /api/v3/activities/{id}` |

Accept only `sport_type` values **`Run`, `TrailRun`, and `VirtualRun`**. Include
manual or treadmill activities classified as runs. Exclude all other and unknown
sports before detail requests or folder creation. Recheck the type on a detail
response before saving it; do not persist unfiltered listing responses.

The [Strava API reference](https://developers.strava.com/docs/reference/) defines
these endpoints and types. Use `start_date` for UTC window comparisons and the
calendar date in `start_date_local` for a new folder. Do not reinterpret the local
clock value as UTC. Source identity is the Strava activity ID, including when a
date or title changes.

## Pagination adapter

- Request `page` / `per_page` pages bounded by the selected history start and
  fixed scan-start time. Adapt the API's strict `after` boundary so an activity
  exactly at the inclusive `--since` timestamp is included, and filter locally.
- Continue until the unfiltered API response is an empty activity page. A page
  without runs is not the end of the list.
- List the selected history on each invocation, not just the recent refresh
  overlap. Let the [shared sync engine](README.md#incremental-fetching-and-recovery)
  choose which details to download or refresh. Its checkpoint is not a cutoff
  for discovering backdated uploads.
- Respect the application's actual [rate-limit headers](https://developers.strava.com/docs/rate-limits/).
  Do not hard-code an assumption that the full import will fit in one quota.

The [activity-list parameters](https://developers.strava.com/docs/reference/#api-Activities-getLoggedInAthleteActivities)
filter by when an activity occurred, rather than its upload or modification time.
An older edit to an existing record is therefore covered by `--full`, not by an
assumption that it will appear as a newly dated activity.

## Provider-specific verification and scope

In addition to the shared contract suite, verify the random-port callback,
localhost resolution, wrong state, unrelated paths, denial, missing permissions,
timeout cleanup, token expiry and rotation, account changes, mixed-sport pages,
all three run types, the inclusive date boundary, and source-local dates.

Separate stream downloads and uploads are outside the first milestone. A Strava
MCP server may be considered as a later transport if it supplies the same source
identity and coverage guarantees; no particular MCP server is selected or
implemented by this specification.
