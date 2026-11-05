# Working on Runner AI

## Start here

1. Read `README.md` for the storage contract and `nike.md` for the implemented
   importer. `strava.md` is a specification, not evidence of a working importer.
2. Read **`data/GOALS.md` before asking about goals or scheduling**. It contains
   athlete-provided race candidates, the goal, and constraints such as the day
   of the long run. Preserve these constraints in any proposed plan.
3. Look for additional `AGENTS.md` files and athlete notes inside `data/` before
   analysing that checkout. Distinguish explicit athlete input from agent output.
   In particular, read `data/ATHLETE-NOTES.md` when present: it records reported
   symptoms, recovery and fuelling without turning them into diagnoses.
4. Inspect both repositories with `git status --short` and
   `git -C data status --short`. `data/` is a separate private Git checkout and is
   ignored by this parent repository. Ordinary `rg --files` skips it.

## Where the evidence lives

- `data/run-YYYY-MM-DD-<provider>-<activity-id>/`: retained activity records.
- `nike.json`: original Nike activity details; `import.json`: provider, activity
  ID, library revision, and the source or fallback timezone used for dating.
- `data/GOALS.md` and athlete-written notes: goals, constraints, race history,
  recovery, pain, and missing records. These take precedence over old advice.
- `data/.sync-state/nike/<account>/state.json`: non-secret import metadata,
  including `complete`, `pending_ids`, `since`, `last_success`,
  `last_success_since`, `coverage`, `timezone`, and possible duplicate hints.
- `slop/`: ignored, generated analysis, calculation scripts, reports and charts.
  These are dated interpretations, never a replacement for source records.

Use targeted listings instead of dumping the whole private tree:

```sh
rg --files --hidden --no-ignore data -g 'AGENTS.md' -g '*.md' -g '!**/.git/**' -g '!**/.sync-state/**'
python3 - <<'PY'
from pathlib import Path
files = sorted(Path('data').glob('run-*/nike.json'))
print('Retained Nike records:', len(files))
if files:
    print('First folder:', files[0].parent.name)
    print('Last folder:', files[-1].parent.name)
PY
```

Never read or print credential contents for a training analysis. In particular,
avoid `data/nike-tokens.json`, `data/strava-tokens.json`, and `data/strava-mcp/`.
Do not recursively search `.sync-state/`: it also contains wider caches and
private logs. Read the selected `state.json` and its relevant fields only.
Do not put personal training data, GPS coordinates, tokens, or race plans into
tracked code, instructions, issues, or public output. Keep reports in `slop/`.

## How to calculate Nike training totals

Read the JSON structure; do not infer units from field names alone. The
following fields were verified against the retained Nike records:

| Quantity | Source / calculation |
| --- | --- |
| Identity | `(import.json.provider, nike.json.id)`; check `activity_id` agrees |
| Status | Check `type == "run"`, `status == "COMPLETED"`, and `delete_indicator` |
| Start | `start_epoch_ms`: milliseconds since the UTC epoch |
| Local date | Convert that UTC instant using the timezone/date basis in `import.json`; the folder date alone can be stale after a source correction |
| Distance | `summaries[]` entry with `metric == "distance"` and `summary == "total"`; current Nike distance streams declare `KM` |
| Active duration | `active_duration_ms / 60000` minutes |
| Elapsed duration | `(end_epoch_ms - start_epoch_ms) / 60000` minutes, including pauses |
| Active pace | Active minutes / distance in km |
| Elapsed pace | Elapsed minutes / distance in km; use this for race cutoffs |
| Average heart rate | `summaries[]`, `metric == "heart_rate"`, `summary == "mean"`; current streams declare `BPM` |
| Elevation gain | `summaries[]`, `metric == "ascent"`, `summary == "total"`; current streams declare `M` |
| Kilometer markers | `moments[]` with `key == "split_km"`; timestamp differences give elapsed, not active, splits |

Check for missing or multiple matching summaries and incompatible stream units
instead of silently choosing or summing different representations. Do not sum
pace samples or take an unweighted average of activity paces. Compute aggregate
pace from total duration / total distance. Nike `distance` stream values are
increments in the inspected records, not cumulative distance; inspect the
stream before reconstructing splits. Different sources can provide parallel
streams of one metric: do not sum those together.

## Analysis workflow

1. State the analysis date, timezone, last recorded activity, archive boundaries,
   sync checkpoint and coverage limitations. `complete` means the importer
   completed its provider selection, not that every real-world run is present.
   The current Nike library excludes manually entered activities.
2. Validate IDs and chronology; check likely duplicate records and overlapping
   timestamps before aggregating. API/MCP representations of the same Strava ID
   count once. Cross-provider matches require checking start, distance and time.
   Keep distinct same-day sessions distinct. Flag tiny/accidental recordings
   and quantify their effect; never silently delete or merge source records.
3. Prioritize the most recent 8–12 weeks; use the wider year for continuity and
   earlier long runs. Report weekly run count, distance, duration and longest
   single run. Distinguish calendar months, complete Monday–Sunday weeks and
   rolling windows. Do not compare a partial current week with full weeks.
4. Examine the last 4/8/12 **complete** weeks, recent long-run progression,
   pauses, breaks, intensity and recovery. Check increases in both weekly
   volume and an individual run relative to the preceding 30 days. A generic
   weekly 10% rule is not a proven safety threshold.
5. Compare similar sessions with context: surface, elevation, weather, pauses,
   recording device and missing HR. Average HR alone does not establish zones,
   aerobic threshold, medical fitness, or fatigue. Do not infer actual interval
   structure from a Friday timestamp or title; inspect streams if needed.
   Before prescribing interval pace, inspect the athlete's previous fast and
   recovery segments in the retained streams. A whole-run average is not a
   fast-segment pace. State the reconstruction method and uncertainty when lap
   markers are absent; distinguish instantaneous pace, rolling windows and
   measured interval averages. If the data cannot establish the pace or session
   structure, say what is missing instead of inventing a precise prescription.
6. Verify the chosen race's current official date, finish limit, intermediate
   cutoffs and timing basis. Notes can be stale. If gun-time versus chip-time
   cutoff enforcement is unclear, explicitly retain that uncertainty and allow
   a start-delay margin. Count food, toilet and walking stops in elapsed time.
7. Give a conditional assessment of finishing and of meeting cutoffs, separate
   from a time-performance forecast. Do not invent a percentage probability or
   extrapolate a short run to a guaranteed marathon. Ask only for consequential
   missing context: chosen race, recent pain/illness, long-run recovery,
   fuelling, missing activity and available days.
8. Preserve the athlete's long-run day. Propose a dated, adaptable plan with
   easy running, recovery weeks, rehearsed fuelling, and a taper. Do not try to
   recover missed mileage, force a 30–32 km session, or increase distance and
   intensity together. Explain when to repeat, shorten or skip a session.
   Include numerical pace ranges in **min/km**, specify whether they describe
   running segments or total elapsed pace, and give an effort-based override
   for hills, symptoms and weather. Respect the athlete's stated priority among
   races; an earlier preparatory race must not silently replace the main goals.
   Present official cutoffs separately from proposed personal checkpoint targets,
   with elapsed time, local clock time, stop allowance and remaining margin.
9. Check primary sports-medicine/nutrition sources for consequential advice.
   Cite sources near supported claims and distinguish evidence from coaching
   judgment. New or persistent pain changes the plan; do not diagnose from logs.
10. Save dated results and reproducible calculations under `slop/`, then verify
    key figures against original records and check the Git diff. Update
    `data/GOALS.md` only with explicit athlete input, not inferred goals or
    agent recommendations. Do not commit or push either repository unless asked.

## Refreshing the archive

Existing records are sufficient for a read-only analysis unless freshness is
material. If a refresh is needed, follow `nike.md`; from the parent root:

```sh
uv run --locked src/nike/sync.py --log
```

This reuses saved configuration and credentials. Authentication requires the
library's interactive `--login` workflow; never request or paste a token in chat.
Do not use `--full`, `--all-history`, or change the date boundary just to analyse
the current training block. Never overwrite source records with derived data.

For importer code changes, follow the offline verification commands in
`nike.md`. Documentation-only analysis work does not require authenticated
fetching or changes to the importer.
