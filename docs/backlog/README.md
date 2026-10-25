# Backlog

Where work on YouHoard is planned and tracked, in git. One file per workstream; each lists decisions, then tasks as checkboxes, ticked in the same commit that finishes them.

| File | Workstream | Status |
| --- | --- | --- |
| [redesign.md](redesign.md) | Rebuild the frontend in the Strongroom design, plus the API additions it needs ([contract](redesign-api.md)) | Done; follow-ups open |

## Working agreements

- Design reference: [docs/design/mockup.html](../design/mockup.html), opened directly in a browser. Its header comment holds the type, color and layout rules.
- Each fact appears once in the UI. Don't repeat a number in two places, and no subtitles under page titles.
- There are no users yet: rebuilding beats patching, and the schema can still change through a new migration.

## Known issues

- The Docker image is only smoke-tested in CI: it starts, answers the health check and runs as 99:100. It hasn't run a real library yet.
- The TubeArchivist import has only run against synthetic backups.
