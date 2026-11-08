"""Writes the deliverables of a run: the lesson, the rejection log, and a machine-readable trace."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from lessonproof.schemas import AttemptRecord, CheckResult, FactPack, best_attempt

UNVERIFIED_WARNING = (
    "> **Grounding warning:** no curated fact pack exists for this topic. The facts were produced "
    "by the model itself and have not been verified by a human.\n\n"
)
REJECTED_WARNING = (
    "> **NOT APPROVED.** This draft failed the rubric after all retries and must not reach "
    "learners without human review.\n\n"
)


def _clean(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _failure_row(failure: CheckResult) -> str:
    evidence = "; ".join(f"`{_clean(e)[:160]}`" for e in failure.evidence) or "-"
    verified = "" if failure.evidence_verified else " *(evidence unverified)*"
    return (
        f"| {failure.check_id} | {failure.dimension} | {_clean(failure.reason)}{verified} "
        f"| {evidence} | {_clean(failure.fix) or '-'} |"
    )


def _retry_changes(attempt: AttemptRecord, previous: AttemptRecord | None) -> list[str]:
    revision = attempt.revision
    if revision is None:
        return []
    lines = ["**What changed on this retry**", ""]
    if revision.rolled_back:
        lines.append(
            f"- The previous draft scored lower, so this retry restarted from attempt "
            f"{revision.base_attempt}."
        )
    sections = ", ".join(revision.sections_changed) or "none"
    lines += [
        f"- Sections rewritten: {sections}",
        f"- Key words changed: {'yes' if revision.key_terms_changed else 'no'}; "
        f"quiz changed: {'yes' if revision.quiz_changed else 'no'}",
        f"- Words added: {revision.words_added}; words removed: {revision.words_removed}",
    ]
    if previous:
        before = {f.check_id for f in previous.report.failures}
        after = {f.check_id for f in attempt.report.failures}
        lines.append(f"- Checks fixed: {', '.join(sorted(before - after)) or 'none'}")
        lines.append(f"- New failures: {', '.join(sorted(after - before)) or 'none'}")
    if revision.notes:
        lines += ["", "Reviser's notes:", ""]
        lines += [f"- {note.check_id}: {note.change}" for note in revision.notes]
    return lines + [""]


def render_rejection_log(
    run_id: str,
    topic: str,
    status: str,
    attempts: list[AttemptRecord],
    guidelines: list[str],
    evolution_events: list[str],
    usage: dict,
) -> str:
    lines = [
        f"# Rejection Log: {topic}",
        "",
        f"- Run: `{run_id}`",
        f"- Final status: **{status.upper()}** after {len(attempts)} attempt(s)",
    ]
    for role, entry in sorted(usage.items()):
        lines.append(
            f"- Usage ({role}): {entry['calls']} calls, {entry['input_tokens']} input tokens, "
            f"{entry['output_tokens']} output tokens, models: {entry.get('models', {})}"
        )
    lines.append("")

    if guidelines:
        lines += ["## Guidelines applied from memory", ""]
        lines += [f"- {g}" for g in guidelines] + [""]

    for index, attempt in enumerate(attempts):
        report = attempt.report
        verdict = "PASSED" if report.passed else "REJECTED"
        lines += [
            f"## Attempt {attempt.attempt}: {verdict} "
            f"({report.pass_count}/{len(report.results)} checks run, {attempt.seconds:.0f}s)",
            "",
        ]
        if attempt.code_fixes:
            lines += ["Fixed by code, at no token cost:", ""]
            lines += [*(f"- {fix}" for fix in attempt.code_fixes), ""]
        if attempt.repaired_rule_failures:
            lines += [
                "The author's draft failed these rule checks, and had one repair before judging:",
                "",
                *(f"- {f.check_id}: {f.reason}" for f in attempt.repaired_rule_failures),
                "",
            ]
        if not report.complete:
            lines += ["Rejected by the rule-based checks, so the AI judges were not called.", ""]
        if report.reused_checks:
            reused = ", ".join(report.reused_checks)
            lines += [f"Verdicts reused because their text did not change: {reused}", ""]
        previous = attempts[index - 1] if index else None
        lines += _retry_changes(attempt, previous)
        if report.failures:
            lines += [
                "| Check | Dimension | Why it failed | Evidence | Required fix |",
                "| --- | --- | --- | --- | --- |",
                *(_failure_row(f) for f in report.failures),
                "",
            ]

    if evolution_events:
        lines += ["## What the system learned from this run", ""]
        lines += [f"- {event}" for event in evolution_events] + [""]
    return "\n".join(lines)


def write_run_outputs(
    output_dir: Path,
    run_id: str,
    topic: str,
    status: str,
    attempts: list[AttemptRecord],
    pack: FactPack,
    guidelines: list[str],
    evolution_events: list[str],
    usage: dict,
    rubric_version: int,
) -> Path:
    run_dir = output_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    final = attempts[-1]
    if status == "shipped":
        name, banner = "lesson.md", ""
    else:
        final = best_attempt(attempts)
        name, banner = "rejected_draft.md", REJECTED_WARNING
    if pack.provenance != "curated":
        banner = UNVERIFIED_WARNING + banner
    (run_dir / name).write_text(banner + final.lesson.to_markdown(), encoding="utf-8")
    (run_dir / "lesson.json").write_text(final.lesson.model_dump_json(indent=2), encoding="utf-8")

    log = render_rejection_log(
        run_id, topic, status, attempts, guidelines, evolution_events, usage
    )
    (run_dir / "rejection_log.md").write_text(log, encoding="utf-8")
    trace = {
        "run_id": run_id,
        "topic": topic,
        "status": status,
        "rubric_version": rubric_version,
        "grounding": pack.provenance,
        "guidelines": guidelines,
        "evolution_events": evolution_events,
        "usage": usage,
        "attempts": [a.model_dump(mode="json") for a in attempts],
    }
    (run_dir / "trace.json").write_text(
        json.dumps(trace, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if status == "shipped":
        latest = output_dir / "latest"
        latest.mkdir(parents=True, exist_ok=True)
        for filename in ("lesson.md", "lesson.json", "rejection_log.md"):
            shutil.copyfile(run_dir / filename, latest / filename)
    return run_dir
