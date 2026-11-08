"""Self-evolution: turns repeated failures and human feedback into lasting improvements.

Writer guidelines take effect straight away because the evaluator still judges their results.
Judge notes change the bar itself, so they stay candidates until calibration approves them.
The rubric's pass criteria are owned by humans and are never rewritten here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from lessonproof.agents.context import join_blocks, rubric_block, tag
from lessonproof.config import Settings
from lessonproof.llm import LLM
from lessonproof.memory import MemoryStore
from lessonproof.prompts import load_prompt
from lessonproof.rubric import Rubric

MAX_REASONS_SHOWN = 5


class GuidelineProposal(BaseModel):
    text: str


class FeedbackRouting(BaseModel):
    target: Literal["writer", "evaluator"]
    check_id: str
    text: str


def evolve(llm: LLM, store: MemoryStore, rubric: Rubric, settings: Settings) -> list[str]:
    events = _learn_from_failures(llm, store, rubric, settings)
    events += _learn_from_feedback(llm, store, rubric)
    return events


def _learn_from_failures(
    llm: LLM, store: MemoryStore, rubric: Rubric, settings: Settings
) -> list[str]:
    events: list[str] = []
    threshold = settings.evolve_failure_threshold
    active = {g.check_id: g for g in store.active_guidelines()}

    for check_id, stats in store.first_attempt_stats(settings.evolve_window_runs).items():
        if stats.failures < threshold:
            continue
        current = active.get(check_id)
        if current:
            failures_since, _ = store.first_attempt_rate(check_id, current.after_run_seq)
            if failures_since < threshold:
                continue

        user = join_blocks(
            tag("check", f"{check_id}: {rubric.get(check_id).criterion}"),
            tag("failure_reasons", "\n".join(stats.reasons[-MAX_REASONS_SHOWN:])),
            tag("previous_guideline", current.text) if current else "",
        )
        proposal = llm.structured("writer", GuidelineProposal, load_prompt("evolver"), user)
        if current:
            store.retire_guideline(current.id)
        store.add_guideline(check_id, proposal.text, "repeated_failure")
        verb = "Replaced ineffective" if current else "Added"
        events.append(
            f"{verb} guideline for {check_id} "
            f"({stats.failures}/{stats.runs} first-draft failures): {proposal.text}"
        )
    return events


def _learn_from_feedback(llm: LLM, store: MemoryStore, rubric: Rubric) -> list[str]:
    events: list[str] = []
    for item in store.pending_feedback():
        user = join_blocks(rubric_block(rubric), tag("human_feedback", item.text))
        routed = llm.structured("writer", FeedbackRouting, load_prompt("feedback_router"), user)
        if routed.check_id not in rubric.ids():
            events.append(f"Ignored feedback {item.id}: unknown check '{routed.check_id}'.")
        elif routed.target == "writer":
            store.add_guideline(routed.check_id, routed.text, "human_feedback")
            events.append(f"Feedback became a writer guideline ({routed.check_id}): {routed.text}")
        else:
            store.add_judge_note(routed.check_id, routed.text, "human_feedback")
            events.append(
                f"Feedback became a candidate judge note ({routed.check_id}): {routed.text}"
            )
        store.mark_feedback_processed(item.id)
    return events
