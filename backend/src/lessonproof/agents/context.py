"""Builds the tagged context blocks that agents receive in their user messages."""

import json

from lessonproof.rubric import Check, Rubric
from lessonproof.schemas import CheckResult, FactPack, Lesson

WRITER_RULES = ("ACC-3", "ACC-4", "LANG-1", "LANG-2", "LANG-3", "JAR-4", "BEG-2")


def tag(name: str, content: str) -> str:
    return f"<{name}>\n{content}\n</{name}>"


def grounding_block(pack: FactPack) -> str:
    return "\n\n".join(
        [
            tag("fact_sheet", pack.facts_block()),
            tag("key_points", pack.key_points_block()),
            tag("misconceptions", pack.misconceptions_block()),
            tag("terms_to_define", ", ".join(pack.must_define)),
        ]
    )


def _check_line(check: Check) -> str:
    suffix = f" Limits: {json.dumps(check.params)}." if check.params else ""
    return f"- {check.id}: {check.criterion}{suffix}"


def rubric_block(rubric: Rubric) -> str:
    return tag("rubric", "\n".join(_check_line(c) for c in rubric.checks))


def guidelines_block(guidelines: list[str]) -> str:
    if not guidelines:
        return ""
    lines = "\n".join(f"- {g}" for g in guidelines)
    return tag("lessons_from_past_runs", lines)


def writing_rules_block(rubric: Rubric) -> str:
    """The measurable limits only, which is all a section writer needs from the rubric."""
    lines = [_check_line(rubric.get(check_id)) for check_id in WRITER_RULES]
    return tag("writing_rules", "\n".join(lines))


def render_lesson(lesson: Lesson) -> str:
    """Compact form for prompts. Costs far fewer tokens than JSON and keeps section roles."""
    sections = "\n\n".join(f"[{s.role.value}] {s.heading}\n{s.body}" for s in lesson.sections)
    terms = "\n".join(f"- {t.term}: {t.definition}" for t in lesson.key_terms)
    quiz = "\n".join(f"Q: {q.question}\nA: {q.answer}" for q in lesson.quiz)
    return f"TITLE: {lesson.title}\n\n{sections}\n\nKEY WORDS\n{terms}\n\nQUIZ\n{quiz}"


def lesson_block(lesson: Lesson) -> str:
    return tag("lesson", render_lesson(lesson))


def failures_block(failures: list[CheckResult]) -> str:
    entries = [
        {
            "check_id": f.check_id,
            "reason": f.reason,
            "evidence": f.evidence,
            "required_fix": f.fix,
        }
        for f in failures
    ]
    return tag("failed_checks", json.dumps(entries, ensure_ascii=False))


def join_blocks(*blocks: str) -> str:
    return "\n\n".join(block for block in blocks if block)
