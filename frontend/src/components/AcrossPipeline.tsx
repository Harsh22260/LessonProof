import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, followJob, type InjectionEvent } from "../api";
import type { Defect, InjectionResult, Memory, RunSummary } from "../types";
import { FailureBlock } from "./RejectionLog";

const OUTCOME: Record<string, string> = { shipped: "Passed", rejected: "Rejected", error: "Stopped" };

interface AcrossProps {
  refreshKey: number;
  labelFor: (id: string) => string;
}

export function AcrossPipeline({ refreshKey, labelFor }: AcrossProps) {
  const [memory, setMemory] = useState<Memory>({ guidelines: [] });
  const [runs, setRuns] = useState<RunSummary[]>([]);

  useEffect(() => {
    Promise.all([api.memory(), api.runs()])
      .then(([nextMemory, nextRuns]) => {
        setMemory(nextMemory);
        setRuns(nextRuns);
      })
      .catch(() => undefined);
  }, [refreshKey]);

  return (
    <div className="tab-content">
      <h2>Rules it wrote for itself</h2>
      <p className="tab-lead">When the same check keeps failing, the system writes a rule to avoid it next time.</p>
      {memory.guidelines.length === 0 && <p className="tab-lead">No rules yet.</p>}
      <div className="learned-list">
        {memory.guidelines.slice(0, 6).map((guideline, index) => (
          <article className="learned-item" key={index}>
            <small>{labelFor(guideline.check_id)}</small>
            <p>{guideline.text}</p>
          </article>
        ))}
      </div>

      <h2 className="tab-heading-gap">Past runs</h2>
      <p className="tab-lead">Memory persists between runs.</p>
      {runs.length === 0 ? (
        <p className="tab-lead">No runs yet.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Topic</th>
                <th>Result</th>
                <th>Attempts</th>
              </tr>
            </thead>
            <tbody>
              {runs.slice(0, 8).map((run) => (
                <tr key={run.run_id}>
                  <td>{run.topic}</td>
                  <td>{OUTCOME[run.status] ?? run.status}</td>
                  <td>{run.attempts}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

interface TestProps {
  defects: Defect[];
  hasLesson: boolean;
  busy: boolean;
  onBusyChange: (busy: boolean) => void;
  labelFor: (id: string) => string;
}

export function EvaluatorTest({ defects, hasLesson, busy, onBusyChange, labelFor }: TestProps) {
  const [defectId, setDefectId] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [result, setResult] = useState<InjectionResult | null>(null);
  const stop = useRef<(() => void) | null>(null);

  useEffect(() => () => stop.current?.(), []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setResult(null);
    setMessage("Checking the lesson with the mistake added.");
    onBusyChange(true);
    try {
      const { job_id: jobId } = await api.injectError(defectId || defects[0].id);
      stop.current = followJob<InjectionEvent>(
        jobId,
        (update) => {
          if (update.event === "injection_result") {
            setResult(update);
            setMessage(null);
          } else if (update.event === "failed") {
            setMessage(
              update.reason === "setup"
                ? "The API key is missing or was not accepted. Set GOOGLE_API_KEY in .env and restart the server."
                : update.reason === "quota"
                  ? "Today's free AI limit is used up. Please try again after it resets."
                  : "The AI service is busy. Please try again shortly.",
            );
          }
        },
        () => onBusyChange(false),
      );
    } catch (error) {
      setMessage((error as Error).message);
      onBusyChange(false);
    }
  }

  const failures = result?.report.results.filter((r) => !r.passed) ?? [];
  return (
    <div className="tab-content">
      <h2>Test the quality checks</h2>
      <p className="tab-lead">
        This is for reviewers, not learners. Pick a mistake to add to a copy of the approved lesson,
        then see if the checks catch it. Your saved lesson does not change.
      </p>
      <form id="inject-form" className="inject-form" onSubmit={submit}>
        <select
          id="defect"
          aria-label="Mistake to add"
          value={defectId}
          onChange={(event) => setDefectId(event.target.value)}
        >
          {defects.map((defect) => (
            <option key={defect.id} value={defect.id}>
              {defect.description}
            </option>
          ))}
        </select>
        <button type="submit" id="inject-button" className="btn-primary" disabled={busy || !hasLesson}>
          Add mistake and check
        </button>
      </form>
      <div id="inject-result">
        {!hasLesson && <p className="tab-lead">Create an approved lesson first.</p>}
        {message && <div className="notice wait">{message}</div>}
        {result && (
          <>
            <div className={`notice ${result.caught ? "pass" : "wait"}`}>
              {result.caught ? "Caught. " : "Missed. "}"{labelFor(result.defect.expected_check)}"
              {result.caught ? " found the mistake." : " did not find the mistake."}
            </div>
            {failures.map((failure) => (
              <FailureBlock key={failure.check_id} result={failure} labelFor={labelFor} />
            ))}
          </>
        )}
      </div>
    </div>
  );
}
