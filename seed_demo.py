"""Add clearly labeled local demo incidents and sample triage history."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

import db
from seed_data import INCIDENTS, as_memory


def _existing_demo_incident(title: str) -> dict[str, int] | None:
    with closing(sqlite3.connect(db.DATABASE_PATH)) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT id FROM incidents WHERE is_demo = 1 AND title = ?",
            (title,),
        ).fetchone()
    return dict(row) if row else None


def _has_demo_diagnosis(incident_id: int) -> bool:
    with closing(sqlite3.connect(db.DATABASE_PATH)) as connection:
        return connection.execute(
            "SELECT 1 FROM diagnoses WHERE incident_id = ? AND is_demo = 1 LIMIT 1",
            (incident_id,),
        ).fetchone() is not None


def _seed_resolved_incidents() -> int:
    now = datetime.now(timezone.utc)
    added = 0
    for index, incident in enumerate(INCIDENTS):
        title = f"Demo - {incident['type']} - {index + 1:02d}"
        existing = _existing_demo_incident(title)
        if existing and _has_demo_diagnosis(existing["id"]):
            continue

        incident_id = (
            existing["id"]
            if existing
            else db.create_incident(
                title=title,
                report=incident["report"],
                incident_type=incident["type"],
                severity="P2" if index % 4 == 0 else "P3",
                source="tester",
                reported_by="Demo seed",
                is_demo=True,
            )
        )
        if incident["type"] == "Database or data issue":
            days_ago = (3, 10, 20)[index % 3]
        else:
            days_ago = 32 + (index * 7 % 28)
        resolved_at = now - timedelta(days=days_ago)
        created_at = resolved_at - timedelta(minutes=20 + index * 6)
        sample_memory = as_memory(incident)
        confidence = 25 + round(index * 65 / max(1, len(INCIDENTS) - 1))
        briefing = {
            "likely_match": f"Demo sample: a related {incident['type'].lower()} resolution is available.",
            "match_confidence": confidence,
            "root_cause": incident["root_cause"],
            "fix_steps": [incident["fix"]],
            "skip_these": [incident["didnt_work"]] if incident["didnt_work"] else [],
            "memories": [sample_memory],
            "is_demo": True,
        }
        with closing(sqlite3.connect(db.DATABASE_PATH)) as connection, connection:
            connection.execute(
                """
                UPDATE incidents
                SET status = 'resolved', created_at = ?, resolved_at = ?,
                    root_cause = ?, fix = ?, not_worked = ?, didnt_work = ?,
                    memory_sync = 'none', is_demo = 1
                WHERE id = ?
                """,
                (
                    created_at.isoformat(),
                    resolved_at.isoformat(),
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
                (
                    incident_id,
                    "Local demo resolution saved; not sent to Hindsight",
                    resolved_at.isoformat(),
                ),
            )
        db.save_briefing(
            incident_id,
            briefing,
            [sample_memory],
            confidence,
            is_demo=True,
            created_at=resolved_at.isoformat(),
        )
        added += 1
    return added


def _seed_open_knowledge_gap() -> bool:
    title = "Demo - Checkout queue is backing up"
    if _existing_demo_incident(title):
        return False
    now = datetime.now(timezone.utc)
    incident_id = db.create_incident(
        title=title,
        report=(
            "Checkout requests are waiting in the queue and timing out. "
            "The issue started after a traffic increase; no related fix was recalled."
        ),
        incident_type="Performance slowdown",
        severity="P1",
        source="monitoring",
        reported_by="Demo seed",
        is_demo=True,
    )
    briefing = {
        "likely_match": "No related demo memory was found for this sample.",
        "match_confidence": 0,
        "root_cause": "The cause still needs investigation.",
        "fix_steps": [
            "Check queue depth and worker availability.",
            "Compare request volume with database connection usage.",
        ],
        "skip_these": [],
        "memories": [],
        "is_demo": True,
    }
    with closing(sqlite3.connect(db.DATABASE_PATH)) as connection, connection:
        connection.execute(
            """
            UPDATE incidents
            SET created_at = ?, briefing_json = ?, not_worked = ?,
                memory_sync = 'none', is_demo = 1
            WHERE id = ?
            """,
            (
                (now - timedelta(hours=3)).isoformat(),
                json.dumps(briefing),
                "Restarting the workers did not clear the growing queue.",
                incident_id,
            ),
        )
        connection.execute(
            """
            INSERT INTO incident_events (incident_id, event, created_at)
            VALUES (?, ?, ?)
            """,
            (
                incident_id,
                "Monitoring alert received (local demo sample)",
                (now - timedelta(hours=3)).isoformat(),
            ),
        )
    return True


def main() -> None:
    db.initialize()
    resolved_added = _seed_resolved_incidents()
    open_added = _seed_open_knowledge_gap()
    print(
        f"Added {resolved_added} resolved demo incidents and "
        f"{int(open_added)} open demo incident(s) to SQLite."
    )
    print("Sample confidence values are illustrative; no requests were sent to Hindsight or Groq.")


if __name__ == "__main__":
    main()
