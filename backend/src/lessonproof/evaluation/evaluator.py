"""Runs the rubric against a lesson, in the cheapest safe order, and returns a hard verdict.

Rule-based checks run first. If one fails, the draft is already rejected, so the paid judges are
skipped. On a retry, a judge group is re-run only if the text it depends on has changed.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from lessonproof.evaluation.deterministic import run_deterministic_checks
from lessonproof.evaluation.judges import audit_claims, audit_coverage, judge_group
from lessonproof.llm import LLM
from lessonproof.rubric import Check, Rubric
from lessonproof.schemas import CheckResult, EvaluationReport, FactPack, Lesson, SectionRole

EXAMPLE_ROLES = (SectionRole.WHAT, SectionRole.WHY, SectionRole.HOW, SectionRole.EXAMPLE)


def _sections_text(lesson: Lesson, roles: tuple[SectionRole, ...]) -> str:
    return "\n".join(s.body for s in lesson.sections if s.role in roles)


GROUP_SCOPES: dict[str, Callable[[Lesson], str]] = {
    "beginner_language": Lesson.teaching_text,
    "examples": lambda lesson: _sections_text(lesson, EXAMPLE_ROLES),
    "clarity": Lesson.teaching_text,
    "flow": Lesson.to_markdown,
}


@dataclass
class Baseline:
    """An earlier, fully judged draft whose verdicts can be reused for unchanged text."""

    lesson: Lesson
    report: EvaluationReport

    def result(self, check_id: str) -> CheckResult:
        return next(r for r in self.report.results if r.check_id == check_id)


class Evaluator:
    def __init__(
        self,
        llm: LLM,
        rubric: Rubric,
        judge_notes: dict[str, list[str]] | None = None,
        concurrency: int = 6,
        on_results: Callable[[list[CheckResult]], None] | None = None,
    ) -> None:
        self._llm = llm
        self._rubric = rubric
        self._notes = judge_notes or {}
        self._concurrency = concurrency
        self._on_results = on_results or (lambda _results: None)

    def evaluate(
        self,
        lesson: Lesson,
        pack: FactPack,
        attempt: int = 1,
        only: set[str] | None = None,
        baseline: Baseline | None = None,
        gate: bool = False,
    ) -> EvaluationReport:
        """Runs the rubric. `only` limits it to named checks; `gate` stops on a rule failure."""
        results = run_deterministic_checks(lesson, pack, self._rubric)
        if only is not None:
            results = [r for r in results if r.check_id in only]
        self._on_results(results)

        gated = gate and any(not r.passed for r in results)
        reused: list[str] = []
        if not gated:
            results += self._run_llm_checks(lesson, pack, only, baseline, reused)

        order = {check.id: i for i, check in enumerate(self._rubric.checks)}
        results.sort(key=lambda r: order[r.check_id])
        return EvaluationReport(
            attempt=attempt,
            lesson_fingerprint=lesson.fingerprint(),
            rubric_version=self._rubric.version,
            results=results,
            complete=not gated,
            reused_checks=reused,
        )

    def _run_llm_checks(
        self,
        lesson: Lesson,
        pack: FactPack,
        only: set[str] | None,
        baseline: Baseline | None,
        reused: list[str],
    ) -> list[CheckResult]:
        def wanted(check_id: str) -> bool:
            return only is None or check_id in only

        groups: dict[str, list[Check]] = defaultdict(list)
        for check in self._rubric.by_kind("judge"):
            if wanted(check.id):
                groups[check.dimension].append(check)

        results: list[CheckResult] = []
        with ThreadPoolExecutor(max_workers=self._concurrency) as pool:
            futures = []
            for dimension, checks in groups.items():
                if baseline and self._scope_unchanged(dimension, lesson, baseline):
                    kept = [baseline.result(c.id) for c in checks]
                    self._on_results(kept)
                    results += kept
                    reused += [c.id for c in checks]
                else:
                    futures.append(
                        pool.submit(
                            self._reporting(judge_group), self._llm, checks, lesson, self._notes
                        )
                    )

            if wanted("ACC-1") or wanted("ACC-2"):
                c1, c2 = self._rubric.get("ACC-1"), self._rubric.get("ACC-2")
                previous = {c.id: baseline.result(c.id) for c in (c1, c2)} if baseline else None
                futures.append(
                    pool.submit(
                        self._reporting(audit_claims),
                        self._llm,
                        c1,
                        c2,
                        lesson,
                        pack,
                        self._notes,
                        baseline.lesson if baseline else None,
                        previous,
                    )
                )
            coverage = None
            if wanted("COV-1"):
                coverage = pool.submit(
                    self._reporting(audit_coverage),
                    self._llm,
                    self._rubric.get("COV-1"),
                    lesson,
                    pack,
                    self._notes,
                    baseline.result("COV-1") if baseline else None,
                )
            results += [result for future in futures for result in future.result()]
            if coverage:
                results.append(coverage.result())
        return results

    def _reporting(self, check_fn):
        def run(*args):
            outcome = check_fn(*args)
            self._on_results(outcome if isinstance(outcome, list) else [outcome])
            return outcome

        return run

    @staticmethod
    def _scope_unchanged(dimension: str, lesson: Lesson, baseline: Baseline) -> bool:
        scope = GROUP_SCOPES[dimension]
        return scope(lesson) == scope(baseline.lesson)
