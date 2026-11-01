"""Each table that records what happened or what is going on has one writer."""

import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "app"
# Migrations change the schema and move data once; they are the one exception.
EXEMPT = ("migrations", "static")


def writes_to(table: str) -> re.Pattern[str]:
    """Any statement that changes the table, however its keywords are spaced or cased."""
    return re.compile(
        rf"\bUPDATE(\s+OR\s+\w+)?\s+{table}\b"
        rf"|\b(INSERT|REPLACE)(\s+OR\s+\w+)?\s+INTO\s+{table}\b"
        rf"|\bDELETE\s+FROM\s+{table}\b",
        re.IGNORECASE,
    )


def inserts_into(table: str) -> re.Pattern[str]:
    return re.compile(rf"\b(INSERT|REPLACE)(\s+OR\s+\w+)?\s+INTO\s+{table}\b", re.IGNORECASE)


def changes_rows_of(table: str) -> re.Pattern[str]:
    return re.compile(
        rf"\bUPDATE(\s+OR\s+\w+)?\s+{table}\b|\bDELETE\s+FROM\s+{table}\b", re.IGNORECASE
    )


def joined(source: str) -> str:
    """The source with adjacent string literals run together, so a statement split across lines
    of a Python file still reads as one."""
    return re.sub(r"""(["'])\s*\n\s*[rfb]*\1""", "", source)


def app_sources():
    for path in sorted(APP.rglob("*")):
        relative = path.relative_to(APP)
        if path.suffix in (".py", ".sql") and relative.parts[0] not in EXEMPT:
            yield relative.as_posix(), joined(path.read_text())


def outside(pattern: re.Pattern[str], owner: str) -> list[str]:
    return [name for name, source in app_sources() if name != owner and pattern.search(source)]


def test_only_the_job_runner_writes_the_jobs_table():
    assert outside(writes_to("jobs"), "jobs.py") == []


def test_only_the_events_module_adds_to_the_record():
    assert outside(inserts_into("events"), "events.py") == []


def test_the_record_is_never_changed_after_it_is_written():
    assert outside(changes_rows_of("events"), "") == []


def test_only_the_gate_writes_the_pause():
    assert outside(writes_to("youtube_pause"), "gate.py") == []


def test_the_owners_do_write_what_they_own():
    sources = dict(app_sources())
    assert writes_to("jobs").search(sources["jobs.py"])
    assert inserts_into("events").search(sources["events.py"])
    assert writes_to("youtube_pause").search(sources["gate.py"])


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE jobs SET status = 'queued'",
        "update  jobs\n   set status = 1",
        "UPDATE OR IGNORE jobs SET status = 1",
        "INSERT INTO jobs (kind) VALUES ('scan')",
        "INSERT OR IGNORE INTO jobs (kind) VALUES ('scan')",
        "REPLACE INTO jobs (kind) VALUES ('scan')",
        "DELETE FROM jobs WHERE id = 1",
        'conn.execute("UPDATE "\n    "jobs SET status = 1")',
        "conn.execute(\n    'DELETE FROM '\n    'jobs')",
    ],
)
def test_the_scan_catches_a_write_however_it_is_spelled(statement):
    assert writes_to("jobs").search(joined(statement))


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT * FROM jobs WHERE status = 'queued'",
        "UPDATE jobs_new SET status = 1",
        "UPDATE subscriptions SET enabled = 0",
        "INSERT INTO job_events VALUES (1)",
        "FROM jobs j LEFT JOIN videos v",
    ],
)
def test_the_scan_leaves_reads_and_other_tables_alone(statement):
    assert not writes_to("jobs").search(joined(statement))


def test_the_scan_catches_the_other_two_tables_too():
    assert inserts_into("events").search("INSERT INTO events (event) VALUES ('x')")
    assert changes_rows_of("events").search("DELETE FROM events")
    assert writes_to("youtube_pause").search("UPDATE youtube_pause SET refusals = 0")
