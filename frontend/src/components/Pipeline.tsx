import { useEffect, useState } from "react";
import { PIPELINE, type StageKey } from "../constants";

interface Props {
  stage: StageKey | null;
  allDone: boolean;
  note: string;
  startedAt: number | null;
  seconds: number | null;
}

function useElapsed(startedAt: number | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (startedAt === null) return;
    const timer = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(timer);
  }, [startedAt]);
  return startedAt === null ? 0 : Math.max(0, Math.round((now - startedAt) / 1000));
}

export default function Pipeline({ stage, allDone, note, startedAt, seconds }: Props) {
  const elapsed = useElapsed(startedAt);
  const activeIndex = PIPELINE.findIndex((step) => step.key === stage);
  const clock =
    startedAt !== null ? `${elapsed}s` : seconds !== null ? `${Math.round(seconds)}s` : "";

  return (
    <section className="tracker" aria-label="Progress">
      <ol className="stepper">
        {PIPELINE.map((step, index) => {
          const state = allDone || index < activeIndex ? "done" : index === activeIndex ? "active" : "";
          return (
            <li key={step.key} className={`step ${state}`} aria-current={state === "active" ? "step" : undefined}>
              <span className="step-dot">{state === "done" ? "✓" : index + 1}</span>
              <span className="step-name">{step.label}</span>
            </li>
          );
        })}
      </ol>
      <div className="tracker-note">
        <span id="current-note" aria-live="polite">
          {note}
        </span>
        {clock && <span className="clock">{clock}</span>}
      </div>
    </section>
  );
}
