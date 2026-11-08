"""HTTP API and static file hosting for the frontend."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterator
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from lessonproof.api.jobs import Job, JobManager
from lessonproof.benchmarks.defects import DEFECTS, get_defect
from lessonproof.config import ENV_FILE, Settings
from lessonproof.evaluation.evaluator import Evaluator
from lessonproof.graph import run_pipeline
from lessonproof.knowledge import find_curated_pack
from lessonproof.llm import LangChainLLM
from lessonproof.memory import MemoryStore
from lessonproof.rubric import load_rubric
from lessonproof.schemas import Lesson

RUN_ID_PATTERN = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$")
HEARTBEAT_SECONDS = 10.0
DEFAULT_TOPIC = "Introduction to RAG (Retrieval-Augmented Generation)"


class RunRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=200)
    regenerate: bool = False


class InjectRequest(BaseModel):
    defect_id: str


class FeedbackRequest(BaseModel):
    text: str = Field(min_length=3, max_length=2000)


def _run_dir(settings: Settings, run_id: str) -> Path:
    if not RUN_ID_PATTERN.match(run_id):
        raise HTTPException(status_code=400, detail="Invalid run id.")
    path = settings.output_dir / "runs" / run_id
    if not path.is_dir():
        raise HTTPException(status_code=404, detail="Run not found.")
    return path


def _read_run(run_dir: Path) -> dict:
    """Run details for the UI. A draft that failed its checks is never sent to the browser."""
    trace = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))
    lesson_path = run_dir / "lesson.md"
    if trace["status"] == "shipped" and lesson_path.exists():
        trace["lesson_markdown"] = lesson_path.read_text(encoding="utf-8")
    else:
        for attempt in trace["attempts"]:
            attempt.pop("lesson", None)
    trace["rejection_log"] = (run_dir / "rejection_log.md").read_text(encoding="utf-8")
    trace["models_used"] = sorted(
        {model for role in trace["usage"].values() for model in role.get("models", {})}
    )
    return trace


def create_app() -> FastAPI:
    load_dotenv(ENV_FILE)
    settings = Settings()
    store = MemoryStore(settings.memory_path)
    store.import_shipped_runs(settings.output_dir / "runs")
    jobs = JobManager()
    app = FastAPI(title="LessonProof")

    def run_job(topic: str, regenerate: bool):
        def work(job: Job) -> None:
            if not regenerate:
                saved = store.latest_shipped_run(topic, load_rubric().version)
                saved_dir = settings.output_dir / "runs" / saved if saved else None
                if saved_dir and (saved_dir / "lesson.md").exists():
                    job.emit({"event": "finished", "from_saved": True, **_read_run(saved_dir)})
                    return

            def on_event(event: dict) -> None:
                if event["event"] == "lesson_ready":
                    run = _read_run(Path(event["run_dir"]))
                    if run["status"] == "shipped":
                        job.emit({"event": "preview", **run})
                else:
                    job.emit(event)

            started = time.perf_counter()
            for start_number in range(settings.fresh_starts + 1):
                if start_number:
                    job.emit({"event": "starting_over"})
                llm = LangChainLLM(settings)
                result = run_pipeline(topic, llm, store, settings, on_event=on_event)
                if result.status == "shipped":
                    break
            job.emit(
                {
                    "event": "finished",
                    "seconds": round(time.perf_counter() - started, 1),
                    **_read_run(result.run_dir),
                }
            )

        return work

    def inject_job(defect_id: str):
        def work(job: Job) -> None:
            defect = get_defect(defect_id)
            path = settings.output_dir / "latest" / "lesson.json"
            lesson = Lesson.model_validate_json(path.read_text(encoding="utf-8"))
            corrupted = defect.apply(lesson)
            job.emit({"event": "step_started", "step": "evaluate_lesson"})
            llm = LangChainLLM(settings)
            evaluator = Evaluator(
                llm,
                load_rubric(),
                store.active_notes_by_check(),
                settings.judge_concurrency,
            )
            report = evaluator.evaluate(corrupted, find_curated_pack(DEFAULT_TOPIC))
            failed = {f.check_id for f in report.failures}
            job.emit(
                {
                    "event": "injection_result",
                    "defect": {
                        "id": defect.id,
                        "description": defect.description,
                        "expected_check": defect.expected_check,
                    },
                    "caught": defect.expected_check in failed,
                    "report": report.model_dump(mode="json"),
                    "usage": llm.usage(),
                }
            )

        return work

    def start(work) -> dict:
        job = jobs.start(work)
        if job is None:
            raise HTTPException(status_code=409, detail="A job is already running.")
        return {"job_id": job.id}

    @app.get("/api/config")
    def config() -> dict:
        rubric = load_rubric()
        latest = settings.output_dir / "latest" / "lesson.json"
        active = jobs.active()
        return {
            "default_topic": DEFAULT_TOPIC,
            "writer_model": settings.writer_model,
            "judge_model": settings.judge_model,
            "max_retries": settings.max_retries,
            "rubric": [c.model_dump(include={"id", "label", "dimension", "kind", "criterion"})
                       for c in rubric.checks],
            "defects": [
                {"id": d.id, "expected_check": d.expected_check, "description": d.description}
                for d in DEFECTS
            ],
            "has_passing_lesson": latest.exists(),
            "active_job": active.id if active else None,
        }

    @app.post("/api/runs", status_code=202)
    def create_run(request: RunRequest) -> dict:
        return start(run_job(request.topic.strip(), request.regenerate))

    @app.post("/api/inject-error", status_code=202)
    def inject_error(request: InjectRequest) -> dict:
        if request.defect_id not in {d.id for d in DEFECTS}:
            raise HTTPException(status_code=400, detail="Unknown error type.")
        if not (settings.output_dir / "latest" / "lesson.json").exists():
            raise HTTPException(status_code=409, detail="Generate a passing lesson first.")
        return start(inject_job(request.defect_id))

    @app.get("/api/jobs/{job_id}/events")
    def job_events(job_id: str) -> StreamingResponse:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found.")

        def stream() -> Iterator[str]:
            seen = 0
            while True:
                events = job.wait_for_events(seen, HEARTBEAT_SECONDS)
                for event in events:
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                seen += len(events)
                if job.finished and seen == len(job.events):
                    yield 'data: {"event": "closed"}\n\n'
                    return
                if not events:
                    yield ": heartbeat\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/runs")
    def list_runs() -> list[dict]:
        history = store.run_history()
        for row in history:
            row["usage"] = json.loads(row.pop("usage_json"))
        return list(reversed(history))

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        return _read_run(_run_dir(settings, run_id))

    @app.post("/api/runs/{run_id}/feedback", status_code=201)
    def add_feedback(run_id: str, request: FeedbackRequest) -> dict:
        _run_dir(settings, run_id)
        store.add_feedback(run_id, request.text.strip())
        return {"saved": True}

    @app.get("/api/memory")
    def memory() -> dict:
        guidelines = []
        for item in store.active_guidelines():
            before = store.first_attempt_rate(item.check_id, 0, item.after_run_seq)
            after = store.first_attempt_rate(item.check_id, item.after_run_seq)
            guidelines.append(
                {
                    "check_id": item.check_id,
                    "text": item.text,
                    "origin": item.origin,
                    "failures_before": before[0],
                    "runs_before": before[1],
                    "failures_after": after[0],
                    "runs_after": after[1],
                }
            )
        notes = [
            {"check_id": n.check_id, "text": n.text, "status": n.status, "origin": n.origin}
            for status in ("active", "candidate", "retired")
            for n in store.judge_notes(status)
        ]
        return {"guidelines": guidelines, "judge_notes": notes}

    index_file = settings.frontend_dir / "index.html"
    if not index_file.exists():
        raise RuntimeError(
            f"{index_file} was not found. Build the frontend first: "
            "cd frontend && npm install && npm run build"
        )

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(index_file)

    app.mount("/assets", StaticFiles(directory=settings.frontend_dir / "assets"), name="assets")
    return app
