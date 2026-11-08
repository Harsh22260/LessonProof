import { PARTS, STEP_INFO, type StageKey } from "./constants";
import type { AttemptRecord, CheckResult, Lesson, RunDetails, RunEvent, Section } from "./types";

export type LogEntry = { kind: "attempt"; record: AttemptRecord } | { kind: "divider" };
export type PartStatus = { tone: "" | "writing" | "ready"; text: string };
export type Notice = { tone: "pass" | "wait"; text: string } | null;
export type Outcome = "none" | "approved" | "not_finished" | "service_busy" | "quota" | "setup";

export interface RunState {
  running: boolean;
  startedAt: number | null;
  seconds: number | null;
  note: string;
  stage: StageKey | null;
  allDone: boolean;
  parts: Record<string, PartStatus>;
  results: Record<string, CheckResult>;
  log: LogEntry[];
  sections: Section[];
  draft: Lesson | null;
  waitingText: string | null;
  notice: Notice;
  outcome: Outcome;
  run: RunDetails | null;
  retryAfter: number | null;
}

function emptyParts(): Record<string, PartStatus> {
  return Object.fromEntries(PARTS.map((p) => [p.role, { tone: "", text: "Waiting" }]));
}

function allParts(status: PartStatus): Record<string, PartStatus> {
  return Object.fromEntries(PARTS.map((p) => [p.role, status]));
}

export const initialRunState: RunState = {
  running: false,
  startedAt: null,
  seconds: null,
  note: "Enter a topic to begin.",
  stage: null,
  allDone: false,
  parts: emptyParts(),
  results: {},
  log: [],
  sections: [],
  draft: null,
  waitingText: null,
  notice: null,
  outcome: "none",
  run: null,
  retryAfter: null,
};

export type RunAction =
  | { type: "start"; now: number }
  | { type: "start_failed" }
  | { type: "event"; event: RunEvent }
  | { type: "show_saved"; run: RunDetails };

function byResultId(results: CheckResult[]): Record<string, CheckResult> {
  return Object.fromEntries(results.map((r) => [r.check_id, r]));
}

function withApproved(state: RunState, run: RunDetails): RunState {
  return {
    ...state,
    run,
    outcome: "approved",
    parts: allParts({ tone: "ready", text: "Approved" }),
    notice: {
      tone: "pass",
      text: run.from_saved
        ? "This lesson already passed every check, so here it is right away."
        : `Your lesson is ready. It passed every check${
            run.seconds ? ` in ${Math.round(run.seconds)} seconds` : ""
          }.`,
    },
  };
}

function finish(state: RunState, run: RunDetails): RunState {
  const hasAttempts = state.log.some((entry) => entry.kind === "attempt");
  const log: LogEntry[] = hasAttempts
    ? state.log
    : run.attempts.map((record) => ({ kind: "attempt", record }));
  const last = run.attempts[run.attempts.length - 1];
  const base: RunState = {
    ...state,
    running: false,
    startedAt: null,
    seconds: run.seconds ?? state.seconds,
    allDone: true,
    stage: null,
    log,
    results: last ? { ...state.results, ...byResultId(last.report.results) } : state.results,
    waitingText: null,
  };
  if (run.status === "shipped") {
    return { ...withApproved(base, run), note: "Done. Your lesson passed every check." };
  }
  return {
    ...base,
    run,
    outcome: "not_finished",
    notice: null,
    parts: allParts({ tone: "", text: "Not published" }),
    note: "Finished. No lesson was published this time.",
  };
}

function reduceEvent(state: RunState, event: RunEvent): RunState {
  switch (event.event) {
    case "step_started": {
      const info = STEP_INFO[event.step];
      const next: RunState = info ? { ...state, stage: info.stage, note: info.note } : state;
      if (event.step === "write_lesson") {
        return { ...next, parts: allParts({ tone: "writing", text: "Writing" }) };
      }
      if (event.step === "evaluate_lesson") return { ...next, results: {} };
      return next;
    }
    case "section_ready": {
      const sections = [
        ...state.sections.filter((s) => s.role !== event.section.role),
        event.section,
      ];
      return {
        ...state,
        sections,
        draft: null,
        waitingText: null,
        parts: {
          ...state.parts,
          [event.section.role]: { tone: "ready", text: "Basics passed" },
        },
        note: `${sections.length} of ${PARTS.length} parts written and shown below.`,
        notice: {
          tone: "wait",
          text: "Parts appear as they pass their basic checks. The full lesson is confirmed at the end.",
        },
      };
    }
    case "draft_ready":
      return { ...state, draft: event.lesson };
    case "checks_done": {
      const results = { ...state.results, ...byResultId(event.results) };
      return { ...state, results };
    }
    case "attempt":
      return { ...state, log: [...state.log, { kind: "attempt", record: event.record }] };
    case "starting_over":
      return {
        ...state,
        sections: [],
        draft: null,
        results: {},
        parts: emptyParts(),
        log: [...state.log, { kind: "divider" }],
        stage: "generate",
        waitingText: "Taking a fresh approach to make this lesson better.",
        note: "Writing a new version from the start.",
        notice: {
          tone: "wait",
          text: "Writing a new version, because the first one needed more work.",
        },
      };
    case "preview":
      return withApproved(state, event);
    case "finished":
      return finish(state, event);
    case "failed":
      return {
        ...state,
        running: false,
        startedAt: null,
        outcome: event.reason === "quota" || event.reason === "setup" ? event.reason : "service_busy",
        retryAfter: event.retry_after,
        notice: null,
        sections: [],
        draft: null,
        waitingText: null,
        stage: null,
        note:
          event.reason === "quota"
            ? "Stopped, because today's AI limit is used up."
            : event.reason === "setup"
              ? "Stopped, because the API key is missing or not valid."
              : "Stopped, because the AI service is busy.",
      };
    default:
      return state;
  }
}

export function runReducer(state: RunState, action: RunAction): RunState {
  switch (action.type) {
    case "start":
      return {
        ...initialRunState,
        running: true,
        startedAt: action.now,
        stage: "input",
        note: "Starting.",
        waitingText: "The first parts will appear here in a moment.",
      };
    case "start_failed":
      return { ...state, running: false, startedAt: null, stage: null, waitingText: null };
    case "event":
      return reduceEvent(state, action.event);
    case "show_saved":
      return finish(initialRunState, { ...action.run, from_saved: true });
  }
}
