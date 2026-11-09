"""Core agent: recall past incidents from Hindsight, diagnose with Groq, retain new fixes."""
from difflib import SequenceMatcher
import json
import os
import re
import time

from settings import load_env

load_env()

from groq import APIStatusError, Groq
from hindsight_client import Hindsight

BANK = os.environ.get("HINDSIGHT_BANK", "incident-memory")
MODEL = os.environ.get("GROQ_MODEL") or "openai/gpt-oss-20b"
FALLBACK_MODEL = "llama-3.3-70b-versatile"

_memory: Hindsight | None = None
_llm: Groq | None = None


def _get_memory() -> Hindsight:
    global _memory
    if _memory is None:
        _memory = Hindsight(
            base_url=os.environ["HINDSIGHT_URL"],
            api_key=os.environ["HINDSIGHT_API_KEY"],
        )
    return _memory


def _get_llm() -> Groq:
    global _llm
    if _llm is None:
        _llm = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _llm

SYSTEM_PROMPT = """You are an incident-response assistant with memory of this team's past incidents.
You are given a new problem report and a list of memories from similar past incidents.

Rules:
- Return exactly one JSON object with keys likely_match, match_confidence,
  root_cause, fix_steps, skip_these, and cited_memory_ids.
- Use plain text only in every JSON value; do not use Markdown, bold markers, or bullets.
- Cite memories by their 1-based IDs. cited_memory_ids must contain only memories you actually used.
- If no memory is useful, set confidence to 0 and cited_memory_ids to an empty array.
- Set match_confidence from 0 to 100 based on the cited memories.
- Keep root_cause to at most two sentences.
- Return at most six fix_steps, with exactly one sentence in each item.
- Return at most three skip_these strings, and only when a cited memory has an explicit
  "What did NOT work" or equivalent note. Never invent failures or fixes.
- Never return a fix-step heading; each fix step must be an actionable sentence."""


def recall_similar(report: str, limit: int = 6) -> list[str]:
    """Ask Hindsight for past incidents related to this report."""
    started = time.perf_counter()
    try:
        res = _get_memory().recall(
            bank_id=BANK,
            query=report,
            budget="low",
            max_tokens=2048,
        )
        unique: list[str] = []
        for result in res.results:
            text = str(result.text or "").replace("**", "")
            text = re.sub(r"[•●▪◦‣]", "", text)
            text = re.sub(r"(?m)^\s*(?:[-*]\s+|\d+[.)]\s+)", "", text).strip()
            if not text:
                continue
            if any(
                SequenceMatcher(None, text.casefold(), prior.casefold()).ratio() > 0.8
                for prior in unique
            ):
                continue
            unique.append(text)
            if len(unique) >= min(limit, 6):
                break
        return unique
    finally:
        print(f"Briefing recall: {time.perf_counter() - started:.2f}s")


def diagnose(report: str, use_memory: bool = True) -> dict:
    """Full flow: recall -> reason. Returns the answer plus the memories used."""
    memories = recall_similar(report) if use_memory else []
    return diagnose_with_memories(report, memories)


def diagnose_with_memories(report: str, memories: list[str]) -> dict:
    """Build a diagnosis using exactly the supplied memory set."""
    memory_block = "\n".join(
        f"[{index}] {memory}" for index, memory in enumerate(memories, 1)
    ) or "(no memories found)"
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"New problem report:\n{report}\n\nPast incident memories:\n{memory_block}",
        },
    ]
    started = time.perf_counter()
    try:
        completion = _create_briefing_completion(messages)
        return {"answer": completion.choices[0].message.content, "memories": memories}
    finally:
        print(f"Briefing Groq call: {time.perf_counter() - started:.2f}s")


def _create_briefing_completion(messages: list[dict[str, str]]):
    models = list(dict.fromkeys((MODEL, FALLBACK_MODEL)))
    for index, model in enumerate(models):
        parameters = {
            "model": model,
            "temperature": 0.2,
            "max_tokens": 600,
            "response_format": {"type": "json_object"},
            "messages": messages,
        }
        if model.startswith("openai/gpt-oss-"):
            parameters["reasoning_effort"] = "low"
        try:
            return _get_llm().chat.completions.create(**parameters)
        except APIStatusError as error:
            if index == 0 and model != FALLBACK_MODEL and error.status_code in {400, 404}:
                continue
            raise
    raise RuntimeError("No Groq model could complete the briefing.")


def assess_change_risk(change: str, memories: list[str]) -> dict:
    """Estimate operational change risk only from explicitly recalled records."""
    if not memories:
        return {
            "risk_level": "Unknown",
            "reasons": [],
            "what_failed_before": [],
            "rollback_note": "No history for this kind of change, risk unknown.",
        }
    numbered_memories = "\n".join(
        f"[{index}] {memory}" for index, memory in enumerate(memories, 1)
    )
    completion = _get_llm().chat.completions.create(
        model=MODEL,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "Assess an operational change using only the supplied incident memories. "
                    "Do not infer hazards, rollback steps, or failures not present in the records. "
                    "Return only JSON with keys risk_level (Low, Medium, High, or Unknown), "
                    "reasons (array of objects with text and memory_ids array), "
                    "what_failed_before (array of objects with text and memory_ids array), "
                    "rollback_note (string). Every reason and failure must cite one or more "
                    "valid memory ids from the numbered records. If evidence is insufficient, "
                    "set risk_level to Unknown and state that plainly."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Proposed change:\n{change}\n\n"
                    f"Past incident memories:\n{numbered_memories}"
                ),
            },
        ],
    )
    text = str(completion.choices[0].message.content or "").strip()
    parsed = _parse_json_object(text)
    level = str(parsed.get("risk_level", "Unknown")).capitalize()
    if level not in {"Low", "Medium", "High", "Unknown"}:
        level = "Unknown"
    valid_ids = set(range(1, len(memories) + 1))

    def validated_items(key: str) -> list[dict]:
        values = parsed.get(key)
        if not isinstance(values, list):
            return []
        output = []
        for value in values:
            if not isinstance(value, dict):
                continue
            text_value = str(value.get("text", "")).strip()
            ids = value.get("memory_ids", [])
            if not text_value or not isinstance(ids, list):
                continue
            citations = [
                identifier
                for identifier in ids
                if isinstance(identifier, int) and identifier in valid_ids
            ]
            if citations:
                output.append({"text": text_value, "memory_ids": citations})
        return output

    reasons = validated_items("reasons")
    failures = validated_items("what_failed_before")
    if level != "Unknown" and not reasons:
        level = "Unknown"
    rollback_note = str(parsed.get("rollback_note", "")).strip()
    if not rollback_note:
        rollback_note = "No rollback detail was recorded in the supplied memories."
    return {
        "risk_level": level,
        "reasons": reasons,
        "what_failed_before": failures,
        "rollback_note": rollback_note,
    }


def _parse_json_object(value: str) -> dict:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        start, end = value.find("{"), value.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            parsed = json.loads(value[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def rephrase_report(report: str) -> str:
    """Rewrite an incident without changing its factual details."""
    completion = _get_llm().chat.completions.create(
        model=MODEL,
        temperature=0.3,
        messages=[
            {
                "role": "system",
                "content": (
                    "Rewrite the incident report in different words while preserving "
                    "all technical facts, names, error messages, and uncertainty. "
                    "Return only the rewritten report."
                ),
            },
            {"role": "user", "content": report},
        ],
    )
    rewritten = completion.choices[0].message.content
    if not rewritten or not rewritten.strip():
        raise ValueError("The model returned an empty rewrite.")
    return rewritten.strip()


def save_resolution(
    report: str,
    root_cause: str,
    fix: str,
    didnt_work: str = "",
    incident_id: int | None = None,
    title: str = "",
    incident_type: str = "General",
) -> None:
    """Retain: store a freshly resolved incident so the agent knows more next time."""
    content = (
        f"{f'Incident #{incident_id}. ' if incident_id is not None else ''}"
        f"Incident type: {incident_type}. "
        f"{f'Title: {title}. ' if title else ''}"
        f"Report: {report} Root cause: {root_cause} Fix: {fix}"
        + (f" What did NOT work: {didnt_work}" if didnt_work else "")
    )
    _get_memory().retain(bank_id=BANK, content=content, context="incident resolution")


def save_outcome(content: str) -> None:
    _get_memory().retain(bank_id=BANK, content=content, context="incident outcome")
