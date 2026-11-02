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
Importers, agent skills, and training workflows are not implemented yet, so there
are no installation or run commands available. The sections below describe the
intended design.

## Planned workflow

1. **Set up private storage.** Use a separate, private Git repository with the
   same name plus a `-data` suffix, such as `runner-ai-data`, checked out under
   `data/`. Setup tooling should create that repository if it does not exist.
2. **Record goals.** Keep current training goals and planned marathons in
   `data/GOALS.md`.
3. **Import activities.** Fetch runs from Strava and Nike+ into dated run
   directories, keeping the source records for each run together. Strava access
   should use OAuth 2.0 with only the permissions needed to read activities.
4. **Review with an agent.** Use repository instructions and skills to guide
   analysis. The agent must ask follow-up questions when information is missing
   and record the athlete's answers rather than inventing details.
5. **Persist source data.** Commit and push imported activity records and explicit
   user inputs to the private data repository. Keep generated analysis in
   `slop/`, outside Git history.

Python is the intended starting point for the shared tooling; implementation
choices may change as the workflow develops. Integration availability,
authentication, and setup instructions will be documented as importers are built.

## Intended directory layout

```text
runner-ai/
├── README.md
├── LICENSE
├── .gitignore
├── data/                        # Separate private Git repository; ignored here
│   ├── GOALS.md                 # Athlete's goals and planned marathons
│   └── run-YYYY-MM-DD[-suffix]/ # Source records and user notes for one run
└── slop/                        # Temporary agent output; ignored here
```

Use zero-padded dates for run directories. Add a suffix when needed to distinguish
multiple runs on the same day. The `data/` and `slop/` directories are excluded by
this repository's `.gitignore`; they are not created by cloning it.

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
