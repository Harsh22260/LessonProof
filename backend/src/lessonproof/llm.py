"""Provider-neutral structured LLM calls with hedged failover and token accounting.

If a model has not answered after a few seconds, the next model starts too, and the first valid
answer wins. A slow or overloaded model therefore costs seconds rather than minutes.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Literal, Protocol, TypeVar

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from lessonproof.config import Settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
Role = Literal["writer", "judge"]

NON_RETRYABLE_STATUS = {400, 401, 403, 404, 422}
KEY_MARKERS = ("API_KEY_INVALID", "PERMISSION_DENIED")
NON_RETRYABLE_MARKERS = ("API_KEY_INVALID", "PERMISSION_DENIED", "INVALID_ARGUMENT")
MODEL_GONE_MARKERS = ("NOT_FOUND",)
UNUSABLE_MARKERS = ("PerDay", *MODEL_GONE_MARKERS)
FALLBACK_BLOCK_SECONDS = 3600.0
RETRY_DELAY = re.compile(r"retryDelay['\"]?:\s*['\"]?(\d+)")
ROUND_PAUSE_SECONDS = 2.0


class LLMError(RuntimeError):
    """A model call failed for good. The run must stop instead of shipping unjudged content."""


class QuotaExhausted(LLMError):
    """The daily limit is used up, so retrying before the reset cannot work."""

    reason = "quota"

    def __init__(self, message: str, retry_after: float | None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ModelSetupError(LLMError):
    """The API key or model package is missing or invalid, so retrying cannot work."""

    reason = "setup"


class LLM(Protocol):
    def structured(self, role: Role, schema: type[T], system: str, user: str) -> T: ...

    def usage(self) -> dict[str, dict]: ...


def _has_marker(error: Exception, markers: tuple[str, ...]) -> bool:
    return any(marker in str(error) for marker in markers)


def _is_permanent(error: Exception) -> bool:
    if _has_marker(error, MODEL_GONE_MARKERS):
        return False
    if getattr(error, "status_code", None) in NON_RETRYABLE_STATUS:
        return True
    return _has_marker(error, NON_RETRYABLE_MARKERS)


class ModelHealth:
    """Shared across runs, so later calls skip models already known to be out of quota."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._unusable_until: dict[str, float] = {}
        self._last_good: str | None = None

    def mark_unusable(self, model: str, error: Exception) -> None:
        """Blocks a model until the reset time the provider reports."""
        match = RETRY_DELAY.search(str(error))
        seconds = float(match.group(1)) if match else FALLBACK_BLOCK_SECONDS
        with self._lock:
            self._unusable_until[model] = time.monotonic() + seconds

    def seconds_until_reset(self, chain: list[str]) -> float | None:
        """Time until the first blocked model in the chain becomes usable again."""
        now = time.monotonic()
        with self._lock:
            waits = [self._unusable_until[m] - now for m in chain if m in self._unusable_until]
        waits = [wait for wait in waits if wait > 0]
        return min(waits) if waits else None

    def mark_good(self, model: str) -> None:
        with self._lock:
            self._last_good = model

    def order(self, chain: list[str]) -> list[str]:
        """Usable models only, with the last one that answered first."""
        now = time.monotonic()
        with self._lock:
            usable = [m for m in chain if self._unusable_until.get(m, 0.0) <= now]
            if self._last_good in usable:
                usable.remove(self._last_good)
                usable.insert(0, self._last_good)
        return usable


_health = ModelHealth()


class UsageTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._totals: dict[str, dict] = {}

    def add(self, role: str, model: str, usage: dict) -> None:
        details = usage.get("input_token_details") or {}
        with self._lock:
            entry = self._totals.setdefault(
                role,
                {
                    "calls": 0,
                    "input_tokens": 0,
                    "cached_tokens": 0,
                    "output_tokens": 0,
                    "models": {},
                },
            )
            entry["calls"] += 1
            entry["input_tokens"] += usage.get("input_tokens", 0)
            entry["cached_tokens"] += details.get("cache_read", 0)
            entry["output_tokens"] += usage.get("output_tokens", 0)
            entry["models"][model] = entry["models"].get(model, 0) + 1

    def snapshot(self) -> dict[str, dict]:
        with self._lock:
            return {
                role: {**entry, "models": dict(entry["models"])}
                for role, entry in self._totals.items()
            }


class LangChainLLM:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._tracker = UsageTracker()
        self._lock = threading.Lock()
        self._models: dict[tuple[str, str], object] = {}
        self._chains = {
            "writer": [settings.writer_model, *settings.fallback_models],
            "judge": [settings.judge_model, *settings.fallback_models],
        }

    def _thinking(self, role: Role) -> str | None:
        return self._settings.writer_thinking if role == "writer" else self._settings.judge_thinking

    def _model(self, role: Role, name: str):
        key = (role, name)
        with self._lock:
            if key not in self._models:
                kwargs = {
                    "max_tokens": self._settings.max_output_tokens,
                    "timeout": self._settings.request_timeout_seconds,
                    "max_retries": 0,
                }
                if self._settings.temperature is not None:
                    kwargs["temperature"] = self._settings.temperature
                level = self._thinking(role)
                if level and name.startswith("google_genai:"):
                    kwargs["thinking_config"] = {"thinking_level": level}
                try:
                    self._models[key] = init_chat_model(name, **kwargs)
                except (ValueError, ImportError) as error:
                    raise ModelSetupError(
                        f"Could not set up model '{name}'. Check that its API key is in .env and "
                        f"its package is installed. Details: {str(error)[:200]}"
                    ) from error
            return self._models[key]

    def _call_once(self, role: Role, name: str, schema: type[T], messages: list):
        runnable = self._model(role, name).with_structured_output(
            schema, method="json_schema", include_raw=True
        )
        response = runnable.invoke(messages)
        self._tracker.add(role, name, getattr(response.get("raw"), "usage_metadata", None) or {})
        parsed = response.get("parsed")
        if parsed is None:
            raise ValueError(f"invalid structured output: {response.get('parsing_error')}")
        return parsed

    def structured(self, role: Role, schema: type[T], system: str, user: str) -> T:
        messages = [SystemMessage(content=system), HumanMessage(content=user)]
        deadline = time.monotonic() + self._settings.call_deadline_seconds
        last_error: Exception | None = None

        for _ in range(self._settings.llm_rounds):
            queue = _health.order(self._chains[role])
            if not queue:
                break
            result, last_error = self._race(role, schema, messages, queue, deadline)
            if result is not None:
                return result
            if time.monotonic() >= deadline:
                break
            time.sleep(ROUND_PAUSE_SECONDS)

        retry_after = _health.seconds_until_reset(self._chains[role])
        if retry_after is not None:
            raise QuotaExhausted(
                "The daily model quota is used up. Wait for the reset or enable billing.",
                retry_after,
            )
        raise LLMError(f"{role} model failed after retries: {str(last_error)[:300]}")

    def _race(self, role, schema, messages, queue: list[str], deadline: float):
        """Starts models one by one, adding another whenever the running ones are slow or fail."""
        pool = ThreadPoolExecutor(max_workers=len(queue))
        pending: dict[Future, str] = {}
        waiting = list(queue)
        last_error: Exception | None = None

        def start_next() -> None:
            name = waiting.pop(0)
            pending[pool.submit(self._call_once, role, name, schema, messages)] = name

        try:
            start_next()
            while pending and time.monotonic() < deadline:
                done, _ = wait(
                    pending, timeout=self._settings.hedge_after_seconds, return_when=FIRST_COMPLETED
                )
                if not done:
                    if waiting:
                        logger.info("%s: %s is slow, also trying %s",
                                    role, list(pending.values())[-1], waiting[0])
                        start_next()
                    continue
                for future in done:
                    name = pending.pop(future)
                    try:
                        result = future.result()
                    except LLMError:
                        raise
                    except Exception as error:
                        if _has_marker(error, KEY_MARKERS):
                            raise ModelSetupError(
                                f"The API key was rejected: {str(error)[:300]}"
                            ) from error
                        if _is_permanent(error):
                            raise LLMError(
                                f"{role} model rejected the request: {str(error)[:300]}"
                            ) from error
                        last_error = error
                        if _has_marker(error, UNUSABLE_MARKERS):
                            _health.mark_unusable(name, error)
                        logger.info("%s: %s failed (%s)", role, name, str(error)[:70])
                        continue
                    _health.mark_good(name)
                    return result, None
                if not pending and waiting:
                    start_next()
            return None, last_error or TimeoutError("no model answered before the deadline")
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def usage(self) -> dict[str, dict]:
        return self._tracker.snapshot()
