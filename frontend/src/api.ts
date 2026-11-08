import type { Config, InjectionResult, Memory, RunDetails, RunEvent, RunSummary } from "./types";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : null;
    throw new Error(detail ?? "Something went wrong. Please try again.");
  }
  return body as T;
}

function post<T>(path: string, payload: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export const api = {
  config: () => request<Config>("/api/config"),
  runs: () => request<RunSummary[]>("/api/runs"),
  run: (id: string) => request<RunDetails>(`/api/runs/${id}`),
  memory: () => request<Memory>("/api/memory"),
  startRun: (topic: string, regenerate: boolean) =>
    post<{ job_id: string }>("/api/runs", { topic, regenerate }),
  injectError: (defectId: string) =>
    post<{ job_id: string }>("/api/inject-error", { defect_id: defectId }),
  sendFeedback: (runId: string, text: string) =>
    post<{ saved: boolean }>(`/api/runs/${runId}/feedback`, { text }),
};

export type InjectionEvent =
  | ({ event: "injection_result" } & InjectionResult)
  | { event: "failed"; message: string; reason: string }
  | { event: "closed" }
  | { event: "step_started"; step: string };

export function followJob<E extends { event: string }>(
  jobId: string,
  onEvent: (event: E) => void,
  onClosed: () => void,
): () => void {
  const source = new EventSource(`/api/jobs/${jobId}/events`);
  source.onmessage = (message) => {
    const event = JSON.parse(message.data) as E;
    if (event.event === "closed") {
      source.close();
      onClosed();
      return;
    }
    onEvent(event);
  };
  source.onerror = () => {
    if (source.readyState === EventSource.CLOSED) onClosed();
  };
  return () => source.close();
}

export type { RunEvent };
