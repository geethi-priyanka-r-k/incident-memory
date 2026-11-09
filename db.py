"""SQLite storage for incidents and their diagnosis history."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Iterator

DATABASE_PATH = Path(__file__).with_name("incidents.db")
SOURCES = ("web", "support", "tester", "monitoring", "band")
STATUSES = ("open", "investigating", "resolved")


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _incident_dict(row: sqlite3.Row) -> dict[str, Any]:
    incident = dict(row)
    if not incident["title"]:
        incident["title"] = incident["report"][:100]
    if not incident["not_worked"] and incident["didnt_work"]:
        incident["not_worked"] = incident["didnt_work"]
    return incident


def initialize() -> None:
    """Create the current schema and add missing columns to an older database."""
    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL DEFAULT '',
                report TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'General',
                severity TEXT NOT NULL DEFAULT 'P3'
                    CHECK (severity IN ('P1', 'P2', 'P3', 'P4')),
                source TEXT NOT NULL DEFAULT 'web'
                    CHECK (source IN ('web', 'support', 'tester', 'monitoring', 'band')),
                reported_by TEXT NOT NULL DEFAULT 'Unknown',
                report_count INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'investigating', 'resolved')),
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                root_cause TEXT,
                fix TEXT,
                not_worked TEXT,
                didnt_work TEXT,
                memory_sync TEXT NOT NULL DEFAULT 'none'
                    CHECK (memory_sync IN ('none', 'pending', 'synced', 'failed')),
                briefing_json TEXT,
                recalled_json TEXT,
                is_demo INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(incidents)")
        }
        additions = {
            "title": "TEXT NOT NULL DEFAULT ''",
            "type": "TEXT NOT NULL DEFAULT 'General'",
            "severity": "TEXT NOT NULL DEFAULT 'P3'",
            "source": "TEXT NOT NULL DEFAULT 'web'",
            "reported_by": "TEXT NOT NULL DEFAULT 'Unknown'",
            "report_count": "INTEGER NOT NULL DEFAULT 1",
            "status": "TEXT NOT NULL DEFAULT 'open'",
            "created_at": "TEXT",
            "resolved_at": "TEXT",
            "root_cause": "TEXT",
            "fix": "TEXT",
            "not_worked": "TEXT",
            "didnt_work": "TEXT",
            "memory_sync": "TEXT NOT NULL DEFAULT 'none'",
            "briefing_json": "TEXT",
            "recalled_json": "TEXT",
            "is_demo": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE incidents ADD COLUMN {name} {definition}")
        if "didnt_work" in columns:
            connection.execute(
                """
                UPDATE incidents
                SET not_worked = didnt_work
                WHERE not_worked IS NULL AND didnt_work IS NOT NULL
                """
            )
        connection.execute(
            """
            UPDATE incidents
            SET title = substr(report, 1, 100)
            WHERE title = '' AND report IS NOT NULL
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS incidents_created_idx ON incidents(created_at)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS incidents_status_idx ON incidents(status)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS diagnoses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id INTEGER NOT NULL,
                mode TEXT NOT NULL CHECK (mode IN ('with_memory', 'no_memory')),
                memories_used TEXT NOT NULL DEFAULT '[]',
                match_confidence INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                is_demo INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (incident_id) REFERENCES incidents(id)
            )
            """
        )
        diagnosis_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(diagnoses)")
        }
        if "is_demo" not in diagnosis_columns:
            connection.execute(
                "ALTER TABLE diagnoses ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0"
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS incident_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id INTEGER NOT NULL,
                event TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (incident_id) REFERENCES incidents(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id INTEGER NOT NULL,
                result TEXT NOT NULL CHECK (result IN ('worked', 'partly', 'didnt_work')),
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                user_id INTEGER,
                memory_sync TEXT NOT NULL DEFAULT 'pending'
                    CHECK (memory_sync IN ('pending', 'synced', 'failed')),
                FOREIGN KEY (incident_id) REFERENCES incidents(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS outcomes_incident_idx ON outcomes(incident_id, created_at)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                is_demo INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS bridge_heartbeat (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_seen TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('running', 'stopped'))
            )
            """
        )


def create_incident(
    *,
    title: str,
    report: str,
    incident_type: str,
    severity: str,
    source: str,
    reported_by: str,
    is_demo: bool = False,
) -> int:
    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO incidents
                (title, report, type, severity, source, reported_by, status, created_at, is_demo)
            VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?)
            """,
            (
                title,
                report,
                incident_type,
                severity,
                source,
                reported_by,
                _now(),
                int(is_demo),
            ),
        )
        return int(cursor.lastrowid)


def create_or_reuse_incident(
    *,
    title: str,
    report: str,
    incident_type: str,
    severity: str,
    source: str,
    reported_by: str,
) -> dict[str, Any]:
    normalized_report = re.sub(r"\s+", " ", report.casefold()).strip()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=60)
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            """
            SELECT id, report, created_at, report_count
            FROM incidents
            WHERE status = 'open'
            ORDER BY created_at DESC, id DESC
            """
        ).fetchall()
        for row in rows:
            try:
                created_at = datetime.fromisoformat(
                    str(row["created_at"]).replace("Z", "+00:00")
                )
            except (TypeError, ValueError):
                continue
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if created_at < cutoff:
                continue
            existing_report = re.sub(r"\s+", " ", row["report"].casefold()).strip()
            if SequenceMatcher(None, normalized_report, existing_report).ratio() < 0.9:
                continue
            connection.execute(
                "UPDATE incidents SET report_count = report_count + 1 WHERE id = ?",
                (row["id"],),
            )
            connection.execute(
                """
                INSERT INTO incident_events (incident_id, event, created_at)
                VALUES (?, ?, ?)
                """,
                (row["id"], f"reported again by {reported_by}", _now()),
            )
            return {
                "id": int(row["id"]),
                "duplicate": True,
                "report_count": int(row["report_count"]) + 1,
            }

        cursor = connection.execute(
            """
            INSERT INTO incidents
                (title, report, type, severity, source, reported_by, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'open', ?)
            """,
            (
                title,
                report,
                incident_type,
                severity,
                source,
                reported_by,
                _now(),
            ),
        )
        return {
            "id": int(cursor.lastrowid),
            "duplicate": False,
            "report_count": 1,
        }


def get_incident(incident_id: int) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM incidents WHERE id = ?", (incident_id,)
        ).fetchone()
    return _incident_dict(row) if row else None


def resolved_incidents(limit: int = 500) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM incidents
            WHERE status = 'resolved' AND resolved_at IS NOT NULL
            ORDER BY resolved_at, id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_incident_dict(row) for row in rows]


def match_memory_sources(memories: list[str]) -> list[dict[str, Any]]:
    """Map recalled text to stored incidents; unmatched seed texts use similarity."""
    incidents = resolved_incidents()
    matched: list[dict[str, Any]] = []
    seen: set[int] = set()
    for memory in memories:
        explicit = re.search(r"\bIncident\s+#(\d+)\b", memory, re.IGNORECASE)
        source = None
        method = "matched by similarity"
        if explicit:
            source = get_incident(int(explicit.group(1)))
            if source and source["status"] == "resolved":
                method = "incident id"
            else:
                source = None
        if source is None:
            best_ratio = 0.0
            for incident in incidents:
                candidate = " ".join(
                    str(value or "")
                    for value in (
                        incident["type"],
                        incident["title"],
                        incident["report"],
                        incident["root_cause"],
                        incident["fix"],
                        incident["not_worked"],
                    )
                )
                ratio = SequenceMatcher(
                    None,
                    re.sub(r"\s+", " ", memory.casefold()).strip(),
                    re.sub(r"\s+", " ", candidate.casefold()).strip(),
                ).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    source = incident
            if best_ratio < 0.35:
                source = None
        if source and source["id"] not in seen:
            seen.add(source["id"])
            matched.append(
                {
                    "memory": memory,
                    "incident_id": source["id"],
                    "title": source["title"],
                    "report": source["report"],
                    "root_cause": source["root_cause"] or "",
                    "fix": source["fix"] or "",
                    "not_worked": source["not_worked"] or "",
                    "resolved_at": source["resolved_at"] or source["created_at"],
                    "type": source["type"],
                    "method": method,
                    "similarity": round(best_ratio * 100) if method == "matched by similarity" else 100,
                }
            )
    return matched


def add_outcome(
    incident_id: int,
    result: str,
    note: str,
    user_id: int | None,
) -> int:
    if result not in {"worked", "partly", "didnt_work"}:
        raise ValueError("Invalid outcome result")
    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO outcomes (incident_id, result, note, created_at, user_id, memory_sync)
            VALUES (?, ?, ?, ?, ?, 'pending')
            """,
            (incident_id, result, note, _now(), user_id),
        )
        return int(cursor.lastrowid)


def update_outcome_memory_sync(outcome_id: int, state: str) -> None:
    if state not in {"pending", "synced", "failed"}:
        raise ValueError("Invalid outcome memory sync state")
    with _connect() as connection:
        connection.execute(
            "UPDATE outcomes SET memory_sync = ? WHERE id = ?",
            (state, outcome_id),
        )


def get_outcome(outcome_id: int) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT id, memory_sync FROM outcomes WHERE id = ?",
            (outcome_id,),
        ).fetchone()
    return dict(row) if row else None


def get_outcome_detail(outcome_id: int) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT id, incident_id, memory_sync FROM outcomes WHERE id = ?",
            (outcome_id,),
        ).fetchone()
    return dict(row) if row else None


def outcomes_for_incidents(incident_ids: list[int]) -> list[dict[str, Any]]:
    if not incident_ids:
        return []
    placeholders = ",".join("?" for _ in incident_ids)
    with _connect() as connection:
        rows = connection.execute(
            f"""
            SELECT o.*, i.title, i.type, u.name AS user_name
            FROM outcomes o
            JOIN incidents i ON i.id = o.incident_id
            LEFT JOIN users u ON u.id = o.user_id
            WHERE o.incident_id IN ({placeholders})
            ORDER BY o.created_at DESC, o.id DESC
            """,
            incident_ids,
        ).fetchall()
    return [dict(row) for row in rows]


def outcome_summary(incident_ids: list[int]) -> dict[str, Any]:
    records = outcomes_for_incidents(incident_ids)
    worked = sum(1 for item in records if item["result"] == "worked")
    failed = sum(1 for item in records if item["result"] == "didnt_work")
    total = len(records)
    return {
        "worked": worked,
        "total": total,
        "failed": failed,
        "needs_review": failed >= 2,
        "text": (
            f"Worked in {worked} of {total} similar cases"
            if total
            else "No outcome records for recalled cases yet."
        ),
    }


def recent_outcomes(limit: int = 50) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT o.*, i.title, i.type, u.name AS user_name
            FROM outcomes o
            JOIN incidents i ON i.id = o.incident_id
            LEFT JOIN users u ON u.id = o.user_id
            ORDER BY o.created_at DESC, o.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def memory_trail(limit: int = 100) -> list[dict[str, Any]]:
    return resolved_incidents(limit=limit)


def replay_cutoffs() -> list[dict[str, str]]:
    incidents = resolved_incidents()
    if not incidents:
        return []
    dates = [str(incident["resolved_at"]) for incident in incidents if incident["resolved_at"]]
    if not dates:
        return []
    middle = dates[(len(dates) - 1) // 2]
    return [
        {"label": "Start of recorded history", "cutoff": dates[0]},
        {"label": "Middle of recorded history", "cutoff": middle},
        {"label": "Now", "cutoff": _now()},
    ]


def list_incident_events(incident_id: int) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT event, created_at
            FROM incident_events
            WHERE incident_id = ?
            ORDER BY created_at, id
            """,
            (incident_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_open_incident(incident_id: int) -> bool:
    with _connect() as connection:
        row = connection.execute(
            "SELECT status FROM incidents WHERE id = ?", (incident_id,)
        ).fetchone()
        if row is None or row["status"] != "open":
            return False
        connection.execute("DELETE FROM diagnoses WHERE incident_id = ?", (incident_id,))
        connection.execute(
            "DELETE FROM incident_events WHERE incident_id = ?", (incident_id,)
        )
        connection.execute("DELETE FROM incidents WHERE id = ?", (incident_id,))
    return True


def create_user(name: str, email: str, password_hash: str) -> int:
    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO users (name, email, password_hash, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (name, email.strip().casefold(), password_hash, _now()),
        )
        return int(cursor.lastrowid)


def get_user(user_id: int) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT id, name, email, is_demo FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def get_user_by_email(email: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT id, name, email, password_hash, is_demo
            FROM users WHERE email = ? COLLATE NOCASE
            """,
            (email.strip(),),
        ).fetchone()
    return dict(row) if row else None


def ensure_demo_user(password_hash: str) -> dict[str, Any]:
    email = "demo@localhost"
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO users (name, email, password_hash, is_demo, created_at)
            VALUES ('Demo user', ?, ?, 1, ?)
            ON CONFLICT(email) DO NOTHING
            """,
            (email, password_hash, _now()),
        )
        row = connection.execute(
            """
            SELECT id, name, email, is_demo
            FROM users WHERE email = ? COLLATE NOCASE
            """,
            (email,),
        ).fetchone()
    if row is None:
        raise RuntimeError("The demo user could not be loaded.")
    return dict(row)


def list_incidents(
    *,
    status: str = "",
    incident_type: str = "",
    source: str = "",
    search: str = "",
) -> list[dict[str, Any]]:
    conditions: list[str] = []
    values: list[str] = []
    if status in STATUSES:
        conditions.append("status = ?")
        values.append(status)
    if incident_type:
        conditions.append("type = ?")
        values.append(incident_type)
    if source in SOURCES:
        conditions.append("source = ?")
        values.append(source)
    if search.strip():
        term = f"%{search.strip()}%"
        conditions.append("(title LIKE ? OR report LIKE ? OR reported_by LIKE ?)")
        values.extend((term, term, term))
    query = "SELECT * FROM incidents"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY id DESC"
    with _connect() as connection:
        rows = connection.execute(query, values).fetchall()
    return [_incident_dict(row) for row in rows]


def filter_options() -> dict[str, list[str]]:
    with _connect() as connection:
        types = connection.execute(
            "SELECT DISTINCT type FROM incidents WHERE type != '' ORDER BY type"
        ).fetchall()
    return {"types": [row["type"] for row in types]}


def dashboard_counts() -> dict[str, int]:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT
                SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open,
                SUM(CASE WHEN status = 'investigating' THEN 1 ELSE 0 END) AS investigating,
                SUM(CASE WHEN status = 'resolved' AND substr(resolved_at, 1, 7) = ?
                    THEN 1 ELSE 0 END) AS resolved_month_count,
                SUM(CASE WHEN memory_sync = 'synced' THEN 1 ELSE 0 END) AS memories_retained
            FROM incidents
            """,
            (month,),
        ).fetchone()
    return {key: int(row[key] or 0) for key in row.keys()}


def public_summary() -> dict[str, int]:
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT
                SUM(CASE WHEN is_demo = 0 THEN 1 ELSE 0 END) AS incidents_remembered,
                SUM(CASE WHEN is_demo = 0 AND memory_sync = 'synced' THEN 1 ELSE 0 END) AS fixes_retained,
                COUNT(DISTINCT CASE
                    WHEN is_demo = 0 AND memory_sync = 'synced' AND type != '' THEN type
                END) AS incident_types_covered
            FROM incidents
            """
        ).fetchone()
    return {key: int(row[key] or 0) for key in row.keys()}


def learning_data() -> dict[str, Any]:
    with _connect() as connection:
        counts = connection.execute(
            """
            SELECT
                SUM(CASE WHEN status = 'resolved' THEN 1 ELSE 0 END) AS resolved,
                SUM(CASE WHEN memory_sync = 'synced' THEN 1 ELSE 0 END) AS retained,
                (SELECT COUNT(*) FROM diagnoses WHERE mode = 'with_memory') AS total_triages,
                (SELECT COUNT(*) FROM diagnoses
                    WHERE mode = 'with_memory' AND memories_used != '[]') AS matched_triages
            FROM incidents
            """
        ).fetchone()
        diagnoses = connection.execute(
            """
            SELECT d.match_confidence, d.created_at, d.is_demo,
                i.id AS incident_id, i.title
            FROM diagnoses d
            JOIN incidents i ON i.id = d.incident_id
            WHERE d.mode = 'with_memory'
            ORDER BY d.created_at, d.id
            """
        ).fetchall()
        fixes = connection.execute(
            """
            SELECT id, title, type, fix, root_cause, resolved_at, is_demo
            FROM incidents
            WHERE memory_sync = 'synced' AND fix IS NOT NULL AND fix != ''
            ORDER BY resolved_at DESC, id DESC
            LIMIT 10
            """
        ).fetchall()
        demo_fixes = connection.execute(
            """
            SELECT id, title, type, fix, root_cause, resolved_at
            FROM incidents
            WHERE is_demo = 1 AND fix IS NOT NULL AND fix != ''
            ORDER BY resolved_at DESC, id DESC
            LIMIT 10
            """
        ).fetchall()
    total = int(counts["total_triages"] or 0)
    matched = int(counts["matched_triages"] or 0)
    points = [dict(row) for row in diagnoses]
    confidences = [int(point["match_confidence"]) for point in points]
    first_five = confidences[:5]
    latest_five = confidences[-5:]
    return {
        "resolved": int(counts["resolved"] or 0),
        "retained": int(counts["retained"] or 0),
        "match_share": round(matched * 100 / total) if total else 0,
        "total_triages": total,
        "matched_triages": matched,
        "points": points,
        "sample_triages": sum(1 for point in points if point["is_demo"]),
        "first_five_average": round(sum(first_five) / len(first_five)) if first_five else 0,
        "latest_five_average": round(sum(latest_five) / len(latest_five)) if latest_five else 0,
        "fixes": [dict(row) for row in fixes],
        "demo_fixes": [dict(row) for row in demo_fixes],
    }


def recurring_patterns(days: int) -> list[dict[str, Any]]:
    if days not in {30, 90}:
        raise ValueError("Pattern window must be 30 or 90 days")
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT type, COUNT(*) AS incident_count
            FROM incidents
            WHERE status = 'resolved'
                AND resolved_at IS NOT NULL
                AND julianday(resolved_at) >= julianday('now', ?)
            GROUP BY type
            ORDER BY incident_count DESC, type
            """,
            (f"-{days} days",),
        ).fetchall()
        patterns: list[dict[str, Any]] = []
        for row in rows:
            count = int(row["incident_count"])
            incidents = connection.execute(
                """
                SELECT id, title, resolved_at
                FROM incidents
                WHERE status = 'resolved' AND type = ?
                    AND resolved_at IS NOT NULL
                    AND julianday(resolved_at) >= julianday('now', ?)
                ORDER BY resolved_at DESC, id DESC
                """,
                (row["type"], f"-{days} days"),
            ).fetchall()
            patterns.append(
                {
                    "type": row["type"],
                    "count": count,
                    "days": days,
                    "incidents": [dict(incident) for incident in incidents],
                }
            )
    return patterns


def find_exact_report(report: str) -> int | None:
    normalized = " ".join(report.casefold().split())
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, report FROM incidents ORDER BY id DESC"
        ).fetchall()
    for row in rows:
        if " ".join(row["report"].casefold().split()) == normalized:
            return int(row["id"])
    return None


def recent_resolved_incidents(limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, title, report, type, severity, source, reported_by, status,
                created_at, resolved_at, root_cause, fix, not_worked, didnt_work,
                memory_sync, briefing_json
            FROM incidents
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_incident_dict(row) for row in rows]


def save_briefing(
    incident_id: int,
    briefing: dict[str, Any],
    memories: list[str],
    confidence: int,
    mode: str = "with_memory",
    *,
    is_demo: bool = False,
    created_at: str | None = None,
) -> None:
    if mode not in {"with_memory", "no_memory"}:
        raise ValueError("Invalid diagnosis mode")
    with _connect() as connection:
        connection.execute(
            "UPDATE incidents SET briefing_json = ? WHERE id = ?",
            (json.dumps(briefing), incident_id),
        )
        connection.execute(
            """
            INSERT INTO diagnoses
                (incident_id, mode, memories_used, match_confidence, created_at, is_demo)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                incident_id,
                mode,
                json.dumps(memories),
                confidence,
                created_at or _now(),
                int(is_demo),
            ),
        )


def save_recalled_memories(incident_id: int, memories: list[str]) -> list[str]:
    with _connect() as connection:
        connection.execute(
            """
            UPDATE incidents
            SET recalled_json = COALESCE(recalled_json, ?)
            WHERE id = ?
            """,
            (json.dumps(memories), incident_id),
        )
        row = connection.execute(
            "SELECT recalled_json FROM incidents WHERE id = ?", (incident_id,)
        ).fetchone()
    if row is None:
        raise ValueError("Incident not found while saving recalled memories.")
    value = json.loads(row["recalled_json"] or "[]")
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("Stored recalled memories are invalid.")
    return value


def save_diagnosis(
    incident_id: int,
    *,
    mode: str,
    memories: list[str],
    confidence: int,
) -> None:
    if mode not in {"with_memory", "no_memory"}:
        raise ValueError("Invalid diagnosis mode")
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO diagnoses
                (incident_id, mode, memories_used, match_confidence, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (incident_id, mode, json.dumps(memories), confidence, _now()),
        )


def get_latest_diagnosis(incident_id: int) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT * FROM diagnoses
            WHERE incident_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (incident_id,),
        ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["memories_used"] = json.loads(result["memories_used"])
    return result


def set_status(incident_id: int, status: str) -> bool:
    if status not in STATUSES:
        return False
    resolved_at = _now() if status == "resolved" else None
    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE incidents
            SET status = ?, resolved_at = CASE WHEN ? = 'resolved' THEN ? ELSE NULL END
            WHERE id = ?
            """,
            (status, status, resolved_at, incident_id),
        )
        return cursor.rowcount > 0


def update_memory_sync(incident_id: int, state: str) -> None:
    if state not in {"none", "pending", "synced", "failed"}:
        raise ValueError("Invalid memory sync state")
    with _connect() as connection:
        connection.execute(
            "UPDATE incidents SET memory_sync = ? WHERE id = ?",
            (state, incident_id),
        )


def update_bridge_heartbeat(state: str) -> None:
    if state not in {"running", "stopped"}:
        raise ValueError("Invalid Band bridge state")
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO bridge_heartbeat (id, last_seen, state)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET last_seen = excluded.last_seen,
                state = excluded.state
            """,
            (_now(), state),
        )


def bridge_heartbeat() -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT last_seen, state FROM bridge_heartbeat WHERE id = 1"
        ).fetchone()
    return dict(row) if row else None


def resolve_and_retain(
    incident_id: int,
    root_cause: str,
    fix: str,
    not_worked: str,
    retain: Callable[[str, str, str, str], None],
) -> bool:
    with _connect() as connection:
        row = connection.execute(
            "SELECT report, title, type FROM incidents WHERE id = ?", (incident_id,)
        ).fetchone()
        if row is None:
            return False
        report = str(row["report"])
        connection.execute(
            """
            UPDATE incidents
            SET status = 'resolved', resolved_at = ?, root_cause = ?, fix = ?,
                not_worked = ?, didnt_work = ?, memory_sync = 'pending',
                briefing_json = NULL, recalled_json = NULL
            WHERE id = ?
            """,
            (_now(), root_cause, fix, not_worked, not_worked, incident_id),
        )

    def retain_in_background() -> None:
        try:
            retain(report, root_cause, fix, not_worked)
        except Exception:
            update_memory_sync(incident_id, "failed")
        else:
            update_memory_sync(incident_id, "synced")

    threading.Thread(target=retain_in_background, daemon=True).start()
    return True


def retain_outcome_in_background(
    outcome_id: int,
    retain: Callable[[str], None],
) -> bool:
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT o.result, o.note, i.id AS incident_id, i.title, i.type, i.fix
            FROM outcomes o JOIN incidents i ON i.id = o.incident_id
            WHERE o.id = ?
            """,
            (outcome_id,),
        ).fetchone()
    if row is None:
        return False
    content = (
        f"Outcome for {row['type']} incident #{row['incident_id']} "
        f"'{row['title']}': suggested fix '{row['fix'] or 'not recorded'}' "
        f"{row['result']}."
    )
    if row["note"]:
        content += f" Note: {row['note']}"

    def retain_in_background() -> None:
        try:
            retain(content)
        except Exception:
            update_outcome_memory_sync(outcome_id, "failed")
        else:
            update_outcome_memory_sync(outcome_id, "synced")

    threading.Thread(target=retain_in_background, daemon=True).start()
    return True
