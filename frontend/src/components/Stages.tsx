import { DIMENSIONS, PARTS } from "../constants";
import type { LogEntry, PartStatus } from "../runState";
import type { CheckResult, RubricCheck } from "../types";

export function PartsPanel({ parts }: { parts: Record<string, PartStatus> }) {
  return (
    <section className="panel" aria-labelledby="generate-title">
      <h2 id="generate-title">Lesson parts</h2>
      <ul className="parts-list">
        {PARTS.map((part) => {
          const status = parts[part.role];
          return (
            <li key={part.role} className={`part-row ${status.tone}`}>
              <span>{part.label}</span>
              <small>{status.text}</small>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

interface ChecksProps {
  rubric: RubricCheck[];
  results: Record<string, CheckResult>;
}

export function ChecksPanel({ rubric, results }: ChecksProps) {
  const finished = Object.values(results);
  const passed = finished.filter((r) => r.passed).length;
  return (
    <section className="panel" aria-labelledby="evaluate-title">
      <div className="panel-head">
        <h2 id="evaluate-title">Quality checks</h2>
        <span className="panel-score" id="evaluate-score">
          {finished.length ? `${passed} of ${rubric.length} passed` : ""}
        </span>
      </div>
      <div id="dimensions">
        {DIMENSIONS.map((dimension) => {
          const checks = rubric.filter((c) => c.dimension === dimension.key);
          const good = checks.filter((c) => results[c.id]?.passed).length;
          const hasFailure = checks.some((c) => results[c.id] && !results[c.id].passed);
          return (
            <details className="dimension" key={dimension.key} open={hasFailure || undefined}>
              <summary>
                <span>{dimension.title}</span>
                <span className={`dimension-count ${good === checks.length && good > 0 ? "all" : ""} ${hasFailure ? "bad" : ""}`}>
                  {good}/{checks.length}
                </span>
              </summary>
              {checks.map((check) => {
                const result = results[check.id];
                const tone = result ? (result.passed ? "pass" : "fail") : "";
                const mark = result ? (result.passed ? "✓" : "✕") : "·";
                return (
                  <div className={`check-row ${tone}`} key={check.id} title={result?.reason}>
                    <i aria-hidden="true">{mark}</i>
                    <span>{check.label || check.id}</span>
                  </div>
                );
              })}
            </details>
          );
        })}
      </div>
    </section>
  );
}

interface RetriesProps {
  log: LogEntry[];
  maxRetries: number;
  labelFor: (id: string) => string;
}

export function RetriesPanel({ log, maxRetries, labelFor }: RetriesProps) {
  const attempts = log.filter((e) => e.kind === "attempt");
  const latest = attempts[attempts.length - 1];
  const retries = latest?.kind === "attempt" ? Math.min(latest.record.attempt - 1, maxRetries) : null;
  return (
    <section className="panel" aria-labelledby="regenerate-title">
      <div className="panel-head">
        <h2 id="regenerate-title">Fixes</h2>
        <span className="panel-score" id="retry-score">
          {retries === null ? "" : `${retries} of ${maxRetries} retries`}
        </span>
      </div>
      {attempts.length === 0 && <p className="panel-empty">Failed checks go back here to be fixed.</p>}
      <ol className="retries">
        {log.map((entry, index) => {
          if (entry.kind === "divider") {
            return (
              <li className="retry-divider" key={index}>
                Second try, from the start
              </li>
            );
          }
          const failures = entry.record.report.results.filter((r) => !r.passed);
          return (
            <li className={`retry-item ${failures.length ? "" : "good"}`} key={index}>
              <b>
                {failures.length
                  ? `Attempt ${entry.record.attempt}: ${failures.length} sent back`
                  : `Attempt ${entry.record.attempt}: all passed`}
              </b>
              {failures.length > 0 && <span>{failures.map((f) => labelFor(f.check_id)).join(", ")}</span>}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
