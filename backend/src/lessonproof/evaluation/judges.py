"""LLM evaluation. Models report findings; code verifies them and decides pass or fail.

Three safeguards keep the judges honest:
- Quotes must appear in the lesson. A fabricated quote triggers one re-ask.
- A check with no trustworthy answer fails. Unknown never becomes a pass.
- Audit verdicts are computed from item-level findings, not from a model's overall opinion.

On a retry, the audits look only at text that changed. Unchanged text keeps its verdict, and
problems found earlier stay open until the flagged text is gone.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from lessonproof import text as tx
from lessonproof.agents.context import (
    grounding_block,
    join_blocks,
    lesson_block,
    tag,
)
from lessonproof.llm import LLM
from lessonproof.prompts import load_prompt
from lessonproof.rubric import Check
from lessonproof.schemas import CheckResult, FactPack, Lesson, SectionRole

COMPARISON_MARKER = re.compile(
    r"\b(think of|imagine|picture|suppose|for example|is like|are like|acts? like|works? like|"
    r"just like|similar to)\b",
    re.IGNORECASE,
)


class Verdict(BaseModel):
    check_id: str
    passed: bool
    evidence_quotes: list[str]
    reason: str
    fix: str


class JudgeResponse(BaseModel):
    verdicts: list[Verdict]


class SentenceFinding(BaseModel):
    number: int
    status: Literal["supported", "contradicted", "unsupported", "illustrative"]
    fact_ids: list[str]
    explanation: str
    fix: str


class ClaimAudit(BaseModel):
    sentences: list[SentenceFinding]


@dataclass
class _Flag:
    sentence: str
    explanation: str
    fix: str


class CoverageFinding(BaseModel):
    key_point_id: str
    covered: bool
    quote: str
    explanation: str


class CoverageAudit(BaseModel):
    points: list[CoverageFinding]


def quote_in_lesson(quote: str, lesson_text: str) -> bool:
    fragments = [f for f in re.split(r"\.\.\.|…", quote) if f.strip()]
    return bool(fragments) and all(
        tx.normalise_for_match(fragment) in lesson_text for fragment in fragments
    )


def _lesson_search_text(lesson: Lesson) -> str:
    return tx.normalise_for_match(lesson.to_markdown())


def _notes_block(checks: Iterable[Check], notes: dict[str, list[str]]) -> str:
    lines = [f"- {c.id}: {note}" for c in checks for note in notes.get(c.id, [])]
    return tag("stricter_guidance", "\n".join(lines)) if lines else ""


def judge_group(
    llm: LLM,
    checks: list[Check],
    lesson: Lesson,
    notes: dict[str, list[str]],
) -> list[CheckResult]:
    expected = {c.id: c for c in checks}
    check_lines = "\n".join(
        f"- {c.id}: {c.criterion} (quote evidence on pass: "
        f"{'required' if c.evidence_on_pass else 'not required'})"
        for c in checks
    )
    base_user = join_blocks(
        lesson_block(lesson),
        tag("checks", check_lines),
        _notes_block(checks, notes),
    )
    system = load_prompt("audience", "judge")
    search_text = _lesson_search_text(lesson)

    response = llm.structured("judge", JudgeResponse, system, base_user)
    problems = _verdict_problems(response, expected, search_text)
    if problems:
        correction = tag("correct_these_problems", "\n".join(problems.values()))
        response = llm.structured(
            "judge", JudgeResponse, system, join_blocks(base_user, correction)
        )
        problems = _verdict_problems(response, expected, search_text)

    verdicts = {v.check_id: v for v in response.verdicts}
    return [_to_result(check, verdicts.get(check.id), problems.get(check.id)) for check in checks]


def _verdict_problems(
    response: JudgeResponse, expected: dict[str, Check], search_text: str
) -> dict[str, str]:
    problems: dict[str, str] = {}
    verdicts = {v.check_id: v for v in response.verdicts}
    for check_id, check in expected.items():
        verdict = verdicts.get(check_id)
        if verdict is None:
            problems[check_id] = f"{check_id}: no verdict was returned."
            continue
        invalid = [q for q in verdict.evidence_quotes if not quote_in_lesson(q, search_text)]
        if invalid:
            problems[check_id] = f"{check_id}: these quotes are not in the lesson: {invalid}."
        elif verdict.passed and check.evidence_on_pass and not verdict.evidence_quotes:
            problems[check_id] = f"{check_id}: a pass on this check requires a quote."
    return problems


def _to_result(check: Check, verdict: Verdict | None, problem: str | None) -> CheckResult:
    if verdict is None:
        return CheckResult(
            check_id=check.id,
            dimension=check.dimension,
            passed=False,
            reason="The judge returned no usable verdict, so the check fails closed.",
            fix="Make sure this check is clearly met.",
            evidence_verified=False,
            source="judge",
        )
    if problem and verdict.passed:
        return CheckResult(
            check_id=check.id,
            dimension=check.dimension,
            passed=False,
            reason=f"The judge's pass could not be verified, so it fails closed. {problem}",
            fix="Make sure this check is clearly met, with text a reviewer can point to.",
            evidence_verified=False,
            source="judge",
        )
    return CheckResult(
        check_id=check.id,
        dimension=check.dimension,
        passed=verdict.passed,
        reason=verdict.reason,
        fix=verdict.fix,
        evidence=verdict.evidence_quotes,
        evidence_verified=problem is None,
        source="judge",
    )


def audit_items(lesson: Lesson, previous: Lesson | None = None) -> list[str]:
    """Every sentence to fact-check, or only the sentences in changed parts on a retry."""
    earlier = {s.role: s.body for s in previous.sections} if previous else {}
    items = [
        sentence
        for section in lesson.sections
        if earlier.get(section.role) != section.body
        for sentence in tx.sentences(section.body)
    ]
    if previous is None or previous.key_terms != lesson.key_terms:
        items += [f"{t.term}: {t.definition}" for t in lesson.key_terms]
    if previous is None or previous.quiz != lesson.quiz:
        items += [f"Quiz question: {q.question} Quiz answer: {q.answer}" for q in lesson.quiz]
    return items


def _numbered(items: list[str], numbers: Iterable[int]) -> str:
    return "\n".join(f"[{n}] {items[n - 1]}" for n in numbers)


def audit_claims(
    llm: LLM,
    contradiction_check: Check,
    support_check: Check,
    lesson: Lesson,
    pack: FactPack,
    notes: dict[str, list[str]],
    previous_lesson: Lesson | None = None,
    previous_results: dict[str, CheckResult] | None = None,
) -> list[CheckResult]:
    """Code numbers each sentence and the model rules on each one, so nothing can be skipped."""
    checks = [contradiction_check, support_check]
    is_retry = previous_lesson is not None and bool(previous_results)
    items = audit_items(lesson, previous_lesson if is_retry else None)
    if is_retry and not items:
        return [previous_results[c.id] for c in checks]

    prefix = join_blocks(_notes_block(checks, notes), grounding_block(pack))
    system = load_prompt("claim_audit")
    all_numbers = list(range(1, len(items) + 1))
    user = join_blocks(prefix, tag("sentences", _numbered(items, all_numbers)))
    findings = {f.number: f for f in llm.structured("judge", ClaimAudit, system, user).sentences}

    skipped = [n for n in all_numbers if n not in findings]
    if skipped:
        user = join_blocks(prefix, tag("sentences", _numbered(items, skipped)))
        retry = llm.structured("judge", ClaimAudit, system, user)
        findings.update({f.number: f for f in retry.sentences})

    known_facts = {f.id for f in pack.facts} | {k.id for k in pack.key_points}
    example = lesson.section(SectionRole.EXAMPLE)
    example_sentences = set(tx.sentences(example.body)) if example else set()
    contradicted: list[_Flag] = []
    unsupported: list[_Flag] = []
    supported = 0
    for number in all_numbers:
        sentence = items[number - 1]
        finding = findings.get(number)
        if finding is None:
            unsupported.append(
                _Flag(sentence, "The fact checker gave no ruling.", "Base this on the fact sheet.")
            )
        elif finding.status == "contradicted":
            contradicted.append(_Flag(sentence, finding.explanation, finding.fix))
        elif finding.status == "unsupported":
            if sentence not in example_sentences and not _is_marked_comparison(sentence):
                unsupported.append(_Flag(sentence, finding.explanation, finding.fix))
        elif finding.status == "supported":
            if known_facts.intersection(finding.fact_ids):
                supported += 1
            else:
                unsupported.append(
                    _Flag(
                        sentence,
                        f"Marked supported, but it cites no real fact: {finding.fact_ids}.",
                        "Base this statement clearly on the fact sheet.",
                    )
                )

    search_text = _lesson_search_text(lesson)
    if is_retry:
        contradicted += _unresolved(previous_results[contradiction_check.id], search_text)
        unsupported += _unresolved(previous_results[support_check.id], search_text)
    elif supported == 0:
        reason = "The audit verified no supported sentences, so grounding cannot be confirmed."
        fix = "Ground the lesson in the facts."
        return [_audit_result(c, False, reason, fix) for c in checks]

    return [
        _claims_result(contradiction_check, contradicted, supported),
        _claims_result(support_check, unsupported, supported),
    ]


def _is_marked_comparison(sentence: str) -> bool:
    """A sentence openly marked as an analogy is not a factual claim, unless it is contradicted."""
    return COMPARISON_MARKER.search(sentence) is not None


def _unresolved(previous: CheckResult, search_text: str) -> list[_Flag]:
    if previous.passed:
        return []
    return [
        _Flag(quote, "Flagged in an earlier attempt and still in the lesson.", previous.fix)
        for quote in previous.evidence
        if quote_in_lesson(quote, search_text)
    ]


def _claims_result(check: Check, flagged: list[_Flag], supported: int) -> CheckResult:
    if not flagged:
        return _audit_result(check, True, f"No issues; {supported} sentences newly verified.")
    reason = " | ".join(f'"{f.sentence}": {f.explanation}' for f in flagged)
    fix = " | ".join(f.fix for f in flagged if f.fix)
    return _audit_result(check, False, reason, fix, [f.sentence for f in flagged])


def audit_coverage(
    llm: LLM,
    check: Check,
    lesson: Lesson,
    pack: FactPack,
    notes: dict[str, list[str]],
    previous: CheckResult | None = None,
) -> CheckResult:
    body = tx.normalise_for_match(lesson.teaching_text())
    confirmed = {
        point_id: quote
        for point_id, quote in (previous.covered_quotes if previous else {}).items()
        if quote_in_lesson(quote, body)
    }
    remaining = [p for p in pack.key_points if p.id not in confirmed]

    findings: dict[str, CoverageFinding] = {}
    if remaining:
        points_text = "\n".join(f"[{k.id}] {k.text}" for k in remaining)
        user = join_blocks(
            _notes_block([check], notes), tag("key_points", points_text), lesson_block(lesson)
        )
        audit = llm.structured("judge", CoverageAudit, load_prompt("coverage_audit"), user)
        findings = {p.key_point_id: p for p in audit.points}

    gaps: list[str] = []
    for point in remaining:
        finding = findings.get(point.id)
        if finding is None:
            gaps.append(f"{point.id} ({point.text}): no finding was returned.")
        elif not finding.covered:
            gaps.append(f"{point.id} ({point.text}): {finding.explanation}")
        elif not quote_in_lesson(finding.quote, body):
            gaps.append(f"{point.id} ({point.text}): its quote is not in the lesson sections.")
        else:
            confirmed[point.id] = finding.quote

    if gaps:
        result = _audit_result(
            check, False, " | ".join(gaps), "Teach each listed key point in the lesson body."
        )
    else:
        result = _audit_result(check, True, f"All {len(pack.key_points)} key points are taught.")
    return result.model_copy(update={"covered_quotes": confirmed})


def _audit_result(
    check: Check,
    passed: bool,
    reason: str,
    fix: str = "",
    evidence: list[str] | None = None,
    evidence_verified: bool = True,
) -> CheckResult:
    return CheckResult(
        check_id=check.id,
        dimension=check.dimension,
        passed=passed,
        reason=reason,
        fix=fix,
        evidence=evidence or [],
        evidence_verified=evidence_verified,
        source="audit",
    )
