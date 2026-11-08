"""Runs one long job at a time on a background thread and keeps its events for streaming."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable


class Job:
    def __init__(self) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.events: list[dict] = []
        self.finished = False
        self._changed = threading.Condition()

    def emit(self, event: dict) -> None:
        with self._changed:
            self.events.append(event)
            self._changed.notify_all()

    def finish(self) -> None:
        with self._changed:
            self.finished = True
            self._changed.notify_all()

    def wait_for_events(self, seen: int, timeout: float) -> list[dict]:
        """Returns events after index `seen`, waiting up to `timeout` seconds for new ones."""
        with self._changed:
            if len(self.events) <= seen and not self.finished:
                self._changed.wait(timeout)
            return self.events[seen:]


class JobManager:
    """One job at a time: parallel runs would compete for the same API rate limit."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._active: Job | None = None

    def start(self, work: Callable[[Job], None]) -> Job | None:
        with self._lock:
            if self._active and not self._active.finished:
                return None
            job = Job()
            self._jobs[job.id] = job
            self._active = job

        def runner() -> None:
            try:
                work(job)
            except Exception as error:
                job.emit(
                    {
                        "event": "failed",
                        "message": str(error)[:500],
                        "reason": getattr(error, "reason", "service"),
                        "retry_after": getattr(error, "retry_after", None),
                    }
                )
            finally:
                job.finish()

        threading.Thread(target=runner, daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def active(self) -> Job | None:
        with self._lock:
            return self._active if self._active and not self._active.finished else None
