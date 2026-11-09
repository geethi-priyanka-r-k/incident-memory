"""Seed 15 resolved incidents over 60 days plus 3 outcome records for demo.

Replaces duplicate/test rows. Realistic dates from 2026-09-08 to 2026-11-05.
No customer names or invented metrics. Idempotent: clears existing non-demo
open rows, then inserts the 15 seeded incidents and 3 outcome records.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import db
from seed_data import INCIDENTS, as_memory

# One resolved incident per seed entry, spread across 60 days.
DATES_UTC = [
    "2026-09-08T09:00:00+00:00",
    "2026-09-15T10:15:00+00:00",
    "2026-09-22T11:30:00+00:00",
    "2026-09-29T08:45:00+00:00",
    "2026-10-06T14:00:00+00:00",
    "2026-10-13T09:20:00+00:00",
    "2026-10-20T13:10:00+00:00",
    "2026-10-27T10:00:00+00:00",
    "2026-11-03T11:55:00+00:00",
    "2026-09-10T09:30:00+00:00",
    "2026-09-17T10:40:00+00:00",
    "2026-09-24T08:15:00+00:00",
    "2026-10-01T12:00:00+00:00",
    "2026-10-08T09:50:00+00:00",
    "2026-10-15T14:25:00+00:00",
]

SEVERITIES = ["P2", "P1", "P2", "P1", "P1", "P3", "P1", "P2", "P2", "P2", "P1", "P2", "P1", "P1", "P2"]
SOURCES = ["web", "monitoring", "support", "monitoring", "web", "tester", "support", "web", "monitoring", "web", "monitoring", "support", "web", "monitoring", "support"]

# Outcome records: (incident number 1-15, result, note)
OUTCOMES = [
    (11, "worked", "Pool size increase held under peak load; saturation alerts fired once."),
    (13, "partly", "Rate limiting slowed the attack but some attempts still reached login."),
    (7, "didnt_work", "Secondary provider took over but failed during regional failover."),
]


def clear_duplicate_rows() -> int:
    with sqlite3.connect(db.DATABASE_PATH) as connection:
        row = connection.execute("SELECT COUNT(*) FROM incidents WHERE is_demo = 0").fetchone()
        before = int(row[0]) if row else 0
        connection.execute("DELETE FROM diagnoses WHERE incident_id IN (SELECT id FROM incidents WHERE is_demo = 0)")
        connection.execute("DELETE FROM incident_events WHERE incident_id IN (SELECT id FROM incidents WHERE is_demo = 0)")
        connection.execute("DELETE FROM outcomes WHERE incident_id IN (SELECT id FROM incidents WHERE is_demo = 0)")
        connection.execute("DELETE FROM incidents WHERE is_demo = 0")
        return before


def seed_incidents() -> list[int]:
    ids = []
    now = datetime.now(timezone.utc)
    for index, incident in enumerate(INCIDENTS):
        resolved_at = DATES_UTC[index]
        created_at = (datetime.fromisoformat(resolved_at) - timedelta(minutes=20 + index * 6)).isoformat()
        incident_id = db.create_incident(
            title=incident["report"][:160],
            report=incident["report"],
            incident_type=incident["type"],
            severity=SEVERITIES[index],
            source=SOURCES[index],
            reported_by="Demo seed",
            is_demo=False,
        )
        with sqlite3.connect(db.DATABASE_PATH) as connection, connection:
            connection.execute(
                """
                UPDATE incidents
                SET status = 'resolved', created_at = ?, resolved_at = ?,
                    root_cause = ?, fix = ?, not_worked = ?, didnt_work = ?,
                    memory_sync = 'synced'
                WHERE id = ?
                """,
                (
                    created_at,
                    resolved_at,
                    incident["root_cause"],
                    incident["fix"],
                    incident["didnt_work"],
                    incident["didnt_work"],
                    incident_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO incident_events (incident_id, event, created_at)
                VALUES (?, ?, ?)
                """,
                (incident_id, "Incident reported (seeded demo data)", created_at),
            )
            connection.execute(
                """
                INSERT INTO incident_events (incident_id, event, created_at)
                VALUES (?, ?, ?)
                """,
                (incident_id, "Resolution saved and retained (seeded demo data)", resolved_at),
            )
        db.save_briefing(
            incident_id,
            {
                "likely_match": f"Related {incident['type'].lower()} resolution.",
                "match_confidence": 70 + (index % 20),
                "root_cause": incident["root_cause"],
                "fix_steps": [incident["fix"]],
                "skip_these": [incident["didnt_work"]] if incident["didnt_work"] else [],
                "memories": [as_memory(incident)],
            },
            [as_memory(incident)],
            70 + (index % 20),
            created_at=resolved_at,
        )
        ids.append(incident_id)
    return ids


def seed_outcomes(incident_ids: list[int]) -> int:
    added = 0
    for position, result, note in OUTCOMES:
        incident_id = incident_ids[position - 1]
        with sqlite3.connect(db.DATABASE_PATH) as connection, connection:
            connection.execute(
                """
                INSERT INTO outcomes (incident_id, result, note, created_at, user_id, memory_sync)
                VALUES (?, ?, ?, ?, NULL, 'synced')
                """,
                (incident_id, result, note, DATES_UTC[position - 1]),
            )
        added += 1
    return added


def main() -> None:
    db.initialize()
    removed = clear_duplicate_rows()
    incident_ids = seed_incidents()
    outcomes_added = seed_outcomes(incident_ids)
    print(f"Removed {removed} duplicate/test rows.")
    print(f"Added {len(incident_ids)} resolved incidents over 60 days.")
    print(f"Added {outcomes_added} outcome records (IDs: {[f'#{i}' for i in incident_ids]}).")


if __name__ == "__main__":
    main()
