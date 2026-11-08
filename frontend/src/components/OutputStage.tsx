import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { api } from "../api";
import { PARTS } from "../constants";
import type { RunState } from "../runState";
import type { Section } from "../types";
import Markdown from "./Markdown";
import RejectionLog from "./RejectionLog";

type View = "lesson" | "log" | "memory" | "test";

interface Props {
  state: RunState;
  labelFor: (id: string) => string;
  onRegenerate: () => void;
  onNewTopic: () => void;
  memoryPanel: ReactNode;
  testPanel: ReactNode;
}

function Part({ section }: { section: Section }) {
  return (
    <section className="part" data-role={section.role}>
      <h2>{section.heading}</h2>
      <Markdown text={section.body} className="part-body" />
    </section>
  );
}

function download(markdown: string) {
  const url = URL.createObjectURL(new Blob([markdown], { type: "text/markdown" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "lesson.md";
  link.click();
  URL.revokeObjectURL(url);
}

function Feedback({ runId }: { runId: string }) {
  const [text, setText] = useState("");
  const [status, setStatus] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!text.trim()) return;
    try {
      await api.sendFeedback(runId, text.trim());
      setText("");
      setStatus("Thank you. Future lessons will learn from this.");
    } catch (error) {
      setStatus((error as Error).message);
    }
  }

  return (
    <form id="feedback-form" className="feedback" onSubmit={submit}>
      <label htmlFor="feedback">How could this lesson be better?</label>
      <textarea
        id="feedback"
        rows={2}
        maxLength={2000}
        placeholder="The system learns from your feedback."
        value={text}
        onChange={(event) => setText(event.target.value)}
      />
      <div className="feedback-row">
        <button type="submit" className="btn-outline">
          Send feedback
        </button>
        <span role="status">{status}</span>
      </div>
    </form>
  );
}

function Message({ title, text, children }: { title: string; text: string; children?: ReactNode }) {
  return (
    <div className="message">
      <h2>{title}</h2>
      <p>{text}</p>
      {children && <div className="message-actions">{children}</div>}
    </div>
  );
}

function quotaText(retryAfter: number | null): string {
  const saved = "Trying again before then will not work. Lessons that are already approved still open normally.";
  if (retryAfter === null) return `New lessons can be created after the limit resets. ${saved}`;
  const resetAt = new Date(Date.now() + retryAfter * 1000).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
  const minutes = Math.ceil(retryAfter / 60);
  const wait =
    minutes < 60 ? `${minutes} minutes` : `${Math.floor(minutes / 60)} hours ${minutes % 60} minutes`;
  return `New lessons can be created again at about ${resetAt}, in ${wait}. ${saved}`;
}

function LessonView({
  state,
  onRegenerate,
  onNewTopic,
  onShowLog,
}: Pick<Props, "state" | "onRegenerate" | "onNewTopic"> & { onShowLog: () => void }) {
  const order = PARTS.map((p) => p.role);
  const liveSections = [...state.sections].sort((a, b) => order.indexOf(a.role) - order.indexOf(b.role));

  if (state.outcome === "approved" && state.run?.lesson_markdown) {
    const markdown = state.run.lesson_markdown;
    return (
      <>
        <div className="lesson-actions">
          <button type="button" id="download" className="btn-outline" onClick={() => download(markdown)}>
            Download lesson
          </button>
          <button type="button" id="regenerate" className="btn-outline" onClick={onRegenerate} disabled={state.running}>
            Create a new version
          </button>
        </div>
        {state.run.grounding !== "curated" && (
          <p className="ground-note">
            This topic has no reviewed fact sheet, so its facts come from the AI. Please
            double-check anything important.
          </p>
        )}
        <article id="lesson" className="lesson">
          <Markdown text={markdown} />
        </article>
        <Feedback runId={state.run.run_id} />
      </>
    );
  }

  if (state.outcome === "not_finished") {
    return (
      <div id="lesson">
        <Message
          title="This lesson did not reach our quality standard"
          text="We do not show a lesson that failed its checks. The rejection log explains what went wrong."
        >
          <button type="button" className="btn-primary" onClick={onRegenerate}>
            Try again
          </button>
          <button type="button" className="btn-outline" onClick={onShowLog}>
            See the rejection log
          </button>
        </Message>
      </div>
    );
  }

  if (state.outcome === "quota") {
    return (
      <div id="lesson">
        <Message title="Today's free AI limit is used up" text={quotaText(state.retryAfter)}>
          <button type="button" className="btn-primary" onClick={onNewTopic}>
            Read an approved lesson
          </button>
        </Message>
      </div>
    );
  }

  if (state.outcome === "setup") {
    return (
      <div id="lesson">
        <Message
          title="Add a working API key to create lessons"
          text="The API key is missing or was not accepted. Set GOOGLE_API_KEY in the .env file in the project folder, then restart the server. Lessons that are already approved still open normally."
        >
          <button type="button" className="btn-primary" onClick={onNewTopic}>
            Read an approved lesson
          </button>
        </Message>
      </div>
    );
  }

  if (state.outcome === "service_busy") {
    return (
      <div id="lesson">
        <Message title="The AI service is busy right now" text="Nothing was published. Please try again in a few minutes.">
          <button type="button" className="btn-primary" onClick={onRegenerate}>
            Try again
          </button>
          <button type="button" className="btn-outline" onClick={onNewTopic}>
            Choose another topic
          </button>
        </Message>
      </div>
    );
  }

  const draftSections = state.draft?.sections;
  return (
    <article id="lesson" className="lesson">
      {state.draft && <h1>{state.draft.title}</h1>}
      {(draftSections ?? liveSections).map((section) => (
        <Part key={section.role} section={section} />
      ))}
      {!draftSections && liveSections.length === 0 && (
        <div className="skeleton" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      )}
      {!draftSections && liveSections.length === 0 && state.waitingText && (
        <p className="waiting">{state.waitingText}</p>
      )}
    </article>
  );
}

const TABS: { key: View; label: string }[] = [
  { key: "lesson", label: "Lesson" },
  { key: "log", label: "Rejection log" },
  { key: "memory", label: "What it learned" },
  { key: "test", label: "For reviewers" },
];

export default function OutputStage(props: Props) {
  const { state, labelFor, onRegenerate, onNewTopic, memoryPanel, testPanel } = props;
  const [view, setView] = useState<View>("lesson");
  const rejectedCount = state.log.filter(
    (entry) =>
      entry.kind === "attempt" &&
      (!entry.record.report.complete || entry.record.report.results.some((r) => !r.passed)),
  ).length;

  useEffect(() => {
    if (state.running) setView("lesson");
  }, [state.running]);

  return (
    <section className="output" id="stage-output" aria-label="Result">
      {state.notice && (
        <div id="lesson-status" className={`notice ${state.notice.tone}`}>
          {state.notice.text}
        </div>
      )}
      <div className="tabs" role="tablist" aria-label="Result views">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            role="tab"
            data-view={tab.key}
            className={tab.key === "test" ? "tab-reviewers" : undefined}
            aria-selected={view === tab.key}
            onClick={() => setView(tab.key)}
          >
            {tab.label}
            {tab.key === "log" && rejectedCount > 0 && <span className="tab-count">{rejectedCount}</span>}
          </button>
        ))}
      </div>
      <div className="tab-body">
        {view === "lesson" && (
          <LessonView
            state={state}
            onRegenerate={onRegenerate}
            onNewTopic={onNewTopic}
            onShowLog={() => setView("log")}
          />
        )}
        {view === "log" && <RejectionLog log={state.log} labelFor={labelFor} />}
        <div hidden={view !== "memory"}>{memoryPanel}</div>
        <div hidden={view !== "test"}>{testPanel}</div>
      </div>
    </section>
  );
}
