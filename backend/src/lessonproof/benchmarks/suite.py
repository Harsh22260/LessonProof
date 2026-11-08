"""Evaluates the evaluator: can it catch planted errors, and is it consistent?"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from pydantic import BaseModel

from lessonproof.agents.context import join_blocks, tag
from lessonproof.benchmarks.defects import DEFECTS, Defect
from lessonproof.config import Settings
from lessonproof.evaluation.evaluator import Evaluator
from lessonproof.graph import run_pipeline
from lessonproof.llm import LLM
from lessonproof.memory import MemoryStore
from lessonproof.prompts import load_prompt
from lessonproof.rubric import Rubric
from lessonproof.schemas import FactPack, Lesson


class SharpeningNote(BaseModel):
    text: str


@dataclass
class DefectOutcome:
    defect: Defect
    caught: bool
    reason: str


@dataclass
class CalibrationResult:
    outcomes: list[DefectOutcome]
    clean_failures: list[str]

    @property
    def caught(self) -> int:
        return sum(o.caught for o in self.outcomes)

    @property
    def recall(self) -> float:
        return self.caught / len(self.outcomes) if self.outcomes else 0.0

    @property
    def missed(self) -> list[DefectOutcome]:
        return [o for o in self.outcomes if not o.caught]


def run_calibration(
    llm: LLM,
    rubric: Rubric,
    lesson: Lesson,
    pack: FactPack,
    notes: dict[str, list[str]],
    concurrency: int,
) -> CalibrationResult:
    """Runs only the check each defect targets, which keeps the suite cheap enough to repeat."""
    evaluator = Evaluator(llm, rubric, notes, concurrency)
    clean = evaluator.evaluate(lesson, pack)
    outcomes = []
    for defect in DEFECTS:
        corrupted = defect.apply(lesson)
        report = evaluator.evaluate(corrupted, pack, only={defect.expected_check})
        result = report.results[0]
        outcomes.append(DefectOutcome(defect, not result.passed, result.reason))
    return CalibrationResult(outcomes, [f.check_id for f in clean.failures])


def propose_notes_for_misses(
    llm: LLM, store: MemoryStore, rubric: Rubric, result: CalibrationResult
) -> list[str]:
    created = []
    for outcome in result.missed:
        if rubric.get(outcome.defect.expected_check).kind == "deterministic":
            continue
        user = join_blocks(
            tag("check", rubric.get(outcome.defect.expected_check).criterion),
            tag("planted_error", outcome.defect.description),
            tag("judge_reason_for_passing", outcome.reason),
        )
        note = llm.structured(
            "judge", SharpeningNote, load_prompt("calibration_sharpener"), user
        )
        store.add_judge_note(outcome.defect.expected_check, note.text, "calibration_miss")
        created.append(f"{outcome.defect.expected_check}: {note.text}")
    return created


def review_candidate_notes(
    llm: LLM,
    store: MemoryStore,
    rubric: Rubric,
    lesson: Lesson,
    pack: FactPack,
    baseline: CalibrationResult,
    concurrency: int,
) -> tuple[list[str], CalibrationResult | None]:
    """Promotes candidates only if recall does not drop and no new false rejection appears."""
    candidates = store.judge_notes("candidate")
    if not candidates:
        return [], None

    trial_notes = store.active_notes_by_check()
    for note in candidates:
        trial_notes.setdefault(note.check_id, []).append(note.text)
    trial = run_calibration(llm, rubric, lesson, pack, trial_notes, concurrency)

    no_lost_recall = trial.caught >= baseline.caught
    no_new_rejections = set(trial.clean_failures) <= set(baseline.clean_failures)
    approved = no_lost_recall and no_new_rejections
    status = "active" if approved else "retired"
    store.set_judge_note_status([n.id for n in candidates], status)
    return [f"{status}: {n.check_id}: {n.text}" for n in candidates], trial


@dataclass
class StabilityResult:
    repeats: int
    failures_per_repeat: list[list[str]]
    flip_counts: dict[str, int] = field(default_factory=dict)
    verdict_changes: int = 0
    total_verdicts: int = 0

    @property
    def agreement(self) -> float:
        total = self.total_verdicts
        return 1 - (self.verdict_changes / total) if total else 1.0


def run_stability(
    llm: LLM,
    rubric: Rubric,
    lesson: Lesson,
    pack: FactPack,
    notes: dict[str, list[str]],
    repeats: int,
    concurrency: int,
) -> StabilityResult:
    """Evaluates one unchanged lesson several times and counts checks that change their verdict."""
    evaluator = Evaluator(llm, rubric, notes, concurrency)
    failures = [
        [f.check_id for f in evaluator.evaluate(lesson, pack).failures] for _ in range(repeats)
    ]
    fail_counts = Counter(check_id for run in failures for check_id in run)
    unstable = {c: n for c, n in fail_counts.items() if 0 < n < repeats}
    llm_check_count = sum(1 for c in rubric.checks if c.kind != "deterministic")
    return StabilityResult(
        repeats=repeats,
        failures_per_repeat=failures,
        flip_counts=unstable,
        verdict_changes=len(unstable),
        total_verdicts=llm_check_count,
    )


def run_benchmark(
    topic: str, make_llm, store: MemoryStore, settings: Settings, runs: int
) -> list[dict]:
    rows = []
    for number in range(1, runs + 1):
        llm = make_llm()
        result = run_pipeline(topic, llm, store, settings)
        tokens = sum(u["input_tokens"] + u["output_tokens"] for u in result.usage.values())
        rows.append(
            {
                "run": number,
                "run_id": result.run_id,
                "status": result.status,
                "attempts": len(result.attempts),
                "first_draft_failures": sorted(
                    {f.check_id for f in result.attempts[0].repaired_rule_failures}
                    | {f.check_id for f in result.attempts[0].report.failures}
                ),
                "tokens": tokens,
                "seconds": result.seconds,
                "new_learnings": len(result.evolution_events),
            }
        )
    return rows
