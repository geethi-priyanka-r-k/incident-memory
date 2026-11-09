"""Flask web interface for the Incident Memory Agent."""

from __future__ import annotations

import json
import hmac
import os
import re
import secrets
import sqlite3
import statistics
from datetime import datetime
from typing import Any

from settings import load_env, warn_missing

load_env()

from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import db

app = Flask(__name__)
app.jinja_env.autoescape = True
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,
    DEMO_MODE=os.environ.get("DEMO_MODE") == "1",
)
db.initialize()


@app.before_request
def require_login():
    if not app.config["SECRET_KEY"]:
        return (
            "Missing SECRET_KEY. Add a random SECRET_KEY to the project .env file and restart the app.",
            503,
        )
    if request.endpoint in {"login", "signup", "static", "home"}:
        user_id = session.get("user_id")
        if user_id:
            g.current_user = db.get_user(int(user_id))
        return None

    if request.path == "/api/report":
        expected = os.environ.get("REPORT_API_TOKEN")
        if not expected:
            return jsonify(
                error="REPORT_API_TOKEN is missing. Add it to the project .env file and restart the app."
            ), 503
        provided = request.headers.get("X-Report-Token", "")
        if not hmac.compare_digest(provided, expected):
            return jsonify(error="A valid X-Report-Token header is required."), 401
        return None

    user_id = session.get("user_id")
    user = db.get_user(int(user_id)) if user_id else None
    if user is None:
        session.clear()
        if request.path.startswith("/api/"):
            return jsonify(error="Please sign in to continue."), 401
        return redirect(url_for("login", next=request.full_path))

    g.current_user = user
    if user["is_demo"] and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if request.endpoint not in {"ask_agent", "logout"}:
            return jsonify(error="The demo workspace is read-only. You can still ask the agent."), 403
    return None


@app.context_processor
def inject_user():
    breadcrumbs = []
    path = request.path
    if path == "/overview":
        breadcrumbs = [{"label": "Home", "url": url_for("overview")}]
    elif path == "/incidents":
        breadcrumbs = [{"label": "Home", "url": url_for("overview")}, {"label": "All incidents", "url": url_for("dashboard")}]
    elif path == "/ask":
        breadcrumbs = [{"label": "Home", "url": url_for("overview")}, {"label": "Ask the agent", "url": url_for("ask_page")}]
    elif path == "/report":
        breadcrumbs = [{"label": "Home", "url": url_for("overview")}, {"label": "Report a problem", "url": url_for("report_page")}]
    elif path == "/compare":
        breadcrumbs = [{"label": "Home", "url": url_for("overview")}, {"label": "With vs without memory", "url": url_for("compare_page")}]
    elif path == "/memory":
        breadcrumbs = [{"label": "Home", "url": url_for("overview")}, {"label": "Learning progress", "url": url_for("memory_page")}]
    elif path == "/patterns":
        breadcrumbs = [{"label": "Home", "url": url_for("overview")}, {"label": "Recurring problems", "url": url_for("patterns_page")}]
    elif path == "/handoff":
        breadcrumbs = [{"label": "Home", "url": url_for("overview")}, {"label": "Shift handoff", "url": url_for("handoff_page")}]
    elif path == "/outcomes":
        breadcrumbs = [{"label": "Home", "url": url_for("overview")}, {"label": "Outcome learning", "url": url_for("outcomes_page")}]
    elif path == "/trail":
        breadcrumbs = [{"label": "Home", "url": url_for("overview")}, {"label": "Memory trail", "url": url_for("memory_trail_page")}]
    elif path == "/replay":
        breadcrumbs = [{"label": "Home", "url": url_for("overview")}, {"label": "Memory over time", "url": url_for("replay_page")}]
    elif path == "/risk":
        breadcrumbs = [{"label": "Home", "url": url_for("overview")}, {"label": "Before you deploy", "url": url_for("risk_page")}]
    elif path == "/connect":
        breadcrumbs = [{"label": "Home", "url": url_for("overview")}, {"label": "Band chat", "url": url_for("connect_page")}]
    elif path.startswith("/incident/"):
        breadcrumbs = [
            {"label": "Home", "url": url_for("overview")},
            {"label": "All incidents", "url": url_for("dashboard")},
            {"label": "Incident", "url": path},
        ]
    return {
        "current_user": getattr(g, "current_user", None),
        "demo_mode": app.config["DEMO_MODE"],
        "breadcrumbs": breadcrumbs,
    }


@app.errorhandler(404)
def page_not_found(_error):
    return render_template(
        "error.html",
        active_page="",
        title="Page not found",
        description="That page isn't here. Return to your workspace to continue.",
    ), 404


@app.errorhandler(500)
def internal_server_error(_error):
    app.logger.error("An unhandled server error occurred.")
    return render_template(
        "error.html",
        active_page="",
        title="Something went wrong",
        description="The page could not be loaded. Return home and try again.",
    ), 500


@app.get("/login")
@app.post("/login")
def login():
    if session.get("user_id"):
        user = db.get_user(int(session["user_id"]))
        if user:
            return redirect(url_for("overview"))
        session.clear()

    if request.method == "POST":
        if request.form.get("demo") == "1":
            if not app.config["DEMO_MODE"]:
                error = "Demo access is not enabled."
            else:
                demo = db.ensure_demo_user(
                    generate_password_hash(secrets.token_urlsafe(32))
                )
                session.clear()
                session["user_id"] = demo["id"]
                return redirect(url_for("overview"))
        else:
            email = request.form.get("email", "").strip()
            password = request.form.get("password", "")
            user = db.get_user_by_email(email) if email else None
            if user and check_password_hash(user["password_hash"], password):
                session.clear()
                session["user_id"] = user["id"]
                return redirect(url_for("overview"))
            error = "The email or password was not recognised."

        return render_template("auth.html", mode="login", error=error)
    return render_template("auth.html", mode="login", error="")


@app.get("/signup")
@app.post("/signup")
def signup():
    if session.get("user_id"):
        user = db.get_user(int(session["user_id"]))
        if user:
            return redirect(url_for("overview"))
        session.clear()

    error = ""
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        if not name or not email or not password or not confirm_password:
            error = "Complete each field to create your account."
        elif len(name) > 120 or len(email) > 254:
            error = "Please use a shorter name or email address."
        elif not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            error = "Enter a valid email address."
        elif len(password) < 8:
            error = "Your password must be at least 8 characters."
        elif password != confirm_password:
            error = "The passwords do not match."
        elif db.get_user_by_email(email):
            error = "An account with that email already exists. Sign in instead."
        else:
            try:
                user_id = db.create_user(
                    name,
                    email,
                    generate_password_hash(password),
                )
            except sqlite3.IntegrityError:
                error = "An account with that email already exists. Sign in instead."
            else:
                session.clear()
                session["user_id"] = user_id
                return redirect(url_for("overview"))

    return render_template(
        "auth.html",
        mode="signup",
        error=error,
        name=name,
        email=email,
    )


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

SOURCE_LABELS = {
    "web": "Web",
    "support": "Support",
    "tester": "Tester",
    "monitoring": "Monitoring",
    "band": "Band",
}
SECTION_NAMES = {
    "likely match": "likely_match",
    "match confidence": "match_confidence",
    "root cause": "root_cause",
    "fix steps": "fix_steps",
    "skip these": "skip_these",
}
SECTION_PATTERN = re.compile(
    r"^\s*\*{0,2}(Likely match|Match confidence|Root cause|Fix steps|Skip these)\*{0,2}\s*:?\s*\*{0,2}\s*(.*)$",
    re.IGNORECASE,
)
MAX_TEXT_LENGTH = 10000
CONFIDENCE_PATTERN = re.compile(r"\b(\d{1,3})\s*%?")


class AskTriageFailure(Exception):
    def __init__(self, saved: dict[str, Any]) -> None:
        super().__init__("The incident was saved, but triage failed.")
        self.saved = saved


class AskRecallFailure(Exception):
    def __init__(self, saved: dict[str, Any]) -> None:
        super().__init__("The incident was saved, but recall failed.")
        self.saved = saved


def _json_body() -> dict[str, Any]:
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else {}


def _plain_text(value: Any) -> str:
    text = str(value or "").replace("**", "")
    text = re.sub(r"[•●▪◦‣]", "", text)
    text = re.sub(r"(?m)^\s*(?:[-*]\s+|\d+[.)]\s+)", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _sentence_limit(value: Any, limit: int) -> str:
    text = _plain_text(value)
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(sentences[:limit]).strip()


def _fix_step_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    steps = []
    for value in values:
        text = _plain_text(value)
        if not text or text.endswith(":"):
            continue
        if re.fullmatch(r"[^.!?]{1,80}:", text):
            continue
        text = _sentence_limit(text, 1)
        if text:
            steps.append(text)
        if len(steps) == 6:
            break
    return steps


def _not_worked_note(memory: str) -> str:
    match = re.search(
        r"(?:what did\s+not work|what failed|did not work|didn't work)\s*[:\-]\s*(.+)",
        memory,
        re.IGNORECASE,
    )
    if not match:
        return ""
    note = _plain_text(match.group(1))
    return re.sub(r"^(?:not recorded|none|n/?a)\.?$", "", note, flags=re.IGNORECASE).strip()


def _split_answer(answer: str) -> dict[str, Any]:
    try:
        parsed = json.loads(answer)
    except json.JSONDecodeError:
        parsed = None
        start, end = answer.find("{"), answer.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(answer[start : end + 1])
            except json.JSONDecodeError:
                pass
    if isinstance(parsed, dict):
        return {
            "likely_match": _plain_text(parsed.get("likely_match")),
            "match_confidence": parsed.get("match_confidence"),
            "root_cause": _sentence_limit(parsed.get("root_cause"), 2),
            "fix_steps": _fix_step_list(parsed.get("fix_steps")),
            "cited_memory_ids": parsed.get("cited_memory_ids", []),
        }

    sections: dict[str, list[str]] = {name: [] for name in SECTION_NAMES.values()}
    current: str | None = None
    for line in answer.splitlines():
        match = SECTION_PATTERN.match(line)
        if match:
            current = SECTION_NAMES[match.group(1).casefold()]
            if match.group(2).strip():
                sections[current].append(match.group(2).strip())
        elif current and line.strip():
            sections[current].append(line.strip())

    confidence_match = CONFIDENCE_PATTERN.search(
        "\n".join(sections["match_confidence"])
    )
    return {
        "likely_match": _plain_text("\n".join(sections["likely_match"])),
        "match_confidence": int(confidence_match.group(1)) if confidence_match else None,
        "root_cause": _sentence_limit("\n".join(sections["root_cause"]), 2),
        "fix_steps": _fix_step_list(sections["fix_steps"]),
        "cited_memory_ids": [],
    }


def _clean_briefing(briefing: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(briefing)
    had_citation_data = isinstance(cleaned.get("cited_memory_ids"), list)
    if had_citation_data:
        memories = cleaned.get("memories", [])
        others = cleaned.get("other_memories", [])
    else:
        memories = []
        others = cleaned.get("memories", [])
        cleaned["cited_memory_ids"] = []
        cleaned["memory_sources"] = []

    memories = memories if isinstance(memories, list) else []
    others = others if isinstance(others, list) else []
    cleaned["memories"] = [
        _plain_text(memory) for memory in memories if _plain_text(memory)
    ]
    cleaned["other_memories"] = [
        _plain_text(memory) for memory in others if _plain_text(memory)
    ]
    cleaned["root_cause"] = _sentence_limit(cleaned.get("root_cause"), 2)
    cleaned["fix_steps"] = _fix_step_list(cleaned.get("fix_steps"))
    skip_these = cleaned.get("skip_these", [])
    if not isinstance(skip_these, list):
        skip_these = []
    cleaned["skip_these"] = [
        _plain_text(item)
        for item in skip_these
        if _plain_text(item)
    ][:3]
    confidence = cleaned.get("match_confidence", 0)
    try:
        confidence = max(0, min(100, int(confidence or 0)))
    except (TypeError, ValueError):
        confidence = 0
    if not cleaned["memories"]:
        confidence = 0
    cleaned["match_confidence"] = confidence
    if confidence >= 50:
        cleaned["likely_match"] = (
            f"Seen before: {len(cleaned['memories'])} similar past incidents"
        )
        cleaned["match_note"] = ""
    else:
        cleaned["likely_match"] = "No close match in memory yet"
        cleaned["match_note"] = (
            "The agent will recognise this once a fix is saved."
        )
        cleaned["skip_these"] = []
    return cleaned


def _run_triage(
    incident: dict[str, Any],
    *,
    use_memory: bool = True,
) -> dict[str, Any]:
    import agent

    memories = _recall_memories(incident) if use_memory else []
    diagnosis = agent.diagnose_with_memories(
        f"{incident['title']}\n{incident['report']}",
        memories,
    )
    briefing = _format_diagnosis(diagnosis, use_memory=use_memory)
    if use_memory:
        briefing = _add_memory_trail(briefing)
    if use_memory:
        db.save_briefing(
            incident["id"],
            briefing,
            briefing["memories"],
            briefing["match_confidence"],
        )
    else:
        db.save_diagnosis(
            incident["id"],
            mode="no_memory",
            memories=briefing["memories"],
            confidence=briefing["match_confidence"],
        )
    return briefing


def _add_memory_trail(briefing: dict[str, Any]) -> dict[str, Any]:
    sources = db.match_memory_sources(briefing.get("memories", []))
    ids = [source["incident_id"] for source in sources]
    outcome = db.outcome_summary(ids)
    briefing["memory_sources"] = sources
    briefing["outcome_summary"] = outcome
    briefing["claim_sources"] = {
        claim: list(range(1, len(sources) + 1))
        for claim in ("likely_match", "root_cause", "fix_steps", "skip_these")
        if sources
    }
    return briefing


def _format_diagnosis(
    diagnosis: dict[str, Any],
    *,
    use_memory: bool,
) -> dict[str, Any]:
    answer = str(diagnosis.get("answer") or "")
    memories = [
        _plain_text(memory)
        for memory in diagnosis.get("memories", [])
        if _plain_text(memory)
    ]
    briefing = _split_answer(answer)
    cited_ids = briefing["cited_memory_ids"]
    if not isinstance(cited_ids, list):
        cited_ids = []
    cited_ids = list(dict.fromkeys(
        item
        for item in cited_ids
        if isinstance(item, int) and not isinstance(item, bool)
        and 1 <= item <= len(memories)
    ))
    cited_memories = [memory for index, memory in enumerate(memories, 1) if index in cited_ids]
    other_memories = [memory for index, memory in enumerate(memories, 1) if index not in cited_ids]
    raw_confidence = briefing["match_confidence"]
    try:
        confidence = max(0, min(100, int(raw_confidence)))
    except (TypeError, ValueError):
        confidence = 55 if cited_memories else 0
    if not use_memory:
        confidence = 0
    elif not cited_memories:
        confidence = 0
    failed_notes = [
        note
        for memory in cited_memories
        if (note := _not_worked_note(memory))
    ]
    briefing.update({
        "answer": _plain_text(answer),
        "match_confidence": confidence,
        "memories": cited_memories,
        "other_memories": other_memories,
        "cited_memory_ids": cited_ids,
        "skip_these": failed_notes[:3],
    })
    if not briefing["root_cause"]:
        briefing["root_cause"] = "No root cause could be identified yet."
    return _clean_briefing(briefing)


def _recall_memories(incident: dict[str, Any]) -> list[str]:
    stored = incident.get("recalled_json")
    if stored:
        memories = json.loads(stored)
        if not isinstance(memories, list) or not all(
            isinstance(memory, str) for memory in memories
        ):
            raise ValueError("Stored recalled memories are invalid.")
        return memories
    import agent

    recalled = agent.recall_similar(
        f"{incident['title']}\n{incident['report']}"
    )
    return db.save_recalled_memories(int(incident["id"]), recalled)


def _ordinal(value: int) -> str:
    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def _pattern_view(days: int) -> list[dict[str, Any]]:
    patterns = db.recurring_patterns(days)
    for pattern in patterns:
        pattern["notice"] = (
            f"{_ordinal(pattern['count'])} {pattern['type'].lower()} incident in "
            f"{days} days. Consider a permanent fix."
            if pattern["count"] >= 3
            else f"{pattern['count']} resolved {pattern['type'].lower()} incidents in {days} days."
        )
    return patterns


def _ask_report(
    report: str,
    *,
    reported_by: str = "Web user",
) -> dict[str, Any]:
    saved = db.create_or_reuse_incident(
        title=report[:160],
        report=report,
        incident_type="General",
        severity="P3",
        source="web",
        reported_by=reported_by,
    )
    incident = db.get_incident(saved["id"])
    if incident is None:
        raise RuntimeError("The saved incident could not be loaded.")
    try:
        if incident["briefing_json"]:
            briefing = _clean_briefing(json.loads(incident["briefing_json"]))
            if briefing.get("memories") and not incident["is_demo"]:
                briefing = _add_memory_trail(briefing)
        else:
            briefing = _run_triage(incident)
    except Exception as error:
        raise AskTriageFailure(saved) from error
    return {
        "id": saved["id"],
        "url": url_for("incident_page", incident_id=saved["id"]),
        "duplicate": saved["duplicate"],
        "report_count": saved["report_count"],
        "seen_before": len(briefing["memories"]),
        "report": report,
        "briefing": briefing,
    }


def _ask_recall(
    report: str,
    *,
    reported_by: str = "Web user",
) -> dict[str, Any]:
    saved = db.create_or_reuse_incident(
        title=report[:160],
        report=report,
        incident_type="General",
        severity="P3",
        source="web",
        reported_by=reported_by,
    )
    incident = db.get_incident(saved["id"])
    if incident is None:
        raise RuntimeError("The saved incident could not be loaded.")
    base = {
        "id": saved["id"],
        "url": url_for("incident_page", incident_id=saved["id"]),
        "duplicate": saved["duplicate"],
        "report_count": saved["report_count"],
        "report": report,
    }
    if incident["briefing_json"]:
        briefing = _clean_briefing(json.loads(incident["briefing_json"]))
        return {
            **base,
            "complete": True,
            "seen_before": len(briefing["memories"]),
            "briefing": briefing,
        }
    try:
        memories = _recall_memories(incident)
    except Exception as error:
        raise AskRecallFailure(saved) from error
    return {
        **base,
        "complete": False,
        "memories": memories,
        "memory_sources": db.match_memory_sources(memories),
    }


@app.get("/")
def home():
    if session.get("user_id"):
        user = db.get_user(int(session["user_id"]))
        if user:
            return redirect(url_for("overview"))
        session.clear()
    return render_template("landing.html", summary=db.public_summary())


@app.get("/overview")
def overview():
    incidents = db.list_incidents()
    counts = db.dashboard_counts()
    learning = db.learning_data()
    resolved_minutes = []
    coverage_counts: dict[str, int] = {}
    knowledge_gaps = []
    sparkline_days = []
    today = datetime.now().astimezone().date()
    for offset in range(6, -1, -1):
        sparkline_days.append(today.fromordinal(today.toordinal() - offset))

    sparkline_values = {
        "open": [0] * 7,
        "resolved": [0] * 7,
        "retained": [0] * 7,
    }
    for incident in incidents:
        incident_type = incident["type"] or "General"
        coverage_counts[incident_type] = coverage_counts.get(incident_type, 0) + 1
        try:
            created_at = datetime.fromisoformat(
                str(incident["created_at"]).replace("Z", "+00:00")
            )
            created_day = created_at.astimezone().date()
            if incident["status"] == "open" and created_day in sparkline_days:
                sparkline_values["open"][sparkline_days.index(created_day)] += 1
            if incident["resolved_at"]:
                resolved_at = datetime.fromisoformat(
                    str(incident["resolved_at"]).replace("Z", "+00:00")
                )
                resolved_day = resolved_at.astimezone().date()
                if resolved_day in sparkline_days:
                    sparkline_values["resolved"][sparkline_days.index(resolved_day)] += 1
                if created_at.tzinfo is None and resolved_at.tzinfo is not None:
                    created_at = created_at.replace(tzinfo=resolved_at.tzinfo)
                if resolved_at.tzinfo is None and created_at.tzinfo is not None:
                    resolved_at = resolved_at.replace(tzinfo=created_at.tzinfo)
                resolved_minutes.append(
                    max(0, (resolved_at - created_at).total_seconds() / 60)
                )
                if incident["memory_sync"] == "synced" and resolved_day in sparkline_days:
                    sparkline_values["retained"][sparkline_days.index(resolved_day)] += 1
        except (TypeError, ValueError):
            pass

        if incident["briefing_json"]:
            try:
                briefing = json.loads(incident["briefing_json"])
            except (TypeError, ValueError):
                briefing = {}
            if not briefing.get("memories") and incident["status"] != "resolved":
                knowledge_gaps.append(incident)

    max_coverage = max(coverage_counts.values(), default=0)
    coverage = [
        {"type": incident_type, "count": count,
         "percent": round(count * 100 / max_coverage) if max_coverage else 0}
        for incident_type, count in sorted(
            coverage_counts.items(), key=lambda item: (-item[1], item[0])
        )[:5]
    ]
    chart_width = max(800, 44 * len(learning["points"]) + 40)
    chart_points = []
    for index, point in enumerate(learning["points"]):
        confidence = max(0, min(100, int(point["match_confidence"])))
        chart_points.append({
            **point,
            "confidence": confidence,
            "x": 20 + index * 44,
            "y": 180 - max(2, round(confidence * 1.4)),
        })
    sparkline_paths = {}
    for name, values in sparkline_values.items():
        high = max(values, default=0) or 1
        sparkline_paths[name] = " ".join(
            f"{12 + index * 13},{28 - round(value / high * 20)}"
            for index, value in enumerate(values)
        )

    recent_outcomes = db.outcomes_for_incidents(
        [row["id"] for row in db.list_incidents(status="resolved")][:25]
    )
    success_fixes = sum(1 for item in recent_outcomes if item["result"] == "worked")
    needs_review_fixes = sum(
        1 for item in recent_outcomes if item["result"] == "didnt_work"
    )
    memory_health = {
        "success_fixes": success_fixes,
        "needs_review_fixes": needs_review_fixes,
    }

    return render_template(
        "overview.html",
        active_page="overview",
        counts=counts,
        incidents=incidents[:10],
        learning=learning,
        chart_points=chart_points,
        chart_width=chart_width,
        knowledge_gaps=knowledge_gaps[:5],
        coverage=coverage,
        median_minutes=round(statistics.median(resolved_minutes))
        if resolved_minutes else None,
        sparkline_paths=sparkline_paths,
        memory_health=memory_health,
        first_name=(g.current_user["name"].split() or ["there"])[0],
        sources=SOURCE_LABELS,
    )


@app.get("/incidents")
def dashboard():
    filters = {
        "status": request.args.get("status", ""),
        "type": request.args.get("type", ""),
        "source": request.args.get("source", ""),
        "search": request.args.get("search", ""),
    }
    incidents = db.list_incidents(
        status=filters["status"],
        incident_type=filters["type"],
        source=filters["source"],
        search=filters["search"],
    )
    for incident in incidents:
        incident["source_label"] = SOURCE_LABELS.get(
            incident["source"], incident["source"].title()
        )
    return render_template(
        "dashboard.html",
        active_page="overview" if request.path == "/overview" else "incidents",
        counts=db.dashboard_counts(),
        incidents=incidents,
        filters=filters,
        options=db.filter_options(),
        sources=SOURCE_LABELS,
    )


@app.get("/ask")
def ask_page():
    return render_template(
        "ask.html",
        active_page="ask",
        counts=db.dashboard_counts(),
    )


@app.get("/report")
def report_page():
    return render_template("report.html", active_page="report")


@app.get("/compare")
def compare_page():
    selected_id = request.args.get("incident_id", type=int)
    selected_incident = db.get_incident(selected_id) if selected_id else None
    incidents = db.recent_resolved_incidents()
    return render_template(
        "compare.html",
        active_page="compare",
        incidents=incidents,
        selected_incident=selected_incident,
    )


@app.get("/memory")
def memory_page():
    learning = db.learning_data()
    chart_width = max(760, 60 * max(1, len(learning["points"])) + 60)
    chart_points = []
    for index, point in enumerate(learning["points"]):
        confidence = max(0, min(100, int(point["match_confidence"])))
        chart_points.append(
            {
                **point,
                "confidence": confidence,
                "x": 30 + index * 60,
                "y": 210 - round(confidence * 1.7),
            }
        )
    return render_template(
        "memory.html",
        active_page="memory",
        learning=learning,
        chart_points=chart_points,
        chart_width=chart_width,
    )


@app.get("/patterns")
def patterns_page():
    patterns_30 = _pattern_view(30)
    patterns_90 = _pattern_view(90)
    for patterns in (patterns_30, patterns_90):
        maximum = max((pattern["count"] for pattern in patterns), default=0)
        for pattern in patterns:
            pattern["bar_percent"] = (
                round(pattern["count"] * 100 / maximum) if maximum else 0
            )
    return render_template(
        "patterns.html",
        active_page="patterns",
        patterns_30=patterns_30,
        patterns_90=patterns_90,
    )


@app.get("/handoff")
def handoff_page():
    open_incidents = db.list_incidents(status="open")
    investigating = db.list_incidents(status="investigating")
    incidents = sorted(
        open_incidents + investigating,
        key=lambda incident: (
            {"P1": 0, "P2": 1, "P3": 2, "P4": 3}.get(incident["severity"], 4),
            incident["created_at"],
        ),
    )
    for incident in incidents:
        try:
            briefing = json.loads(incident["briefing_json"] or "{}")
        except (TypeError, ValueError):
            briefing = {}
        briefing = _clean_briefing(briefing)
        incident["recommendation"] = briefing.get("fix_steps") or []
        incident["memories"] = briefing.get("memories") or []
        incident["events"] = db.list_incident_events(incident["id"])
        incident["tried"] = incident["not_worked"] or ""
    return render_template(
        "handoff.html",
        active_page="handoff",
        incidents=incidents,
    )


@app.get("/outcomes")
def outcomes_page():
    return render_template(
        "outcomes.html",
        active_page="outcomes",
        outcomes=db.recent_outcomes(),
    )


@app.get("/trail")
def memory_trail_page():
    incidents = db.memory_trail()
    return render_template(
        "trail.html",
        active_page="trail",
        incidents=incidents,
    )


@app.get("/replay")
@app.post("/replay")
def replay_page():
    incidents = db.recent_resolved_incidents()
    selected_id = request.values.get("incident_id", type=int)
    selected = db.get_incident(selected_id) if selected_id else None
    results = []
    summary = ""
    error = ""
    cutoffs = db.replay_cutoffs()
    if request.method == "POST":
        if selected is None or selected["status"] != "resolved":
            error = "Choose a resolved incident to replay."
        else:
            try:
                import agent

                recalled = agent.recall_similar(
                    f"{selected['title']}\n{selected['report']}"
                )
                sources = db.match_memory_sources(recalled)
                for checkpoint in cutoffs:
                    allowed_ids = {
                        source["incident_id"]
                        for source in sources
                        if str(source["resolved_at"]) <= checkpoint["cutoff"]
                    }
                    checkpoint_memories = [
                        source["memory"]
                        for source in sources
                        if source["incident_id"] in allowed_ids
                    ]
                    diagnosis = agent.diagnose_with_memories(
                        f"{selected['title']}\n{selected['report']}",
                        checkpoint_memories,
                    )
                    briefing = _format_diagnosis(diagnosis, use_memory=True)
                    briefing["memory_sources"] = db.match_memory_sources(
                        briefing["memories"]
                    )
                    briefing["outcome_summary"] = db.outcome_summary(
                        [source["incident_id"] for source in briefing["memory_sources"]]
                    )
                    briefing["checkpoint"] = checkpoint["label"]
                    briefing["cutoff"] = checkpoint["cutoff"][:10]
                    results.append(briefing)
                if results:
                    start_fixes = results[0]["fix_steps"]
                    now_fixes = results[-1]["fix_steps"]
                    summary = (
                        "The additional memory available later changed the suggested steps."
                        if start_fixes != now_fixes
                        else "The suggested steps stayed the same across these recorded memory checkpoints."
                    )
            except Exception as error_value:
                app.logger.error("Memory replay failed (%s)", type(error_value).__name__)
                error = "Replay could not complete. Check that memory and reasoning services are available, then try again."
    return render_template(
        "replay.html",
        active_page="replay",
        incidents=incidents,
        selected=selected,
        results=results,
        summary=summary,
        error=error,
    )


@app.get("/risk")
@app.post("/risk")
def risk_page():
    change = str(request.form.get("change", "")).strip()
    result = None
    sources: list[dict[str, Any]] = []
    error = ""
    if request.method == "POST":
        if not change:
            error = "Describe the change before checking its history."
        elif len(change) > MAX_TEXT_LENGTH:
            error = "Keep the change description to 10,000 characters or fewer."
        else:
            try:
                import agent

                memories = agent.recall_similar(change)
                sources = db.match_memory_sources(memories)
                result = agent.assess_change_risk(change, memories)
                if not sources:
                    result = {
                        "risk_level": "Unknown",
                        "reasons": [],
                        "what_failed_before": [],
                        "rollback_note": "No history for this kind of change, risk unknown.",
                    }
                linked_reasons = []
                for item in result["reasons"]:
                    item["sources"] = [
                        source
                        for memory_id in item["memory_ids"]
                        for source in sources
                        if source["memory"] == memories[memory_id - 1]
                    ]
                    if item["sources"]:
                        linked_reasons.append(item)
                result["reasons"] = linked_reasons
                linked_failures = []
                for item in result["what_failed_before"]:
                    item["sources"] = [
                        source
                        for memory_id in item["memory_ids"]
                        for source in sources
                        if source["memory"] == memories[memory_id - 1]
                    ]
                    if item["sources"]:
                        linked_failures.append(item)
                result["what_failed_before"] = linked_failures
                if result["risk_level"] != "Unknown" and not result["reasons"]:
                    result["risk_level"] = "Unknown"
                if not result["reasons"]:
                    result["rollback_note"] = (
                        "No rollback detail is supported by the linked incident history."
                    )
            except Exception as error_value:
                app.logger.error("Change risk check failed (%s)", type(error_value).__name__)
                error = "The change history could not be checked. Try again when memory and reasoning services are available."
    return render_template(
        "risk.html",
        active_page="risk",
        change=change,
        result=result,
        sources=sources,
        error=error,
    )


@app.get("/connect")
def connect_page():
    env_names = (
        "BAND_API_KEY",
        "BAND_AGENT_ID",
        "HINDSIGHT_URL",
        "HINDSIGHT_API_KEY",
        "GROQ_API_KEY",
    )
    configured = {name: bool(os.environ.get(name)) for name in env_names}
    heartbeat = db.bridge_heartbeat()
    bridge_online = False
    if heartbeat and heartbeat["state"] == "running":
        try:
            last_seen = datetime.fromisoformat(
                str(heartbeat["last_seen"]).replace("Z", "+00:00")
            )
            if last_seen.tzinfo is None:
                from datetime import timezone

                last_seen = last_seen.replace(tzinfo=timezone.utc)
            bridge_online = (
                datetime.now(last_seen.tzinfo) - last_seen
            ).total_seconds() <= 45
        except (TypeError, ValueError):
            bridge_online = False
    return render_template(
        "connect.html",
        active_page="connect",
        configured=configured,
        bridge_configured=all(configured.values()),
        bridge_online=bridge_online,
        bridge_heartbeat=heartbeat,
    )


@app.get("/incident/<int:incident_id>")
def incident_page(incident_id: int):
    incident = db.get_incident(incident_id)
    if incident is None:
        return render_template("error.html", active_page="", title="Incident not found"), 404
    briefing = None
    if incident["briefing_json"]:
        briefing = _clean_briefing(json.loads(incident["briefing_json"]))
        if briefing.get("memories") and not incident["is_demo"]:
            briefing = _add_memory_trail(briefing)
    return render_template(
        "incident.html",
        active_page="incidents",
        incident=incident,
        briefing=briefing,
        events=db.list_incident_events(incident_id),
        outcome_summary=(briefing or {}).get("outcome_summary", {
            "text": "No outcome records for recalled cases yet.",
            "needs_review": False,
        }),
    )


@app.get("/api/memory/source/<int:incident_id>")
def memory_source(incident_id: int):
    incident = db.get_incident(incident_id)
    if incident is None or incident["status"] != "resolved":
        return jsonify(error="The source incident is not available."), 404
    return jsonify(
        id=incident["id"],
        title=incident["title"],
        type=incident["type"],
        report=incident["report"],
        root_cause=incident["root_cause"] or "",
        fix=incident["fix"] or "",
        not_worked=incident["not_worked"] or "",
        resolved_at=incident["resolved_at"] or incident["created_at"],
    )


@app.post("/api/incidents/<int:incident_id>/outcome")
def record_incident_outcome(incident_id: int):
    incident = db.get_incident(incident_id)
    if incident is None:
        return jsonify(error="Incident not found."), 404
    if incident["is_demo"]:
        return jsonify(error="Outcome feedback cannot be recorded on illustrative demo incidents."), 409
    if not incident["briefing_json"]:
        return jsonify(error="Run the incident briefing before recording its outcome."), 409
    body = _json_body()
    result = str(body.get("result", ""))
    note = str(body.get("note", "")).strip()
    if result not in {"worked", "partly", "didnt_work"}:
        return jsonify(error="Choose Worked, Partly, or Didn't work."), 400
    if len(note) > 2000:
        return jsonify(error="Keep the outcome note to 2,000 characters or fewer."), 400
    try:
        outcome_id = db.add_outcome(
            incident_id,
            result,
            note,
            g.current_user["id"],
        )
        import agent

        if not db.retain_outcome_in_background(outcome_id, agent.save_outcome):
            return jsonify(error="The outcome was saved, but its memory task could not start."), 500
    except Exception as error_value:
        app.logger.error("Outcome save failed (%s)", type(error_value).__name__)
        return jsonify(error="The outcome could not be saved. Please try again."), 500
    return jsonify(ok=True, outcome_id=outcome_id, memory_sync="pending")


@app.get("/api/outcomes/<int:outcome_id>/memory-sync")
def outcome_memory_sync(outcome_id: int):
    outcome = db.get_outcome_detail(outcome_id)
    if outcome is None:
        return jsonify(error="Outcome not found."), 404
    incident = db.get_incident(outcome["incident_id"])
    briefing = json.loads(incident["briefing_json"] or "{}") if incident else {}
    source_ids = [
        source["incident_id"]
        for source in briefing.get("memory_sources", [])
        if source.get("incident_id")
    ]
    source_ids.append(outcome["incident_id"])
    return jsonify(
        memory_sync=outcome["memory_sync"],
        outcome_summary=db.outcome_summary(list(set(source_ids))),
    )


@app.post("/api/report")
def create_report():
    return _create_report_response()


@app.post("/api/incidents")
def create_web_report():
    return _create_report_response()


def _create_report_response():
    body = _json_body()
    title = str(body.get("title", "")).strip()
    report_text = str(body.get("report", "")).strip()
    where_seen = str(body.get("where_seen", "")).strip()
    source = str(body.get("source", "web")).strip()
    reported_by = str(body.get("reported_by", "")).strip()
    incident_type = str(body.get("type", "General")).strip() or "General"
    severity = str(body.get("severity", "P3")).strip().upper()

    if not title or not report_text or not reported_by:
        return jsonify(error="Title, incident details, and your name are required."), 400
    if len(title) > 160 or len(report_text) > MAX_TEXT_LENGTH or len(where_seen) > 500:
        return jsonify(error="Keep the title under 160 characters and incident details under 10,000 characters."), 400
    if len(reported_by) > 100:
        return jsonify(error="Your name must be 100 characters or fewer."), 400
    if source not in db.SOURCES:
        return jsonify(error="Choose a valid incident source."), 400
    if severity not in {"P1", "P2", "P3", "P4"}:
        return jsonify(error="Choose a valid severity."), 400
    report = report_text
    if where_seen:
        report += f"\n\nWhere it was seen: {where_seen}"

    saved = db.create_or_reuse_incident(
        title=title,
        report=report,
        incident_type=incident_type,
        severity=severity,
        source=source,
        reported_by=reported_by,
    )
    return jsonify(
        id=saved["id"],
        url=url_for("incident_page", incident_id=saved["id"]),
        duplicate=saved["duplicate"],
        report_count=saved["report_count"],
    )


@app.post("/api/ask")
def ask_agent():
    body = _json_body()
    report = str(body.get("report", "")).strip()
    if not report:
        return jsonify(error="Describe what is going wrong."), 400
    if len(report) > MAX_TEXT_LENGTH:
        return jsonify(error="Incident details must be 10,000 characters or fewer."), 400
    if body.get("phase") == "recall":
        try:
            return jsonify(_ask_recall(report))
        except AskRecallFailure as error:
            app.logger.error("Ask recall failed for incident %s", error.saved["id"])
            return jsonify(
                error="The incident was saved, but related memories could not be loaded.",
                id=error.saved["id"],
                url=url_for("incident_page", incident_id=error.saved["id"]),
                duplicate=error.saved["duplicate"],
                report_count=error.saved["report_count"],
            ), 503
        except Exception as error:
            app.logger.error("Ask recall failed (%s)", type(error).__name__)
            return jsonify(
                error="The incident was saved, but related memories could not be loaded.",
            ), 503
    try:
        return jsonify(_ask_report(report))
    except AskTriageFailure as error:
        app.logger.error("Ask triage failed for incident %s", error.saved["id"])
        return jsonify(
            error="The incident was saved, but the agent could not complete triage. Open the incident and retry.",
            id=error.saved["id"],
            url=url_for("incident_page", incident_id=error.saved["id"]),
            duplicate=error.saved["duplicate"],
            report_count=error.saved["report_count"],
        ), 503
    except Exception as error:
        app.logger.error("Ask request failed (%s)", type(error).__name__)
        return jsonify(error="The request could not be completed. Please try again."), 503


@app.post("/api/incidents/<int:incident_id>/try-reworded")
def try_reworded_incident(incident_id: int):
    incident = db.get_incident(incident_id)
    if incident is None:
        return jsonify(error="Incident not found."), 404
    try:
        import agent

        rewritten = agent.rephrase_report(incident["report"])
        if not rewritten or len(rewritten) > MAX_TEXT_LENGTH:
            raise ValueError("The reworded report was empty or too long.")
        return jsonify(_ask_report(rewritten, reported_by=incident["reported_by"]))
    except AskTriageFailure as error:
        app.logger.error("Reworded triage failed for incident %s", error.saved["id"])
        return jsonify(
            error="The reworded report was saved, but triage could not finish.",
            id=error.saved["id"],
            url=url_for("incident_page", incident_id=error.saved["id"]),
            duplicate=error.saved["duplicate"],
            report_count=error.saved["report_count"],
        ), 503
    except Exception as error:
        app.logger.error(
            "Reworded Ask failed for incident %s (%s)",
            incident_id,
            type(error).__name__,
        )
        return jsonify(
            error="The agent could not create and triage a reworded report right now. Please try again."
        ), 503


@app.delete("/api/incidents/<int:incident_id>")
def delete_incident(incident_id: int):
    if not db.delete_open_incident(incident_id):
        incident = db.get_incident(incident_id)
        if incident is None:
            return jsonify(error="Incident not found."), 404
        return jsonify(error="Only open incidents can be deleted."), 409
    return jsonify(ok=True)


@app.post("/api/compare")
def compare_incident():
    body = _json_body()
    report = str(body.get("report", "")).strip()
    incident_id = body.get("incident_id")
    incident = None
    if incident_id not in (None, ""):
        try:
            incident = db.get_incident(int(incident_id))
        except (TypeError, ValueError):
            return jsonify(error="Choose a valid incident."), 400
        if incident is None:
            return jsonify(error="Incident not found."), 404
        report = f"{incident['title']}\n{incident['report']}"
    if not report:
        return jsonify(error="Select an incident or enter the incident details."), 400
    if len(report) > MAX_TEXT_LENGTH:
        return jsonify(error="Incident details must be 10,000 characters or fewer."), 400

    phase = body.get("phase")
    if phase == "recall":
        try:
            import agent

            memories = agent.recall_similar(report)
            return jsonify(
                memories=memories,
                memory_sources=db.match_memory_sources(memories),
            )
        except Exception as error:
            app.logger.error("Comparison recall failed (%s)", type(error).__name__)
            return jsonify(
                error="Related memories could not be loaded for comparison."
            ), 503

    recalled_memories = None
    if phase == "complete":
        values = body.get("memories")
        if (
            not isinstance(values, list)
            or len(values) > 6
            or any(not isinstance(value, str) or len(value) > 10000 for value in values)
            or sum(len(value) for value in values if isinstance(value, str)) > 20000
        ):
            return jsonify(error="The recalled memory set is invalid."), 400
        recalled_memories = [
            text for value in values if (text := _plain_text(value))
        ]

    try:
        import agent

        if recalled_memories is None:
            without_diagnosis = agent.diagnose(report, use_memory=False)
            with_diagnosis = agent.diagnose(report, use_memory=True)
        else:
            without_diagnosis = agent.diagnose_with_memories(report, [])
            with_diagnosis = agent.diagnose_with_memories(report, recalled_memories)
        without_memory = _format_diagnosis(without_diagnosis, use_memory=False)
        with_memory = _format_diagnosis(with_diagnosis, use_memory=True)
        with_memory = _add_memory_trail(with_memory)
        if incident is not None:
            db.save_diagnosis(
                incident["id"],
                mode="no_memory",
                memories=without_memory["memories"],
                confidence=without_memory["match_confidence"],
            )
            db.save_briefing(
                incident["id"],
                with_memory,
                with_memory["memories"],
                with_memory["match_confidence"],
            )
    except Exception as error:
        app.logger.error("Comparison failed (%s)", type(error).__name__)
        return jsonify(error="The comparison is temporarily unavailable. Please try again."), 503

    if with_memory["memories"]:
        explanation = (
            f"The model cited {len(with_memory['memories'])} similar past incident"
            f"{'s' if len(with_memory['memories']) != 1 else ''}."
        )
    else:
        explanation = (
            "No recalled memories were cited as relevant, so the with-memory result "
            "used general guidance."
        )
    return jsonify(
        without_memory=without_memory,
        with_memory=with_memory,
        explanation=explanation,
    )


@app.post("/api/compare/reworded")
def compare_reworded_incident():
    body = _json_body()
    report = str(body.get("report", "")).strip()
    if not report:
        return jsonify(error="Enter or select an incident before rewording it."), 400
    if len(report) > MAX_TEXT_LENGTH:
        return jsonify(error="Incident details must be 10,000 characters or fewer."), 400

    phase = body.get("phase")
    if phase == "recall":
        try:
            import agent

            rewritten = agent.rephrase_report(report)
            if not rewritten or len(rewritten) > MAX_TEXT_LENGTH:
                raise ValueError("The reworded report was empty or too long.")
            memories = agent.recall_similar(rewritten)
            return jsonify(
                report=rewritten,
                memories=memories,
                memory_sources=db.match_memory_sources(memories),
            )
        except Exception as error:
            app.logger.error("Reworded recall failed (%s)", type(error).__name__)
            return jsonify(
                error="The report could not be reworded and recalled right now."
            ), 503

    recalled_memories = None
    rewritten = report
    if phase == "complete":
        values = body.get("memories")
        if (
            not isinstance(values, list)
            or len(values) > 6
            or any(not isinstance(value, str) or len(value) > 10000 for value in values)
            or sum(len(value) for value in values if isinstance(value, str)) > 20000
        ):
            return jsonify(error="The recalled memory set is invalid."), 400
        recalled_memories = [
            text for value in values if (text := _plain_text(value))
        ]
    try:
        import agent

        if recalled_memories is None:
            rewritten = agent.rephrase_report(report)
            if not rewritten or len(rewritten) > MAX_TEXT_LENGTH:
                raise ValueError("The reworded report was empty or too long.")
            without_diagnosis = agent.diagnose(rewritten, use_memory=False)
            with_diagnosis = agent.diagnose(rewritten, use_memory=True)
        else:
            without_diagnosis = agent.diagnose_with_memories(rewritten, [])
            with_diagnosis = agent.diagnose_with_memories(
                rewritten, recalled_memories
            )
        without_memory = _format_diagnosis(without_diagnosis, use_memory=False)
        with_memory = _format_diagnosis(with_diagnosis, use_memory=True)
        with_memory = _add_memory_trail(with_memory)
    except Exception as error:
        app.logger.error("Reworded comparison failed (%s)", type(error).__name__)
        return jsonify(
            error="The report could not be reworded and compared right now. Please try again."
        ), 503
    return jsonify(
        report=rewritten,
        without_memory=without_memory,
        with_memory=with_memory,
        explanation=(
            f"The model cited {len(with_memory['memories'])} related "
            f"incident memor{'y' if len(with_memory['memories']) == 1 else 'ies'}."
            if with_memory["memories"]
            else "No recalled memories were cited as relevant for the reworded report."
        ),
    )


@app.post("/api/incidents/<int:incident_id>/triage")
def triage_incident(incident_id: int):
    incident = db.get_incident(incident_id)
    if incident is None:
        return jsonify(error="Incident not found."), 404
    if incident["briefing_json"]:
        return jsonify(_clean_briefing(json.loads(incident["briefing_json"])))
    try:
        return jsonify(_run_triage(incident))
    except Exception as error:
        app.logger.error("Triage failed for incident %s (%s)", incident_id, type(error).__name__)
        return jsonify(
            error="Triage is temporarily unavailable. The incident is saved; try again shortly."
        ), 503


@app.post("/api/incidents/<int:incident_id>/recall")
def recall_incident(incident_id: int):
    incident = db.get_incident(incident_id)
    if incident is None:
        return jsonify(error="Incident not found."), 404
    if incident["briefing_json"]:
        return jsonify(
            complete=True,
            briefing=_clean_briefing(json.loads(incident["briefing_json"])),
        )
    try:
        memories = _recall_memories(incident)
        return jsonify(
            complete=False,
            memories=memories,
            memory_sources=db.match_memory_sources(memories),
        )
    except Exception as error:
        app.logger.error(
            "Incident recall failed for %s (%s)",
            incident_id,
            type(error).__name__,
        )
        return jsonify(
            error="Related memories could not be loaded. Please retry triage."
        ), 503


@app.post("/api/incidents/<int:incident_id>/status")
def update_incident_status(incident_id: int):
    status = str(_json_body().get("status", ""))
    if status not in db.STATUSES:
        return jsonify(error="Choose a valid incident status."), 400
    if not db.set_status(incident_id, status):
        return jsonify(error="Incident not found."), 404
    return jsonify(ok=True, status=status)


def _retain_resolution(
    report: str,
    root_cause: str,
    fix: str,
    not_worked: str,
    incident_id: int,
    title: str,
    incident_type: str,
) -> None:
    import agent

    agent.save_resolution(
        report,
        root_cause,
        fix,
        not_worked,
        incident_id=incident_id,
        title=title,
        incident_type=incident_type,
    )


def _retain_resolution_for(incident: dict[str, Any]):
    def retain(report: str, root_cause: str, fix: str, not_worked: str) -> None:
        _retain_resolution(
            report,
            root_cause,
            fix,
            not_worked,
            int(incident["id"]),
            str(incident["title"]),
            str(incident["type"]),
        )

    return retain


@app.post("/api/incidents/<int:incident_id>/resolve")
def resolve_incident(incident_id: int):
    body = _json_body()
    root_cause = str(body.get("root_cause", "")).strip()
    fix = str(body.get("fix", "")).strip()
    not_worked = str(body.get("not_worked", "")).strip()
    if not root_cause or not fix:
        return jsonify(error="Root cause and fix are required."), 400
    incident = db.get_incident(incident_id)
    if incident is None:
        return jsonify(error="Incident not found."), 404
    try:
        updated = db.resolve_and_retain(
            incident_id, root_cause, fix, not_worked, _retain_resolution_for(incident)
        )
    except Exception as error:
        app.logger.error(
            "Resolution could not be saved for incident %s (%s)",
            incident_id,
            type(error).__name__,
        )
        return jsonify(error="The resolution could not be saved. Please try again."), 500
    if not updated:
        return jsonify(error="Incident not found."), 404
    return jsonify(ok=True, memory_sync="pending")


@app.post("/api/incidents/<int:incident_id>/retry-memory")
def retry_memory(incident_id: int):
    incident = db.get_incident(incident_id)
    if incident is None:
        return jsonify(error="Incident not found."), 404
    if not incident["root_cause"] or not incident["fix"]:
        return jsonify(error="Save a root cause and fix before retrying memory."), 400
    try:
        updated = db.resolve_and_retain(
            incident_id,
            incident["root_cause"],
            incident["fix"],
            incident["not_worked"] or "",
            _retain_resolution_for(incident),
        )
    except Exception as error:
        app.logger.error(
            "Memory retry could not start for incident %s (%s)",
            incident_id,
            type(error).__name__,
        )
        return jsonify(error="The memory retry could not start. Please try again."), 500
    if not updated:
        return jsonify(error="Incident not found."), 404
    return jsonify(ok=True, memory_sync="pending")


@app.get("/api/incidents/<int:incident_id>/memory-sync")
def memory_sync_status(incident_id: int):
    incident = db.get_incident(incident_id)
    if incident is None:
        return jsonify(error="Incident not found."), 404
    return jsonify(memory_sync=incident["memory_sync"])


@app.post("/api/diagnose")
def diagnose():
    report = str(_json_body().get("report", "")).strip()
    if not report:
        return jsonify(error="Please paste an error or problem report."), 400
    try:
        import agent

        return jsonify(agent.diagnose(report))
    except Exception as error:
        app.logger.error("Standalone diagnosis failed (%s)", type(error).__name__)
        return jsonify(error="Diagnosis is temporarily unavailable."), 503


@app.post("/api/save")
def save():
    body = _json_body()
    report = str(body.get("report", "")).strip()
    fix = str(body.get("fix", "")).strip()
    if not report or not fix:
        return jsonify(error="Report and fix are required."), 400
    try:
        import agent

        incident_id = db.create_incident(
            title=report[:160],
            report=report,
            incident_type=str(body.get("type", "General"))[:80] or "General",
            severity="P3",
            source="web",
            reported_by="API user",
        )
        updated = db.resolve_and_retain(
            incident_id,
            str(body.get("root_cause", "Not specified")),
            fix,
            str(body.get("didnt_work", "")),
            _retain_resolution_for(db.get_incident(incident_id)),
        )
        if not updated:
            return jsonify(error="The report was saved, but its resolution could not be started."), 500
        return jsonify(ok=True, incident_id=incident_id, memory_sync="pending")
    except Exception as error:
        app.logger.error("Standalone memory save failed (%s)", type(error).__name__)
        return jsonify(error="Memory save is temporarily unavailable."), 503


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO)
    warn_missing(
        (
            "SECRET_KEY",
            "REPORT_API_TOKEN",
            "HINDSIGHT_URL",
            "HINDSIGHT_API_KEY",
            "GROQ_API_KEY",
        ),
        "the website",
    )
    if not os.environ.get("SECRET_KEY"):
        raise SystemExit(1)
    app.run(debug=True, port=5000)
