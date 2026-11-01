# Job core

The app makes decisions without recording why, and nothing owns job state. Each operational question took an investigation of logs, the database and old notes. This work makes every question below answerable from the app, or from one named place in the code.

| Question | Answer after this work |
| --- | --- |
| Why is this job paused? | The job's `reason`, and its history on the Activity page |
| Why is it waiting, and for what? | `state`, `waiting_on` and `waits_until` from one view |
| What can change a job's status? | `JobRunner._move` and the `MOVES` table in `app/jobs.py` |
| What runs next? | `QUEUE_ORDER` in `app/jobs.py` |
| How fast is it going? | `app/pace.py`, and the real rate on System |
| What did it do yesterday? | The Activity page; one log line per event |
| Why didn't this video download? | An entry's `skip_reason`; a video's `lost_at` |

## Decisions

### One owner for job state

- `app/jobs.py` is the only code that writes the `jobs` table. A test fails if `UPDATE jobs`, `INSERT ... INTO jobs` or `DELETE FROM jobs` appears anywhere else in `app/`, migrations aside. Reading jobs elsewhere stays allowed.
- All status changes go through one method, `JobRunner._move`, checked against a table at the top of the module:

  ```python
  MOVES = {
      "queued": ("paused", "running", "cancelled"),
      "paused": ("queued", "cancelled"),
      "running": ("queued", "completed", "failed", "cancelled"),
      "failed": ("queued",),
      "cancelled": ("queued",),
      "completed": (),
  }
  ```

- `_finish(**fields)` goes. One private writer holds the single-row `UPDATE jobs SET`; `_move` validates and calls it, and it records the event in the same transaction.
- Routes do no job logic. They call named `JobRunner` methods: `pause`, `resume`, `retry`, `run_now`, `cancel`, `pause_many`, `resume_many`, `retry_failed`, `remove`, `clear_finished`, plus reads `list_jobs`, `job_ids`, `counts`. New exceptions `NotAllowed` and `JobNotFound` map to 409 and 404 in `main.py`, the way `Paused` maps to 503.
- Run now becomes `POST /api/jobs/{id}/run-now`. It clears `run_after`, resets `refusals` and raises the job to `NOW`, so it really is next, and keeps `attempts` and `error`. It answers 409 while YouTube is paused.
- `retry-failed` skips jobs whose reason is `gone`, so "not retried" is true.
- Rename the exception `Refused` to `Declined` (a job that declined to run, like a rescan that would mark too much missing), so "refused" only ever means YouTube refused.

### A record of what happened

- New table `events`, append-only. `app/events.py` holds the one write helper, `record()`, and the read used by `GET /api/events`. No other code inserts into it, and a test enforces that.
- `record()` also writes the log line, at INFO by default, so the log and the table can't disagree. It takes a `Database` or an open connection, so it joins the caller's transaction.
- `actor` is `owner` (came through the API), `app` or `cli`.
- Ids in `events` are plain integers, not foreign keys: the record outlives what it describes. "Clear finished" removes job rows, never events.
- Events:
  - `job.queued`, `job.started`, `job.completed`, `job.failed`, `job.retrying`, `job.refused`, `job.deferred` (premiere or live), `job.returned` (back to the queue on a restart or a pause), `job.paused`, `job.resumed`, `job.cancelled`, `job.retried`, `job.run_now`, `job.removed`, `jobs.cleared`
  - `youtube.refused`, `youtube.extras_refused`, `youtube.failures`, `youtube.paused`, `youtube.resumed`
  - `subscription.off`, `subscription.on` (with how many downloads moved), `trash.purged`, `scan.completed` (the command line's rescan, actor `cli`), `app.started`, `app.stopped`
- `job.completed` carries a short summary in `detail`: resolution for a download, counts for a check or scan. If a download lost subtitles or chat to a refusal, the summary says so.
- No retention: about 10 MB a year at this volume.

### Jobs say why

New columns on `jobs`:

- `origin`: `user` (asked for by hand), `policy` (a subscription's download policy) or `schedule` (a due check). Required by `enqueue`. This replaces inferring who asked from `priority`.
- `reason`: why the job is in its current status, from a `Reason` StrEnum in `app/jobs.py`. NULL when there's nothing to explain, including while running or completed.

  | Status | Reasons |
  | --- | --- |
  | paused | `asked`, `subscription_off` |
  | queued | `retry`, `premiere`, `refused` |
  | failed | `gone`, `needs_account`, `declined`, `error` |

- `resume_reason`: what `reason` goes back to when a paused job resumes, so a pause doesn't make a job forget it's waiting out a retry or a premiere. Not in the API.
- `refusals`: how many times YouTube refused this job. A refused job goes behind every job YouTube hasn't refused, so `QUEUE_ORDER = "j.refusals, j.priority DESC, j.id"`, shared by the claim and the job list. This replaces lowering `priority`.
- `via_subscription_id`: the subscription a download came through, `REFERENCES subscriptions (id) ON DELETE SET NULL`, so deleting a subscription leaves its queued downloads running on library defaults, as now. It replaces `options.subscription_id`; `subscription_id` stays the target of a check.

`priority` becomes a named `Priority` IntEnum: `ROUTINE = 0`, `SCAN = 1`, `ASKED = 5`, `URGENT = 10`, the current values, plus `NOW = 20` for Run now. No call site passes a bare number.

### Waiting is derived, once

- Nothing copies the YouTube pause onto job rows. `_hold_queued`, `earliest_start` and the gate's listeners go. `run_after` means only "this job's own retry or premiere wait".
- A new file, `app/views.sql`, holds the rules derived from tables. `Database.migrate()` drops and recreates its views at every start, after migrations, so a rule change needs no migration. `video_status` moves there.
- View `job_state` adds to every `jobs` column:
  - `state`: the status, except a queued job is `waiting` while its own `run_after` is ahead, or while YouTube is paused if it's a `download` or `check`. These are the `Status` values the API already filters on.
  - `wait_ends`: when a waiting job can run, the later of the two.
  - `waiting_on`: `youtube` when the pause is the later of the two, otherwise the job's `reason`.
- Every read uses it: the job list, counts, ids, `/api/system`, `video_status`, and the claim. So "Up next" and "what the worker will take" can't disagree. The frontend stops computing any of this.
- Read the pause with a scalar subquery on `youtube_pause`, not a join, so `video_status` can still flatten the view. `gate._save()` keeps that row current, and it's the one writer of that table.

### One place for pace

- New module `app/pace.py` holds every number that sets how fast YouHoard talks to YouTube: `REQUEST_SLEEP`, `LISTING_SLEEP`, `SUBTITLE_SLEEP`, `REST`, `BLOCK_PAUSES`, `EXTRAS_PAUSE`, `FAILURE_STREAK`, `FAILURE_PAUSE`, `RETRY_DELAYS`. Its docstring names the two that live elsewhere: `max_concurrent_downloads` (a setting) and `YTDLP_REQUEST_INTERVAL` (config).
- `REST = {"download": (120.0, 240.0), "check": (20.0, 40.0)}` is the new, slower pace: about three minutes between downloads.
- The gate enforces rest across all workers, not per worker. `gate.can_start(kind)` is true once the rest since the last start or finish of that kind has passed; `gate.started(kind)` and `gate.finished(kind)` set it. `_claim` holds one `asyncio.Lock` around check, claim and `started`, so two workers can't both slip through. Jobs stay `queued` during a rest instead of sitting in `running`.
- `_download_worker` loses its `_rest` call; `_worker` gains the same pacing for checks through `_claim`.
- `/api/system` adds `pace` and `activity`, read from `events` so "Clear finished" doesn't erase them.
- `/api/jobs` and `/api/system` report `download_rest_until`, so a queue that's resting can say so rather than look stuck.

### Gate rules

These close the open review findings on the gate.

- A refused subtitle or chat pauses for a fixed `EXTRAS_PAUSE` (one hour) with the refusal as the reason. It doesn't climb the ladder, and the download still counts as a success, because the video came through.
- Only a completed download resets the ladder. `fetch_video` no longer does.
- `FAILURE_STREAK` (5) generic download failures in a row pause for `FAILURE_PAUSE` (one hour), off the ladder. Any completed download resets the streak. The streak lives in memory.
- `hold()` takes an optional reason, actor and cause, so these and the owner's manual pause share it.
- A pause keeps its `cause` (`asked`, `refused`, `extras` or `failures`) in `youtube_pause`, so the app can say what started it without reading the words of `reason`.
- Calls past the gate stop too. `Paused` moves to `app/youtube.py`, still not a `YouTubeError`. `YouTube.before_call`, a callable the gate sets, runs in `_run` after the spacing lock on every attempt, and for each entry in `list_entries`. It raises `Paused`, which `_run` must pass through rather than classify. A transfer already under way still finishes.

### Subscriptions

- The rule for switching a subscription off and on moves out of the PATCH route into one function in `app/checks.py`.
- Off (disabled, or policy `none`) pauses its `origin = 'policy'` downloads with reason `subscription_off`. On resumes exactly those. Downloads the owner paused or asked for by hand aren't touched either way.
- `apply_policy` returns 0 for a disabled subscription, whoever calls it, and off runs before it in the same transaction.
- `queue_due_checks` keeps each subscription's rhythm: the next check is the first time on its own schedule after now, starting from its previous `next_check_at`, with the existing 10% jitter. So a long pause doesn't bunch the checks up for good.

### Why a video wasn't downloaded

- View `entry_selection` in `app/views.sql` gives each inventory entry a `skip_reason`: `policy_none`, `subscription_off`, `removed`, `not_ready`, `tab_off`, `before_subscribing`, or NULL when the policy selects it. `apply_policy` and `ENTRY_SELECT` both read it, so the label and the rule can't drift. It must select exactly what `apply_policy`'s current WHERE clause selects.
- `videos.lost_at` is set when a rescan loses a file and cleared when it's relinked or downloaded again.

## API contract

Jobs, in lists and `GET /api/jobs`:

```json
{
  "id": 12, "kind": "download",
  "status": "queued",
  "state": "waiting",
  "reason": "retry",
  "origin": "policy",
  "waiting_on": "youtube",
  "waits_until": "2026-11-01T18:00:00Z",
  "priority": 0, "refusals": 0, "attempts": 1, "max_attempts": 4,
  "error": "…", "result": null,
  "created_at": "…", "started_at": null, "finished_at": null,
  "video": {"id": 1, "title": "…", "youtube_id": "…"},
  "subscription": null,
  "via_subscription": {"id": 3, "title": "…"},
  "progress": null
}
```

- `run_after` leaves the API. `waits_until` and `waiting_on` are null unless `state` is `waiting`.
- The `status` query parameter keeps its name and filters on `state`. `counts` is keyed by state.
- A video's `job`, and an inventory entry's, becomes `{state, reason, waiting_on, waits_until, attempts, max_attempts, error}`.
- `video_out` adds `error_reason` (the job's reason while the video's status is `failed`) and `lost_at`. Entries add `skip_reason`.
- New: `POST /api/jobs/{id}/run-now`.
- New: `GET /api/events?job_id=&video_id=&subscription_id=&group=jobs|youtube|app&before=&limit=`, newest first, paged by id:

  ```json
  {
    "items": [{
      "id": 90, "at": "…", "event": "job.refused", "actor": "app",
      "job_id": 12, "job_kind": "download",
      "video": {"id": 1, "title": "…"},
      "subscription": null,
      "reason": "refused", "detail": "…"
    }],
    "next_before": 90
  }
  ```

  `next_before` is the id of the page's last item, and null on the last page. `before` is exclusive.

- `GET /api/system` adds:

  ```json
  {
    "pace": {"download_rest": [120, 240], "check_rest": [20, 40]},
    "activity": {
      "downloads_last_hour": 3, "downloads_last_day": 40,
      "last_download_at": "…", "last_refusal_at": "…"
    }
  }
  ```

- `GET /api/jobs` and `GET /api/system` both add `youtube_pause_cause` (null unless paused) and `download_rest_until` (null when no rest is running).

## Migration

`005_job_core.sql` must carry a live database across, including one that has been stalled behind a pause:

- Rebuild `jobs` with the new columns and `AUTOINCREMENT`: events refer to a job by its plain id and Clear finished deletes rows, so an id must never be handed out twice. Add the `events` table.
- Set `origin` before removing `options.subscription_id`: a download with `priority > 0` is `user`, otherwise `policy` if it names a subscription, otherwise `user`. A check with `priority > 0` is `user`, otherwise `schedule`. A scan is `user`.
- Lift negative priorities to 0. The old code lowered a job's priority on each refusal; `refusals` does that work now.
- Set `via_subscription_id` from `options.subscription_id` where that subscription still exists, then remove the key from `options`.
- Clear `run_after` on queued `download` and `check` jobs where it equals `youtube_pause.paused_until`: that was the copied pause.
- Backfill `reason` from `error`, with the same phrases as `BLOCKED`, `GONE`, `INACCESSIBLE` and `WAITING` in `app/youtube.py`. Paused jobs stay NULL: nothing recorded why they were paused, and the UI says so.
- Backfill `job.completed`, `job.failed` and `job.cancelled` events from finished jobs, ordered by `finished_at`, so Activity and the rate have history from the first start.

## Tasks

### Backend

- [x] `005_job_core.sql` and `app/views.sql`, recreated by `Database.migrate()`
- [x] `app/events.py` and `GET /api/events`
- [x] `app/pace.py`; the adapter and gate read from it
- [x] `MOVES`, `_move`, named `JobRunner` methods; `app/api/jobs.py` reduced to routes
- [x] `origin`, `reason`, `refusals`, `via_subscription_id`, `Priority`, `QUEUE_ORDER`; `Refused` renamed `Declined`
- [x] Waiting derived from `job_state`; hold copying removed
- [x] Pace enforced by the gate and `_claim`; `/api/system` reports pace and activity
- [x] Gate rules: extras pause, ladder reset, failure streak, `before_call`
- [x] Subscription off and on, `apply_policy` guard, check rhythm
- [x] `entry_selection`, `skip_reason`, `lost_at`
- [x] Tests, including the boundary test and the migration of a stalled database

### Frontend

- [x] Types and API client follow the contract; `src/lib/jobs.js` loses its error regexes
- [x] Queue page shows why for every row, and Run now uses its endpoint
- [x] Activity page, linked from a job's row
- [x] System shows pace, rate and last success
- [x] Inventory and video pages show `skip_reason` and `lost_at`
- [x] Pause YouTube menu stays on screen at phone width

### Docs

- [x] DESIGN.md and the research doc's pacing table describe what's built
