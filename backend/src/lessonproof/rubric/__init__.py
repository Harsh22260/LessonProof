"""The rubric: hard pass/fail checkpoints loaded from a versioned YAML file."""

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

RUBRIC_PATH = Path(__file__).parent / "rubric.yaml"


class Check(BaseModel):
    id: str
    label: str = ""
    dimension: str
    kind: Literal["deterministic", "judge", "audit"]
    criterion: str
    evidence_on_pass: bool = False
    params: dict[str, Any] = Field(default_factory=dict)


class Rubric(BaseModel):
    version: int
    checks: list[Check]

    def by_kind(self, kind: str) -> list[Check]:
        return [c for c in self.checks if c.kind == kind]

    def get(self, check_id: str) -> Check:
        return next(c for c in self.checks if c.id == check_id)

    def ids(self) -> set[str]:
        return {c.id for c in self.checks}


@lru_cache(maxsize=1)
def load_rubric() -> Rubric:
    return Rubric.model_validate(yaml.safe_load(RUBRIC_PATH.read_text(encoding="utf-8")))
