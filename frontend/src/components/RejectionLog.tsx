import type { LogEntry } from "../runState";
import type { AttemptRecord, CheckResult } from "../types";

type LabelFor = (id: string) => string;

export function FailureBlock({ result, labelFor }: { result: CheckResult; labelFor: LabelFor }) {
  return (
    <div className="failure">
      <b>{labelFor(result.check_id)}</b>
      <div>{result.reason}</div>
      {(result.evidence ?? []).slice(0, 3).map((quote, index) => (
        <div className="evidence" key={index}>
          {quote}
        </div>
      ))}
      {result.fix && <div className="fix">Required fix: {result.fix}</div>}
    </div>
  );
}

function changeItems(record: AttemptRecord, labelFor: LabelFor): string[] {
  const items = [...(record.code_fixes ?? [])];
  (record.repaired_rule_failures ?? []).forEach((failure) => {
    items.push(`Repaired before judging: ${labelFor(failure.check_id)}`);
  });
  if (record.revision) {
    items.push(`Parts rewritten: ${record.revision.sections_changed.join(", ") || "none"}`);
    record.revision.notes.forEach((note) => {
      items.push(`${labelFor(note.check_id)}: ${note.change}`);
    });
  }
  return items;
}

function Attempt({ record, labelFor }: { record: AttemptRecord; labelFor: LabelFor }) {
  const { report } = record;
  const failures = report.results.filter((r) => !r.passed);
  const allPassed = report.complete && failures.length === 0;
  const changes = changeItems(record, labelFor);
  return (
    <div className="attempt">
      <div className="attempt-head">
        <h3>
          Attempt {record.attempt}: {report.results.length - failures.length} of{" "}
          {report.results.length} checks passed
        </h3>
        <span className={`badge ${allPassed ? "pass" : "fail"}`}>
          {allPassed ? "Passed" : "Rejected"}
        </span>
      </div>
      {changes.length > 0 && (
        <>
          <p className="log-label">{record.revision ? "WHAT CHANGED ON THIS RETRY" : "AUTOMATIC FIXES"}</p>
          <ul className="changes">
            {changes.map((text, index) => (
              <li key={index}>{text}</li>
            ))}
          </ul>
        </>
      )}
      {failures.length > 0 && (
        <>
          <p className="log-label">WHAT FAILED AND WHY</p>
          {failures.map((failure) => (
            <FailureBlock key={failure.check_id} result={failure} labelFor={labelFor} />
          ))}
        </>
      )}
    </div>
  );
}

export default function RejectionLog({ log, labelFor }: { log: LogEntry[]; labelFor: LabelFor }) {
  return (
    <div>
      <p className="stage-sub">What failed, why, and what was changed on each retry.</p>
      <div id="attempts">
        {log.length === 0 && <p className="empty">The log appears after a lesson has been checked.</p>}
        {log.map((entry, index) =>
          entry.kind === "divider" ? (
            <h3 className="log-divider" key={index}>
              Second try, written from the start
            </h3>
          ) : (
            <Attempt key={index} record={entry.record} labelFor={labelFor} />
          ),
        )}
      </div>
    </div>
  );
}
