"""Load role prompts from ``agents/``."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

AGENTS_DIR = Path(__file__).resolve().parents[3] / "agents"


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    p = AGENTS_DIR / f"{name}.md"
    if not p.exists():
        # minimal fallback keeps the mock working even if prompts are missing
        return f"<!-- task: {name} -->\n"
    return p.read_text(encoding="utf-8")
