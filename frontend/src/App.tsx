import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { api, followJob } from "./api";
import { AcrossPipeline, EvaluatorTest } from "./components/AcrossPipeline";
import Landing from "./components/Landing";
import OutputStage from "./components/OutputStage";
import Pipeline from "./components/Pipeline";
import { ChecksPanel, PartsPanel, RetriesPanel } from "./components/Stages";
import { initialRunState, runReducer } from "./runState";
import type { Config, RunDetails, RunEvent } from "./types";

export default function App() {
  const [state, dispatch] = useReducer(runReducer, initialRunState);
  const [config, setConfig] = useState<Config | null>(null);
  const [screen, setScreen] = useState<"home" | "lesson">("home");
  const [topic, setTopic] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [testBusy, setTestBusy] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const stopFollowing = useRef<(() => void) | null>(null);

  const busy = state.running || testBusy;

  const follow = useCallback((jobId: string) => {
    stopFollowing.current?.();
    stopFollowing.current = followJob<RunEvent>(
      jobId,
      (event) => dispatch({ type: "event", event }),
      () => setRefreshKey((key) => key + 1),
    );
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .config()
      .then((nextConfig) => {
        if (cancelled) return;
        setConfig(nextConfig);
        if (nextConfig.active_job) {
          dispatch({ type: "start", now: Date.now() });
          setScreen("lesson");
          follow(nextConfig.active_job);
        }
      })
      .catch((loadError: Error) => setError(loadError.message));
    return () => {
      cancelled = true;
      stopFollowing.current?.();
    };
  }, [follow]);

  useEffect(() => {
    document.body.dataset.running = String(state.running);
  }, [state.running]);

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" });
  }, [screen]);

  const labelFor = useCallback(
    (id: string) => config?.rubric.find((check) => check.id === id)?.label || id,
    [config],
  );

  async function begin(nextTopic: string, regenerate: boolean) {
    setError(null);
    setTopic(nextTopic);
    setScreen("lesson");
    dispatch({ type: "start", now: Date.now() });
    try {
      const { job_id: jobId } = await api.startRun(nextTopic, regenerate);
      follow(jobId);
    } catch (startError) {
      dispatch({ type: "start_failed" });
      setScreen("home");
      setError((startError as Error).message);
    }
  }

  function openRun(run: RunDetails) {
    setTopic(run.topic);
    dispatch({ type: "show_saved", run });
    setScreen("lesson");
  }

  function goHome() {
    setScreen("home");
  }

  const rubric = config?.rubric ?? [];
  const stopped = ["quota", "service_busy", "setup"].includes(state.outcome);

  if (screen === "home") {
    return <Landing busy={busy} error={error} rubric={rubric} onCreate={(t) => begin(t, false)} onOpenRun={openRun} />;
  }

  return (
    <div className="workspace">
      <header className="topbar">
        <div className="container topbar-row">
          <button type="button" className="logo logo-button" onClick={goHome} disabled={state.running}>
            <span className="logo-mark" aria-hidden="true">L</span> LessonProof
          </button>
          <p className="topbar-topic" title={topic}>
            {topic}
          </p>
          <button type="button" id="new-topic" className="btn-outline btn-small" onClick={goHome} disabled={state.running}>
            New topic
          </button>
        </div>
      </header>

      <div className="container">
        <Pipeline
          stage={state.stage}
          allDone={state.allDone}
          note={state.note}
          startedAt={state.startedAt}
          seconds={state.seconds}
        />
        <div className={`columns ${stopped ? "columns-single" : ""}`}>
          <main className="main-column">
            <OutputStage
              state={state}
              labelFor={labelFor}
              onRegenerate={() => begin(state.run?.topic ?? topic, true)}
              onNewTopic={goHome}
              memoryPanel={<AcrossPipeline refreshKey={refreshKey} labelFor={labelFor} />}
              testPanel={
                <EvaluatorTest
                  defects={config?.defects ?? []}
                  hasLesson={config?.has_passing_lesson ?? false}
                  busy={busy}
                  onBusyChange={setTestBusy}
                  labelFor={labelFor}
                />
              }
            />
          </main>
          {!stopped && (
            <aside className="side-column" aria-label="Progress details">
              <PartsPanel parts={state.parts} />
              <ChecksPanel rubric={rubric} results={state.results} />
              <RetriesPanel log={state.log} maxRetries={config?.max_retries ?? 2} labelFor={labelFor} />
            </aside>
          )}
        </div>
      </div>
    </div>
  );
}
