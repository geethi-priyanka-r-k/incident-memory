"""Connect the incident memory agent to Band rooms."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import traceback
from typing import Any

from settings import load_env, missing_message

load_env()

from band import Agent
from band.core import AgentToolsProtocol, SimpleAdapter
from band.core.types import PlatformMessage
from band.runtime.formatters import strip_leading_mentions

import db

REQUIRED_ENV_VARS = (
    "BAND_API_KEY",
    "BAND_AGENT_ID",
    "HINDSIGHT_URL",
    "HINDSIGHT_API_KEY",
    "GROQ_API_KEY",
)
MAX_MESSAGE_LENGTH = 10000

RESOLVE_COMMAND = re.compile(
    r"^\s*resolve\s+#(?P<incident_id>\d+)\b(?P<fields>.*)$",
    re.IGNORECASE | re.DOTALL,
)
RESOLVE_PREFIX = re.compile(r"^\s*resolve\b", re.IGNORECASE)
RESOLUTION_FIELD = re.compile(
    r"\b(root\s+cause|fix|not\s+worked)\s*:",
    re.IGNORECASE,
)
FIELD_NAMES = {
    "root cause": "root_cause",
    "fix": "fix",
    "not worked": "didnt_work",
}
DISPLAY_NAMES = {
    "root_cause": "root cause",
    "fix": "fix",
    "didnt_work": "not worked",
}


def parse_resolution(message: str) -> tuple[int | None, dict[str, str]]:
    command = RESOLVE_COMMAND.match(message)
    if command is None:
        return None, {}

    fields_text = command.group("fields")
    matches = list(RESOLUTION_FIELD.finditer(fields_text))
    values: dict[str, str] = {}
    for index, match in enumerate(matches):
        display_name = " ".join(match.group(1).casefold().split())
        field_name = FIELD_NAMES[display_name]
        value_start = match.end()
        value_end = matches[index + 1].start() if index + 1 < len(matches) else len(fields_text)
        values[field_name] = fields_text[value_start:value_end].strip()

    return int(command.group("incident_id")), values


def missing_resolution_fields(values: dict[str, str]) -> list[str]:
    return [
        DISPLAY_NAMES[name]
        for name in ("root_cause", "fix", "didnt_work")
        if not values.get(name)
    ]


def missing_fields_message(missing: list[str], missing_id: bool = False) -> str:
    requested = (["incident number (for example #12)"] if missing_id else []) + missing
    if len(requested) == 1:
        fields = requested[0]
    elif len(requested) == 2:
        fields = f"{requested[0]} and {requested[1]}"
    else:
        fields = ", ".join(requested[:-1]) + f", and {requested[-1]}"
    return f"Please add the missing {fields}."


def format_briefing(
    incident_id: int,
    diagnosis: dict[str, Any],
    recurrence_alert: str,
    report_count: int = 1,
) -> str:
    raw = str(diagnosis.get("answer") or "").strip()
    try:
        data = json.loads(raw)
        steps = "\n".join(f"{i}. {s}" for i, s in enumerate(data.get("fix_steps", []), 1))
        skip = "; ".join(data.get("skip_these", []))
        answer = (
            f"Likely match: {data.get('likely_match', '')} "
            f"({data.get('match_confidence', '?')}% confidence)\n"
            f"Root cause: {data.get('root_cause', '')}\n"
            f"Fix steps:\n{steps}\n"
            f"Don't try: {skip}"
        )
    except (ValueError, AttributeError, TypeError):
        answer = raw
    if not answer:
        answer = "The incident was saved, but the diagnosis did not include a briefing."
    if len(answer) > 1500:
        answer = answer[:1497].rsplit(" ", 1)[0] + "..."

    memories = diagnosis.get("memories") or []
    confidence = (
        "Moderate (related memories were found; verify them against this incident)."
        if memories
        else "Low (no related memories were found)."
    )
    memory_summary = (
        "\n".join(f"- {str(memory)[:180]}" for memory in memories)
        if memories
        else "- None"
    )
    return (
        f"Incident #{incident_id} saved"
        f"{f' (x{report_count} reports)' if report_count > 1 else ''}.\n"
        f"{answer}\n"
        f"Confidence: {confidence}\n"
        f"Memories recalled ({len(memories)}):\n{memory_summary}\n"
        f"Recurrence alert: {recurrence_alert}\n"
        f"Details: http://127.0.0.1:5000/incident/{incident_id}"
    )


def recurrence_alert(exact_match_id: int | None) -> str:
    if exact_match_id is not None:
        return f"Exact repeat of incident #{exact_match_id}. See /patterns."
    patterns = db.recurring_patterns(30)
    pattern = next((item for item in patterns if item["count"] >= 3), None)
    if pattern is None:
        return "No category reached three resolved incidents in 30 days. See /patterns."
    count = pattern["count"]
    ordinal = f"{count}{'th' if 10 <= count % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(count % 10, 'th')}"
    return (
        f"{ordinal.capitalize()} {pattern['type'].lower()} incident in 30 days. "
        "Consider a permanent fix. See /patterns."
    )
class MentionTools:
    """Wraps tools so every reply mentions the sender."""

    def __init__(self, tools, sender_id):
        self._tools = tools
        self._sender_id = sender_id

    def __getattr__(self, name):
        return getattr(self._tools, name)

    async def send_message(self, content, mentions=None):
        return await self._tools.send_message(
            content, mentions=mentions or [self._sender_id]
        )

class IncidentAdapter(SimpleAdapter[Any]):
    def __init__(self, incident_agent: Any) -> None:
        super().__init__()
        self.incident_agent = incident_agent

    async def on_message(
        self,
        msg: PlatformMessage,
        tools: AgentToolsProtocol,
        history: Any,
        participants_msg: str | None,
        contacts_msg: str | None,
        *,
        is_session_bootstrap: bool,
        room_id: str,
    ) -> None:
        try:
            if msg.sender_id == tools.agent_id:
                return 
            tools = MentionTools(tools, msg.sender_id)

            message = strip_leading_mentions(msg.content).strip()
            if os.environ.get("BAND_ECHO") == "1":
                await tools.send_message(f"Echo: {message}", mentions=[msg.sender_id])
                return
            if len(message) > MAX_MESSAGE_LENGTH:
                await tools.send_message(
                    "That message is too long. Please keep it under 10,000 characters."
                )
                return

            if RESOLVE_PREFIX.match(message):
                await self.resolve_and_retain(message, tools)
                return
            if not message:
                await tools.send_message("Please include the incident details after mentioning me.")
                return

            exact_match_id = db.find_exact_report(message)
            saved_incident = db.create_or_reuse_incident(
                title=message[:160],
                report=message,
                incident_type="General",
                severity="P3",
                source="band",
                reported_by=msg.sender_name or "Unknown sender",
            )
            incident_id = saved_incident["id"]
            try:
                diagnosis = await asyncio.to_thread(
                    self.incident_agent.diagnose, message
                )
            except Exception:
                await tools.send_message(
                    "I saved this incident, but couldn't complete memory triage right now. "
                    f"Please try again later. Details: "
                    f"http://127.0.0.1:5000/incident/{incident_id}"
                )
                return

            memories = [str(memory) for memory in diagnosis.get("memories", [])]
            confidence = 55 if memories else 0
            db.save_briefing(
                incident_id,
                {"answer": diagnosis.get("answer") or "", "memories": memories},
                memories,
                confidence,
            )
            await tools.send_message(
                format_briefing(
                    incident_id,
                    diagnosis,
                    recurrence_alert(exact_match_id),
                    saved_incident["report_count"],
                )
            )
        except Exception as error:
            traceback.print_exc()
            try:
                await tools.send_message(f"Internal error: {type(error).__name__}")
            except Exception:
                traceback.print_exc()

    async def resolve_and_retain(
        self,
        message: str,
        tools: AgentToolsProtocol,
    ) -> None:
        incident_id, values = parse_resolution(message)
        if incident_id is None:
            await tools.send_message(
                missing_fields_message(missing_resolution_fields(values), missing_id=True)
            )
            return

        missing = missing_resolution_fields(values)
        if missing:
            await tools.send_message(missing_fields_message(missing))
            return

        root_cause = values["root_cause"]
        fix = values["fix"]
        didnt_work = values["didnt_work"]
        saved = db.resolve_and_retain(
            incident_id,
            root_cause,
            fix,
            didnt_work,
            lambda report, cause, saved_fix, failed_attempt: (
                self.incident_agent.save_resolution(
                    report,
                    cause,
                    saved_fix,
                    failed_attempt,
                    incident_id=incident_id,
                    title=(db.get_incident(incident_id) or {}).get("title", ""),
                    incident_type=(db.get_incident(incident_id) or {}).get("type", "General"),
                )
            ),
        )
        if not saved:
            await tools.send_message(
                f"I couldn't find incident #{incident_id} in the local incident log."
            )
            return

        await tools.send_message("Saved to memory")


def required_environment() -> tuple[str, str]:
    message = missing_message(REQUIRED_ENV_VARS, "the Band bridge")
    if message:
        raise SystemExit(message)
    return os.environ["BAND_AGENT_ID"], os.environ["BAND_API_KEY"]


async def main() -> None:
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger("band").setLevel(logging.DEBUG)
    agent_id, api_key = required_environment()
    import agent as incident_agent

    db.initialize()
    heartbeat_stop = threading.Event()
    db.update_bridge_heartbeat("running")

    def heartbeat_loop() -> None:
        while not heartbeat_stop.wait(15):
            db.update_bridge_heartbeat("running")

    heartbeat_thread = threading.Thread(
        target=heartbeat_loop,
        name="band-bridge-heartbeat",
        daemon=True,
    )
    heartbeat_thread.start()
    try:
        band_agent = Agent.create(
            adapter=IncidentAdapter(incident_agent),
            agent_id=agent_id,
            api_key=api_key,
        )
        await band_agent.run()
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=2)
        db.update_bridge_heartbeat("stopped")


if __name__ == "__main__":
    asyncio.run(main())
