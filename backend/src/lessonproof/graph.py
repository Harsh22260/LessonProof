"""The LangGraph workflow: plan, write, then evaluate and revise until pass or out of retries."""

from __future__ import annotations

import logging
import operator
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from lessonproof.agents.authoring import (
    apply_patch,
    create_plan,
    describe_revision,
    research_topic,
    revise_lesson,
    tidy_lesson,
    write_extras,
    write_section,
)
from lessonproof.agents.evolver import evolve
from lessonproof.config import Settings
from lessonproof.evaluation.deterministic import (
    run_deterministic_checks,
    section_rule_failures,
)
from lessonproof.evaluation.evaluator import Baseline, Evaluator
from lessonproof.knowledge import find_curated_pack
from lessonproof.llm import LLM, LLMError
from lessonproof.memory import MemoryStore
from lessonproof.reporting import write_run_outputs
from lessonproof.rubric import Rubric, load_rubric
from lessonproof.schemas import (
    AttemptRecord,
    CheckResult,
    EvaluationReport,
    FactPack,
    Lesson,
    LessonPlan,
    RevisionRecord,
    Section,
    SectionRole,
    best_attempt,
)
from lessonproof.text import split_long_paragraphs

logger = logging.getLogger(__name__)

EventSink = Callable[[dict], None]

SECTION_ORDER = (
    SectionRole.INTRO,
    SectionRole.WHAT,
    SectionRole.WHY,
    SectionRole.HOW,
    SectionRole.EXAMPLE,
    SectionRole.LIMITS,
    SectionRole.RECAP,
)
SECTION_RULES = ("ACC-3", "ACC-4", "LANG-4")


class RunState(TypedDict, total=False):
    run_id: str
    topic: str
    pack: FactPack
    guidelines: list[str]
    judge_notes: dict[str, list[str]]
    plan: LessonPlan
    lesson: Lesson
    pending_revision: RevisionRecord | None
    code_fixes: list[str]
    repaired_rule_failures: list[CheckResult]
    attempts: Annotated[list[AttemptRecord], operator.add]
    status: str
    run_dir: Path
    evolution_events: list[str]


@dataclass
class Deps:
    llm: LLM
    store: MemoryStore
    rubric: Rubric
    settings: Settings
    on_event: EventSink


def build_graph(deps: Deps):
    def emit(event: str, **fields) -> None:
        deps.on_event({"event": event, **fields})

    def timed(name: str, fn):
        @wraps(fn)
        def wrapper(state: RunState) -> dict:
            emit("step_started", step=name)
            started = time.perf_counter()
            update = fn(state)
            seconds = round(time.perf_counter() - started, 1)
            logger.info("%s finished in %.1fs", name, seconds)
            emit("step_finished", step=name, seconds=seconds)
            return update

        return wrapper

    def self_check(
        lesson: Lesson, state: RunState
    ) -> tuple[Lesson, list[str], list[CheckResult]]:
        """Tidies a draft, then gives the author one repair if a rule check fails.

        Rule failures are measurable, so they are settled here. That keeps the limited retries
        for feedback from the judges. A repair is kept only if it reduces rule failures.
        """
        tidy, fixes = tidy_lesson(lesson, deps.rubric, state["pack"])
        failures = [
            r for r in run_deterministic_checks(tidy, state["pack"], deps.rubric) if not r.passed
        ]
        if not failures:
            return tidy, fixes, []
        patch = revise_lesson(
            deps.llm, tidy, failures, state["pack"], deps.rubric, state["guidelines"]
        )
        repaired, more_fixes = tidy_lesson(apply_patch(tidy, patch), deps.rubric, state["pack"])
        remaining = [
            r
            for r in run_deterministic_checks(repaired, state["pack"], deps.rubric)
            if not r.passed
        ]
        if len(remaining) < len(failures):
            return repaired, fixes + more_fixes, failures
        return tidy, fixes, failures

    def load_context(state: RunState) -> dict:
        pack = find_curated_pack(state["topic"]) or research_topic(deps.llm, state["topic"])
        limit = deps.settings.max_active_guidelines
        guidelines = [g.text for g in deps.store.active_guidelines(limit)]
        emit("context", grounding=pack.provenance, guidelines=guidelines)
        return {
            "pack": pack,
            "guidelines": guidelines,
            "judge_notes": deps.store.active_notes_by_check(),
        }

    def plan(state: RunState) -> dict:
        return {
            "plan": create_plan(
                deps.llm, state["topic"], state["pack"], deps.rubric, state["guidelines"]
            )
        }

    def write_one_section(role: SectionRole, state: RunState) -> Section:
        def draft(problems: list[CheckResult] | None = None) -> Section:
            result = write_section(
                deps.llm,
                role,
                state["topic"],
                state["pack"],
                state["plan"],
                deps.rubric,
                state["guidelines"],
                problems,
            )
            limit = deps.rubric.get("LANG-4").params["max_paragraph_sentences"]
            body, _ = split_long_paragraphs(result.body, limit)
            planned = next((s for s in state["plan"].sections if s.role == role), None)
            heading = planned.heading if planned and planned.heading else result.heading
            return Section(role=role, heading=heading, body=body)

        section = draft()
        problems = section_rule_failures(section, state["pack"], deps.rubric, SECTION_RULES)
        if problems:
            section = draft(problems)
        emit("section_ready", section=section.model_dump(mode="json"))
        return section

    def write(state: RunState) -> dict:
        """Writes every section at once and shows each one as soon as it clears its rule checks."""
        with ThreadPoolExecutor(max_workers=deps.settings.section_concurrency) as pool:
            futures = [pool.submit(write_one_section, role, state) for role in SECTION_ORDER]
            sections = [future.result() for future in futures]
        extras = write_extras(
            deps.llm,
            state["plan"].title or state["topic"],
            sections,
            state["pack"],
            state["guidelines"],
        )
        lesson = Lesson(
            title=state["plan"].title or state["topic"],
            sections=sections,
            key_terms=extras.key_terms,
            quiz=extras.quiz,
        )
        checked, fixes, repaired = self_check(lesson, state)
        emit("draft_ready", lesson=checked.model_dump(mode="json"))
        return {
            "lesson": checked,
            "pending_revision": None,
            "code_fixes": fixes,
            "repaired_rule_failures": repaired,
        }

    def evaluate(state: RunState) -> dict:
        attempts = state.get("attempts", [])
        number = len(attempts) + 1
        evaluator = Evaluator(
            deps.llm,
            deps.rubric,
            state["judge_notes"],
            deps.settings.judge_concurrency,
            on_results=lambda results: emit(
                "checks_done",
                attempt=number,
                results=[r.model_dump(mode="json") for r in results],
            ),
        )
        judged = [a for a in attempts if a.report.complete]
        baseline = Baseline(judged[-1].lesson, judged[-1].report) if judged else None
        started = time.perf_counter()
        # Judges must see a draft while a retry remains to act on their feedback.
        gate = number != deps.settings.max_retries
        report = evaluator.evaluate(
            state["lesson"], state["pack"], number, baseline=baseline, gate=gate
        )
        logger.info(
            "Attempt %d: %d/%d checks passed. Failed: %s",
            number,
            report.pass_count,
            len(report.results),
            [f.check_id for f in report.failures] or "none",
        )
        record = AttemptRecord(
            attempt=number,
            lesson=state["lesson"],
            report=report,
            revision=state.get("pending_revision"),
            seconds=round(time.perf_counter() - started, 1),
            code_fixes=state.get("code_fixes", []),
            repaired_rule_failures=state.get("repaired_rule_failures", []),
        )
        emit("attempt", record=record.model_dump(mode="json"))
        return {"attempts": [record]}

    def revise(state: RunState) -> dict:
        attempts = state["attempts"]
        base = best_attempt(attempts)
        patch = revise_lesson(
            deps.llm,
            base.lesson,
            base.report.failures,
            state["pack"],
            deps.rubric,
            state["guidelines"],
        )
        if apply_patch(base.lesson, patch).fingerprint() == base.lesson.fingerprint():
            logger.info("The reviser changed nothing, so it gets one more request")
            patch = revise_lesson(
                deps.llm,
                base.lesson,
                base.report.failures,
                state["pack"],
                deps.rubric,
                [*state["guidelines"], "Your last revision changed nothing. Rewrite the text."],
            )
        revised, fixes, repaired = self_check(apply_patch(base.lesson, patch), state)
        emit("draft_ready", lesson=revised.model_dump(mode="json"))
        record = describe_revision(
            base.lesson, revised, patch, base.attempt, base.attempt != attempts[-1].attempt
        )
        return {
            "lesson": revised,
            "pending_revision": record,
            "code_fixes": fixes,
            "repaired_rule_failures": repaired,
        }

    def route(state: RunState) -> str:
        attempts = state["attempts"]
        if attempts[-1].report.passed:
            return "finalize"
        return "revise" if len(attempts) <= deps.settings.max_retries else "finalize"

    def finalize(state: RunState) -> dict:
        attempts = state["attempts"]
        status = "shipped" if attempts[-1].report.passed else "rejected"
        # Attempt 0 keeps pre-repair failures in memory, so the system still learns from them.
        raw_draft = EvaluationReport(
            attempt=0,
            lesson_fingerprint=attempts[0].report.lesson_fingerprint,
            rubric_version=deps.rubric.version,
            results=attempts[0].repaired_rule_failures,
            complete=False,
        )
        deps.store.record_run(
            state["run_id"],
            state["topic"],
            status,
            [raw_draft, *(a.report for a in attempts)],
            deps.rubric.version,
            deps.llm.usage(),
        )
        run_dir = save_outputs(state, status, [])
        emit("lesson_ready", run_id=state["run_id"], run_dir=str(run_dir))
        return {"status": status, "run_dir": run_dir}

    def save_outputs(state: RunState, status: str, events: list[str]) -> Path:
        return write_run_outputs(
            deps.settings.output_dir,
            state["run_id"],
            state["topic"],
            status,
            state["attempts"],
            state["pack"],
            state["guidelines"],
            events,
            deps.llm.usage(),
            deps.rubric.version,
        )

    def learn(state: RunState) -> dict:
        events = evolve(deps.llm, deps.store, deps.rubric, deps.settings)
        if events:
            save_outputs(state, state["status"], events)
        return {"evolution_events": events}

    graph = StateGraph(RunState)
    graph.add_node("load_context", timed("load_context", load_context))
    graph.add_node("plan_lesson", timed("plan_lesson", plan))
    graph.add_node("write_lesson", timed("write_lesson", write))
    graph.add_node("evaluate_lesson", timed("evaluate_lesson", evaluate))
    graph.add_node("revise_lesson", timed("revise_lesson", revise))
    graph.add_node("finalize_run", timed("finalize_run", finalize))
    graph.add_node("learn", timed("learn", learn))

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "plan_lesson")
    graph.add_edge("plan_lesson", "write_lesson")
    graph.add_edge("write_lesson", "evaluate_lesson")
    graph.add_conditional_edges(
        "evaluate_lesson", route, {"revise": "revise_lesson", "finalize": "finalize_run"}
    )
    graph.add_edge("revise_lesson", "evaluate_lesson")
    graph.add_edge("finalize_run", "learn")
    graph.add_edge("learn", END)
    return graph.compile()


@dataclass
class RunResult:
    run_id: str
    status: str
    attempts: list[AttemptRecord]
    run_dir: Path
    evolution_events: list[str]
    usage: dict
    seconds: float


def new_run_id() -> str:
    return f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"


def run_pipeline(
    topic: str,
    llm: LLM,
    store: MemoryStore,
    settings: Settings,
    on_event: EventSink | None = None,
) -> RunResult:
    rubric = load_rubric()
    run_id = new_run_id()
    sink = on_event or (lambda _event: None)
    graph = build_graph(
        Deps(llm=llm, store=store, rubric=rubric, settings=settings, on_event=sink)
    )
    started = time.perf_counter()
    try:
        state = graph.invoke({"run_id": run_id, "topic": topic, "attempts": []})
    except LLMError:
        store.record_run(run_id, topic, "error", [], rubric.version, llm.usage())
        raise
    return RunResult(
        run_id=run_id,
        status=state["status"],
        attempts=state["attempts"],
        run_dir=state["run_dir"],
        evolution_events=state["evolution_events"],
        usage=llm.usage(),
        seconds=round(time.perf_counter() - started, 1),
    )
