"""System prompts stored as Markdown so they can be reviewed apart from the code."""

from functools import cache
from pathlib import Path

PROMPT_DIR = Path(__file__).parent


@cache
def load_prompt(*names: str) -> str:
    parts = ((PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8").strip() for name in names)
    return "\n\n".join(parts)
