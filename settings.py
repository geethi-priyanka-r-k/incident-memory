"""Small standard-library loader for the project's local .env file."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

_VARIABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_env(path: Path | None = None) -> None:
    """Load KEY=VALUE lines without replacing existing process variables."""
    env_path = path or Path(__file__).with_name(".env")
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, value = line.partition("=")
        name = name.strip()
        if not separator or not _VARIABLE_NAME.fullmatch(name):
            raise ValueError(f"Invalid .env entry on line {line_number}.")
        if name in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[name] = value


def missing_message(required: Iterable[str], context: str) -> str:
    missing = [name for name in required if not os.environ.get(name)]
    if not missing:
        return ""
    names = ", ".join(missing)
    return (
        f"Missing required environment variable(s): {names}. Add them to the "
        f"project .env file (copy .env.example to .env) or set them in "
        f"PowerShell, then restart {context}."
    )


def warn_missing(required: Iterable[str], context: str) -> bool:
    """Print one actionable, key-free warning and report whether it occurred."""
    message = missing_message(required, context)
    if not message:
        return False
    print(message)
    return True
