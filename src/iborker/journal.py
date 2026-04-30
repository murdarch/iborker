"""Append-only daily session journal for guardrails mode.

Writes to ``workspace/journal/YYYY-MM-DD.md`` relative to the project root
(i.e. wherever the trader was launched from).  ``workspace/`` is gitignored.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

JOURNAL_DIR = Path("workspace") / "journal"


def _today_path() -> Path:
    return JOURNAL_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.md"


def append(entry: str) -> Path:
    """Append a markdown entry to today's journal file.

    Caller is expected to format multi-line content; we just ensure trailing
    newlines so successive entries don't run together.  Returns the path
    written to.
    """
    path = _today_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = entry.rstrip() + "\n\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(text)
    return path


def append_clock_in() -> Path:
    ts = datetime.now().strftime("%H:%M:%S")
    return append(f"## {ts} — Clock in")


def append_checklist(answers: tuple[str, ...], questions: tuple[str, ...]) -> Path:
    ts = datetime.now().strftime("%H:%M:%S")
    lines = [f"## {ts} — Checklist submitted"]
    for q, a in zip(questions, answers, strict=True):
        lines.append(f"- **{q}**")
        lines.append(f"  {a}")
    return append("\n".join(lines))


def append_rearm(reason: str) -> Path:
    ts = datetime.now().strftime("%H:%M:%S")
    return append(f"## {ts} — Re-arm reason\n\n{reason}")
