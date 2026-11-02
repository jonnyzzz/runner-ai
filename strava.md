# Strava integration specification

Use either the custom Strava API importer or a Strava MCP server. These are
independent approaches with separate authentication, configuration, and token
storage. Both produce records meeting the
[common data requirements](README.md#integration-specification).

Local Python code is preferably run with uv. No common Python implementation
with the Nike+ library or MCP server is required.

## Custom importer: Strava API

Planned implementation: `src/strava/sync.py`. From the repository root:

```sh
uv run src/strava/sync.py
```

This script is not implemented yet. It owns its API client and OAuth flow.

### Setup and credentials

Register an application at [Strava API Settings](https://www.strava.com/settings/api),
following the [Getting Started guide](https://developers.strava.com/docs/getting-started/).
Set **Authorization Callback Domain** to `localhost`, without a scheme, path, or
port. `STRAVA_CLIENT_ID` and `STRAVA_CLIENT_SECRET` configure **this custom OAuth
app path only**; supply them through the environment.

Subscription or API-access eligibility may depend on the selected integration
and app tier. Strava's current guide lists a subscription as a prerequisite for
creating a custom app. Check the current dashboard requirements rather than
making a blanket claim that private runs always require a subscription. Private
activity visibility also requires the appropriate OAuth scope below.

Save access and refresh tokens, expiry, and athlete ID in
**`data/strava-tokens.json`**. Apply the
[credential exclusion and permission rules](README.md#credential-files-under-data)
before writing it. Keep the client secret supplied through the environment out
of this file.

### OAuth login

1. Start a loopback-only HTTP listener on an OS-assigned free port by requesting
   port `0`. Ensure it is reachable as `localhost`. Redirect to
   `http://localhost:<assigned-port>/callback`.
2. Open Strava's authorization page in the default browser with the client ID,
   redirect URI, `response_type=code`, unpredictable `state`, and **only
   `scope=activity:read_all`**. Print the authorization URL if browser launch
   is unavailable.
3. Validate the callback path and state, verify granted scope, and handle denial,
   malformed callbacks, and a bounded timeout. Close the listener on completion,
   cancellation, or timeout.
4. Exchange the code at `POST https://www.strava.com/oauth/token`. Persist the
   returned tokens and expiry in the selected credential file.
5. Reuse valid tokens; refresh expired tokens and atomically save the latest
   returned refresh token. Reauthorize if refresh credentials are rejected,
   preserving run records and import progress.

`activity:read_all` includes private “Only You” activities; `activity:read` omits
them. Request no profile or write scopes. Strava has no run-only permission, so
filter locally. Follow [Strava's authentication documentation](https://developers.strava.com/docs/authentication/).

### Activity fetching and persistence

Use `GET /api/v3/athlete/activities` for paginated summaries and
`GET /api/v3/activities/{id}` for selected run details. Accept only `sport_type`
values **`Run`, `TrailRun`, and `VirtualRun`**, including manual and treadmill
runs classified accordingly. Skip unrelated and unknown sports before detail
requests or folder creation.

Use `start_date` for UTC history selection and the calendar date in
`start_date_local` for new folders. Keep source details in
`data/run-YYYY-MM-DD-strava-<id>/strava.json`, preserving original fields.

The custom script should expose `--since YYYY-MM-DD`, `--all-history`, and
`--full` for the [common history and refresh behavior](README.md#history-and-incremental-imports).
Revisit summaries in the selected period to discover missing or backdated runs;
reuse existing details and refresh recent corrections. A seven-day refresh
overlap is a reasonable initial policy; `--full` refreshes older existing runs.

Apply the API's `after` / `before` bounds and `page` / `per_page` pagination,
including records exactly at the inclusive start boundary. Continue until the
unfiltered response is empty, even through pages without runs. Follow the
[API reference](https://developers.strava.com/docs/reference/#api-Activities-getLoggedInAthleteActivities)
and [rate-limit headers](https://developers.strava.com/docs/rate-limits/).

## MCP integration

Select a Strava MCP server independently of the custom importer. No server is
selected yet; its documented capabilities and setup must be verified when chosen.
Prefer a uv-launched Python server or local helper where supported, while using
the selected server's own runtime and configuration.

### Setup and credentials

- **The MCP server owns authentication and token lifecycle**, including consent,
  expiry, refresh, and its credential format. Follow its security guidance.
- The custom importer's `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`, and
  `data/strava-tokens.json` are not MCP configuration. A server may have its own
  client credentials; use only its documented setup.
- Configure the server's supported credential files under
  **`data/strava-mcp/`**, separately from the custom OAuth file. Record its exact
  native filenames and verify the
  [data-repository exclusions and permissions](README.md#credential-files-under-data).
  Select a local or self-hosted server supporting this location; Runner AI must
  not parse or rewrite its token cache to imitate the custom importer.
- Prefer read-only activity access. Confirm support and permission for private
  “Only You” runs where needed. Do not infer private access or required scopes
  from the custom importer's configuration.
- Check subscription and app-access requirements for that particular server and
  authorization method; they may differ from creating a personal API app.

### Fetching and persistence

Use the server's supported activity-list and detail tools, date filters,
pagination, and incremental behavior. Export only runs within the selected
history, following the [common data requirements](README.md#run-records-and-layout).
If the tools cannot supply stable IDs, sufficient history, or run classification,
report the limitation rather than claiming a complete import.

Save retained MCP source responses in
`data/run-YYYY-MM-DD-strava-<id>/strava-mcp.json`, with MCP server/tool provenance
in `import.json`. Preserve any `strava.json` already in that activity folder.
API and MCP records with the same Strava ID are representations of one run.
Server-managed credentials stay out of those activity files.

## Verification

For the API path, check callback validation and cleanup, scope denial, token
rotation, account changes, mixed-sport pages, date boundaries, and reruns. For
MCP, check the chosen server's credential ownership and configured paths,
permissions, tool pagination, private-activity coverage, and retained output.
Verify common data outcomes independently for each approach; no shared Python
code or token implementation is required.
