import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { DIMENSIONS, SUGGESTIONS } from "../constants";
import type { RubricCheck, RunDetails } from "../types";

const STEPS = [
  { name: "Input", text: "You give a topic. We assume you are starting from zero." },
  { name: "Generate", text: "Every part of the lesson is written at once, from checked facts." },
  { name: "Evaluate", text: "Hard pass or fail checks, with no partial credit." },
  { name: "Regenerate", text: "Anything that fails goes back with the reasons, and gets fixed." },
  { name: "Output", text: "You get the passing lesson, plus a log of what was rejected." },
];

function firstParagraph(markdown: string): string {
  const paragraph = markdown
    .split(/\n\s*\n/)
    .find((block) => block.trim() && !block.trim().startsWith("#") && !block.trim().startsWith(">"));
  return paragraph?.trim() ?? "";
}

function lessonTitle(markdown: string): string {
  return markdown.match(/^#\s+(.+)$/m)?.[1] ?? "Sample lesson";
}

interface Props {
  busy: boolean;
  error: string | null;
  rubric: RubricCheck[];
  onCreate: (topic: string) => void;
  onOpenRun: (run: RunDetails) => void;
}

export default function Landing({ busy, error, rubric, onCreate, onOpenRun }: Props) {
  const [topic, setTopic] = useState("");
  const [showEmpty, setShowEmpty] = useState(false);
  const [sample, setSample] = useState<RunDetails | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const runs = await api.runs();
      for (const candidate of runs.filter((run) => run.status === "shipped")) {
        const run = await api.run(candidate.run_id).catch(() => null);
        if (run) {
          if (!cancelled) setSample(run);
          return;
        }
      }
    }
    load().catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!topic.trim()) {
      setShowEmpty(true);
      return;
    }
    onCreate(topic.trim());
  }

  return (
    <div className="home">
      <header className="home-hero">
        <div className="container">
          <nav className="home-nav" aria-label="Main">
            <span className="logo">
              <span className="logo-mark" aria-hidden="true">L</span> LessonProof
            </span>
            <span className="home-links">
              <a href="#how">How it works</a>
              <a href="#checks">Quality checks</a>
              {sample && <a href="#sample">Sample lesson</a>}
            </span>
          </nav>

          <div className="hero-body">
            <h1>Understand any topic, even if you are starting from zero.</h1>
            <p className="hero-lead">
              Short lessons in plain English, with examples from everyday life in India. Written by
              AI, and only shown to you after passing {rubric.length || 23} quality checks.
            </p>

            <form id="run-form" className="topic-form" onSubmit={submit} noValidate>
              <label htmlFor="topic" className="sr-only">
                What do you want to learn?
              </label>
              <input
                id="topic"
                maxLength={200}
                autoComplete="off"
                placeholder="What do you want to learn?"
                value={topic}
                onChange={(event) => setTopic(event.target.value)}
              />
              <button type="submit" id="run-button" className="btn-accent" disabled={busy}>
                Create my lesson
              </button>
            </form>
            {showEmpty && !topic.trim() && (
              <p className="hero-error" role="alert">
                Please type a topic first.
              </p>
            )}
            {error && (
              <p className="hero-error" role="alert">
                {error}
              </p>
            )}

            <div className="suggestions" id="suggestions">
              <span>Try:</span>
              {SUGGESTIONS.map((suggestion) => (
                <button
                  type="button"
                  key={suggestion}
                  className="chip"
                  disabled={busy}
                  onClick={() => onCreate(suggestion)}
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        </div>
      </header>

      <main>
        <section className="home-section" id="how">
          <div className="container">
            <h2>How every lesson is made</h2>
            <ol className="how-grid">
              {STEPS.map((step, index) => (
                <li key={step.name}>
                  <span className="how-number">{index + 1}</span>
                  <h3>{step.name}</h3>
                  <p>{step.text}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="home-section tinted" id="checks">
          <div className="container">
            <h2>What a lesson must pass</h2>
            <p className="section-lead">One failed check sends it back. There is no partial credit.</p>
            <div className="check-grid">
              {DIMENSIONS.map((dimension) => {
                const checks = rubric.filter((c) => c.dimension === dimension.key);
                return (
                  <article key={dimension.key} className="check-card">
                    <h3>{dimension.title}</h3>
                    <ul>
                      {checks.map((check) => (
                        <li key={check.id}>{check.label}</li>
                      ))}
                    </ul>
                  </article>
                );
              })}
            </div>
          </div>
        </section>

        {sample?.lesson_markdown && (
          <section className="home-section" id="sample">
            <div className="container sample-grid">
              <div>
                <h2>See a finished lesson</h2>
                <p className="section-lead">
                  Read the approved lesson on RAG, along with the log of what was rejected on the
                  way there.
                </p>
                <button type="button" id="open-sample" className="btn-primary" onClick={() => onOpenRun(sample)}>
                  Read the sample lesson
                </button>
              </div>
              <button type="button" className="sample-card" onClick={() => onOpenRun(sample)}>
                <span className="pill-pass">Passed every check</span>
                <span className="sample-title">{lessonTitle(sample.lesson_markdown)}</span>
                <span className="sample-text">{firstParagraph(sample.lesson_markdown)}</span>
              </button>
            </div>
          </section>
        )}
      </main>

      <footer className="home-footer">
        <div className="container">LessonProof. Built with LangGraph, FastAPI, and React.</div>
      </footer>
    </div>
  );
}
