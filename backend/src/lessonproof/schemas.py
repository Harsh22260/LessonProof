"""Typed contracts shared by every agent, check, and report."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class SectionRole(StrEnum):
    INTRO = "intro"
    WHAT = "what"
    WHY = "why"
    HOW = "how"
    EXAMPLE = "example"
    LIMITS = "limits"
    RECAP = "recap"


class Section(BaseModel):
    role: SectionRole
    heading: str
    body: str = Field(description="Markdown body. Short paragraphs and numbered lists are allowed.")


class KeyTerm(BaseModel):
    term: str
    definition: str = Field(description="One plain-language sentence.")


class QuizQuestion(BaseModel):
    question: str
    answer: str


class Lesson(BaseModel):
    title: str
    sections: list[Section]
    key_terms: list[KeyTerm]
    quiz: list[QuizQuestion]

    def section(self, role: SectionRole) -> Section | None:
        return next((s for s in self.sections if s.role == role), None)

    def teaching_text(self) -> str:
        """Section bodies only: the text the learner reads to learn the topic."""
        return "\n\n".join(s.body for s in self.sections)

    def to_markdown(self) -> str:
        parts = [f"# {self.title}"]
        parts += [f"## {s.heading}\n\n{s.body.strip()}" for s in self.sections]
        if self.key_terms:
            terms = "\n".join(f"- **{t.term}**: {t.definition}" for t in self.key_terms)
            parts.append(f"## Key Words\n\n{terms}")
        if self.quiz:
            questions = "\n\n".join(
                f"**Question {i}.** {q.question}\n\n*Answer:* {q.answer}"
                for i, q in enumerate(self.quiz, start=1)
            )
            parts.append(f"## Check Yourself\n\n{questions}")
        return "\n\n".join(parts) + "\n"

    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:12]


class SectionPlan(BaseModel):
    role: SectionRole
    heading: str = Field(default="", description="This section's own unique heading.")
    goal: str
    must_include: list[str]
    word_target: int = Field(default=110, description="Target length of this section in words.")
    fact_ids: list[str] = Field(default_factory=list, description="Facts this section relies on.")
    terms_to_define: list[str] = Field(
        default_factory=list, description="Terms first explained in this section."
    )


class LessonPlan(BaseModel):
    title: str = Field(default="", description="A short, simple lesson title.")
    learning_objectives: list[str]
    running_example: str = Field(
        description="One concrete everyday scenario that is carried through the whole lesson."
    )
    sections: list[SectionPlan]


class SectionDraft(BaseModel):
    heading: str = Field(description="A short heading in simple words.")
    body: str = Field(description="Markdown body of this one section.")


class LessonExtras(BaseModel):
    key_terms: list[KeyTerm]
    quiz: list[QuizQuestion]


class Fact(BaseModel):
    id: str
    text: str
    source: str = ""


class KeyPoint(BaseModel):
    id: str
    text: str


class FactPack(BaseModel):
    """Trusted reference material the writer must use and the evaluator grades against."""

    topic: str
    aliases: list[str] = Field(default_factory=list)
    provenance: Literal["curated", "model_generated"] = "curated"
    facts: list[Fact]
    key_points: list[KeyPoint]
    must_define: list[str] = Field(default_factory=list)
    misconceptions: list[str] = Field(default_factory=list)
    abbreviations: dict[str, str] = Field(default_factory=dict)
    glossary: list[KeyTerm] = Field(default_factory=list)

    def facts_block(self, ids: list[str] | None = None) -> str:
        chosen = [f for f in self.facts if not ids or f.id in ids] or self.facts
        return "\n".join(f"[{f.id}] {f.text}" for f in chosen)

    def key_points_block(self) -> str:
        return "\n".join(f"[{k.id}] {k.text}" for k in self.key_points)

    def misconceptions_block(self) -> str:
        return "\n".join(f"- {m}" for m in self.misconceptions)


class CheckResult(BaseModel):
    check_id: str
    dimension: str
    passed: bool
    reason: str
    fix: str = ""
    evidence: list[str] = Field(default_factory=list)
    evidence_verified: bool = True
    source: Literal["deterministic", "judge", "audit"] = "deterministic"
    covered_quotes: dict[str, str] = Field(default_factory=dict)


class EvaluationReport(BaseModel):
    attempt: int
    lesson_fingerprint: str
    rubric_version: int
    results: list[CheckResult]
    complete: bool = True
    reused_checks: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.complete and bool(self.results) and all(r.passed for r in self.results)

    @property
    def failures(self) -> list[CheckResult]:
        return [r for r in self.results if not r.passed]

    @property
    def pass_count(self) -> int:
        return sum(r.passed for r in self.results)


class SectionPatch(BaseModel):
    role: SectionRole
    heading: str
    body: str


class ChangeNote(BaseModel):
    check_id: str
    change: str = Field(description="What was changed in the lesson to fix this check.")


class RevisionPatch(BaseModel):
    """Targeted edit. Anything left out stays exactly as it was."""

    section_updates: list[SectionPatch] = Field(default_factory=list)
    key_terms: list[KeyTerm] | None = Field(
        default=None, description="Full replacement list, or null to keep the current list."
    )
    quiz: list[QuizQuestion] | None = Field(
        default=None, description="Full replacement list, or null to keep the current quiz."
    )
    change_notes: list[ChangeNote]


class RevisionRecord(BaseModel):
    """What a retry changed, computed from the lessons rather than taken from the reviser."""

    base_attempt: int
    rolled_back: bool
    sections_changed: list[str]
    key_terms_changed: bool
    quiz_changed: bool
    words_added: int
    words_removed: int
    notes: list[ChangeNote]


class AttemptRecord(BaseModel):
    attempt: int
    lesson: Lesson
    report: EvaluationReport
    revision: RevisionRecord | None = None
    seconds: float = 0.0
    code_fixes: list[str] = Field(default_factory=list)
    repaired_rule_failures: list[CheckResult] = Field(default_factory=list)


def best_attempt(attempts: list[AttemptRecord]) -> AttemptRecord:
    """The latest draft, unless an earlier one failed fewer of the checks both drafts ran."""
    best = attempts[-1]
    for candidate in reversed(attempts[:-1]):
        best_results = {r.check_id: r.passed for r in best.report.results}
        other_results = {r.check_id: r.passed for r in candidate.report.results}
        shared = best_results.keys() & other_results.keys()
        best_failures = sum(not best_results[c] for c in shared)
        other_failures = sum(not other_results[c] for c in shared)
        if other_failures < best_failures:
            best = candidate
    return best
