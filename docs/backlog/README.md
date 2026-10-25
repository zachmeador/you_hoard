# Backlog

Where work on YouHoard is planned and tracked, in git. One file per workstream; each lists decisions, then tasks as checkboxes, ticked in the same commit that finishes them.

| File | Workstream | Status |
| --- | --- | --- |
| [redesign.md](redesign.md) | Rebuild the frontend in the Strongroom design, plus the API additions it needs ([contract](redesign-api.md)) | Done; follow-ups open |

## Working agreements

- Large building work goes to Sonnet 5.5 subagents with a written brief. The main session plans, reviews, integrates and verifies.
- Design reference: [docs/design/mockup.html](../design/mockup.html), opened directly in a browser. Its header comment holds the type, color and layout rules.
- Each fact appears once in the UI. Don't repeat a number in two places, and no subtitles under page titles.
- There are no users yet: rebuilding beats patching, and the schema can still change through a new migration.

## Known issues

- The Docker image has never been built locally; only CI builds it.
- The TubeArchivist import has only run against synthetic backups.
