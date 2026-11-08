"""Command-line interface."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import typer
import uvicorn
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from lessonproof.benchmarks.defects import DEFECTS, get_defect
from lessonproof.benchmarks.suite import (
    propose_notes_for_misses,
    review_candidate_notes,
    run_benchmark,
    run_calibration,
    run_stability,
)
from lessonproof.config import ENV_FILE, PROJECT_ROOT, Settings
from lessonproof.evaluation.evaluator import Evaluator
from lessonproof.graph import run_pipeline
from lessonproof.knowledge import find_curated_pack
from lessonproof.llm import LangChainLLM, LLMError
from lessonproof.memory import MemoryStore
from lessonproof.rubric import load_rubric
from lessonproof.schemas import EvaluationReport, Lesson

app = typer.Typer(add_completion=False, help="Self-evaluating lesson generator.")
console = Console()

DEFAULT_TOPIC = "Introduction to RAG (Retrieval-Augmented Generation)"
DEFAULT_LESSON = PROJECT_ROOT / "outputs" / "latest" / "lesson.json"


@app.callback()
def setup(verbose: bool = typer.Option(False, "--verbose", "-v", help="Show progress logs.")):
    load_dotenv(ENV_FILE)
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    logging.getLogger("lessonproof").setLevel(logging.INFO)
    for noisy in ("httpx", "google_genai", "langchain_google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _store(settings: Settings) -> MemoryStore:
    return MemoryStore(settings.memory_path)


def _load_lesson(path: Path) -> Lesson:
    if not path.exists():
        raise typer.BadParameter(f"{path} does not exist. Run `lessonproof run` first.")
    return Lesson.model_validate_json(path.read_text(encoding="utf-8"))


def _load_pack(topic: str):
    pack = find_curated_pack(topic)
    if pack is None:
        raise typer.BadParameter(f"No curated fact pack matches '{topic}'.")
    return pack


def _print_report(report: EvaluationReport) -> None:
    table = Table(title=f"Attempt {report.attempt}: {report.pass_count}/{len(report.results)}")
    table.add_column("Check")
    table.add_column("Result")
    table.add_column("Reason", overflow="fold")
    for result in report.results:
        label = "[green]PASS[/green]" if result.passed else "[red]FAIL[/red]"
        table.add_row(result.check_id, label, result.reason)
    console.print(table)


def _save_evaluation(settings: Settings, name: str, payload: dict) -> Path:
    folder = settings.output_dir / "evaluations"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


@app.command()
def run(topic: str = typer.Argument(DEFAULT_TOPIC, help="The lesson topic.")) -> None:
    """Generate, evaluate, and regenerate a lesson until it passes or retries run out."""
    settings = Settings()
    try:
        result = run_pipeline(topic, LangChainLLM(settings), _store(settings), settings)
    except LLMError as error:
        console.print(f"[red]Run stopped, nothing was shipped:[/red] {error}")
        raise typer.Exit(code=2) from error

    for attempt in result.attempts:
        _print_report(attempt.report)
    for event in result.evolution_events:
        console.print(f"[cyan]Learned:[/cyan] {event}")
    color = "green" if result.status == "shipped" else "red"
    console.print(f"[{color}]{result.status.upper()}[/{color}] after {len(result.attempts)} "
                  f"attempt(s) in {result.seconds}s. Outputs: {result.run_dir}")
    console.print(f"Usage: {result.usage}")
    if result.status != "shipped":
        raise typer.Exit(code=1)


@app.command()
def evaluate(
    lesson_path: Path = typer.Option(DEFAULT_LESSON, "--lesson", help="Lesson JSON file."),
    topic: str = typer.Option(DEFAULT_TOPIC, help="Topic with a curated fact pack."),
) -> None:
    """Run the full rubric against an existing lesson."""
    settings = Settings()
    store = _store(settings)
    evaluator = Evaluator(
        LangChainLLM(settings),
        load_rubric(),
        store.active_notes_by_check(),
        settings.judge_concurrency,
    )
    _print_report(evaluator.evaluate(_load_lesson(lesson_path), _load_pack(topic)))


@app.command("inject-error")
def inject_error(
    defect_id: str = typer.Argument("false-claim", help="Which deliberate error to plant."),
    lesson_path: Path = typer.Option(DEFAULT_LESSON, "--lesson", help="Lesson JSON file."),
    topic: str = typer.Option(DEFAULT_TOPIC, help="Topic with a curated fact pack."),
) -> None:
    """Plant a deliberate error in a passing lesson and show that the full rubric catches it."""
    settings = Settings()
    defect = get_defect(defect_id)
    store = _store(settings)
    console.print(f"Planted error: [yellow]{defect.description}[/yellow]")
    console.print(f"This must fail check: [yellow]{defect.expected_check}[/yellow]\n")
    evaluator = Evaluator(
        LangChainLLM(settings),
        load_rubric(),
        store.active_notes_by_check(),
        settings.judge_concurrency,
    )
    report = evaluator.evaluate(defect.apply(_load_lesson(lesson_path)), _load_pack(topic))
    _print_report(report)
    caught = defect.expected_check in {f.check_id for f in report.failures}
    console.print("[green]CAUGHT[/green]" if caught else "[red]MISSED[/red]")
    if not caught:
        raise typer.Exit(code=1)


@app.command("list-errors")
def list_errors() -> None:
    """List the deliberate errors that can be planted."""
    for defect in DEFECTS:
        console.print(f"{defect.id:22} {defect.expected_check:8} {defect.description}")


@app.command()
def calibrate(
    lesson_path: Path = typer.Option(DEFAULT_LESSON, "--lesson", help="A lesson that passes."),
    topic: str = typer.Option(DEFAULT_TOPIC, help="Topic with a curated fact pack."),
    sharpen: bool = typer.Option(
        False, help="Propose judge notes for misses, and approve them only if they do no harm."
    ),
) -> None:
    """Measure how many planted errors the evaluator catches, and any false rejections."""
    settings = Settings()
    llm, store, rubric = LangChainLLM(settings), _store(settings), load_rubric()
    lesson, pack = _load_lesson(lesson_path), _load_pack(topic)
    result = run_calibration(
        llm, rubric, lesson, pack, store.active_notes_by_check(), settings.judge_concurrency
    )

    table = Table(title=f"Caught {result.caught}/{len(result.outcomes)} planted errors")
    table.add_column("Planted error")
    table.add_column("Target")
    table.add_column("Result")
    for outcome in result.outcomes:
        label = "[green]caught[/green]" if outcome.caught else "[red]MISSED[/red]"
        table.add_row(outcome.defect.id, outcome.defect.expected_check, label)
    console.print(table)
    console.print(f"False rejections of the clean lesson: {result.clean_failures or 'none'}")

    review: list[str] = []
    if sharpen:
        for created in propose_notes_for_misses(llm, store, rubric, result):
            console.print(f"[cyan]Candidate note:[/cyan] {created}")
        review, trial = review_candidate_notes(
            llm, store, rubric, lesson, pack, result, settings.judge_concurrency
        )
        for line in review:
            console.print(f"[cyan]Note review:[/cyan] {line}")
        if trial:
            console.print(f"Recall with candidate notes: {trial.caught}/{len(trial.outcomes)}")

    path = _save_evaluation(
        settings,
        "calibration",
        {
            "caught": result.caught,
            "total": len(result.outcomes),
            "recall": result.recall,
            "clean_lesson_failures": result.clean_failures,
            "outcomes": [
                {
                    "defect": o.defect.id,
                    "expected_check": o.defect.expected_check,
                    "caught": o.caught,
                    "reason": o.reason,
                }
                for o in result.outcomes
            ],
            "note_review": review,
            "usage": llm.usage(),
        },
    )
    console.print(f"Saved: {path}. Usage: {llm.usage()}")


@app.command()
def stability(
    repeats: int = typer.Option(3, min=2, help="How many times to judge the same lesson."),
    lesson_path: Path = typer.Option(DEFAULT_LESSON, "--lesson", help="Lesson JSON file."),
    topic: str = typer.Option(DEFAULT_TOPIC, help="Topic with a curated fact pack."),
) -> None:
    """Judge one unchanged lesson several times and report checks that change their verdict."""
    settings = Settings()
    llm, store = LangChainLLM(settings), _store(settings)
    result = run_stability(
        llm,
        load_rubric(),
        _load_lesson(lesson_path),
        _load_pack(topic),
        store.active_notes_by_check(),
        repeats,
        settings.judge_concurrency,
    )
    for number, failures in enumerate(result.failures_per_repeat, start=1):
        console.print(f"Repeat {number}: failed {failures or 'nothing'}")
    console.print(f"Unstable checks: {result.flip_counts or 'none'}")
    console.print(f"Agreement across LLM checks: {result.agreement:.0%}")
    path = _save_evaluation(
        settings,
        "stability",
        {
            "repeats": repeats,
            "failures_per_repeat": result.failures_per_repeat,
            "unstable_checks": result.flip_counts,
            "agreement": result.agreement,
            "usage": llm.usage(),
        },
    )
    console.print(f"Saved: {path}. Usage: {llm.usage()}")


@app.command()
def benchmark(
    runs: int = typer.Option(3, min=1, help="How many full runs to perform."),
    topic: str = typer.Option(DEFAULT_TOPIC, help="The lesson topic."),
) -> None:
    """Run the whole pipeline repeatedly, sharing memory, to measure learning across runs."""
    settings = Settings()
    rows = run_benchmark(
        topic, lambda: LangChainLLM(settings), _store(settings), settings, runs
    )
    table = Table(title="Benchmark")
    columns = ("Run", "Status", "Attempts", "First-draft failures", "Tokens", "Seconds", "Learned")
    for column in columns:
        table.add_column(column, overflow="fold")
    for row in rows:
        table.add_row(
            str(row["run"]),
            row["status"],
            str(row["attempts"]),
            ", ".join(row["first_draft_failures"]) or "none",
            str(row["tokens"]),
            str(row["seconds"]),
            str(row["new_learnings"]),
        )
    console.print(table)
    console.print(f"Saved: {_save_evaluation(settings, 'benchmark', {'runs': rows})}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Address to bind."),
    port: int = typer.Option(8000, help="Port to bind."),
) -> None:
    """Start the web frontend."""
    uvicorn.run("lessonproof.api.app:create_app", factory=True, host=host, port=port)


@app.command()
def feedback(run_id: str, text: str) -> None:
    """Leave human feedback on a run. The next run learns from it."""
    _store(Settings()).add_feedback(run_id, text)
    console.print("Saved. The next run will learn from this feedback.")


@app.command()
def memory() -> None:
    """Show past runs and everything the system has learned."""
    store = _store(Settings())
    runs = Table(title="Runs")
    for column in ("#", "Run", "Status", "Attempts", "First-draft failures"):
        runs.add_column(column)
    for row in store.run_history():
        runs.add_row(
            str(row["seq"]),
            row["run_id"],
            row["status"],
            str(row["attempts"]),
            str(row["first_draft_failures"]),
        )
    console.print(runs)

    guidelines = Table(title="Active writer guidelines")
    for column in ("Check", "Origin", "Fail rate before", "Fail rate after", "Guideline"):
        guidelines.add_column(column, overflow="fold")
    for item in store.active_guidelines():
        before = store.first_attempt_rate(item.check_id, 0, item.after_run_seq)
        after = store.first_attempt_rate(item.check_id, item.after_run_seq)
        guidelines.add_row(
            item.check_id,
            item.origin,
            f"{before[0]}/{before[1]}",
            f"{after[0]}/{after[1]}",
            item.text,
        )
    console.print(guidelines)

    notes = Table(title="Judge notes")
    for column in ("Check", "Status", "Origin", "Note"):
        notes.add_column(column, overflow="fold")
    for status in ("active", "candidate", "retired"):
        for note in store.judge_notes(status):
            notes.add_row(note.check_id, note.status, note.origin, note.text)
    console.print(notes)


def main() -> None:
    try:
        app()
    except LLMError as error:
        console.print(f"[red]Stopped, nothing was shipped:[/red] {str(error)[:300]}")
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
