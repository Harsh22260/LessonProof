export type StageKey = "input" | "generate" | "evaluate" | "regenerate" | "output";

export const PIPELINE: { key: StageKey; label: string; target: string }[] = [
  { key: "input", label: "INPUT", target: "run-form" },
  { key: "generate", label: "GENERATE", target: "stage-generate" },
  { key: "evaluate", label: "EVALUATE", target: "stage-evaluate" },
  { key: "regenerate", label: "REGENERATE", target: "stage-regenerate" },
  { key: "output", label: "OUTPUT", target: "stage-output" },
];

export const STEP_INFO: Record<string, { stage: StageKey; note: string }> = {
  load_context: { stage: "input", note: "Gathering the facts for your topic." },
  plan_lesson: { stage: "generate", note: "Planning the lesson and choosing a familiar example." },
  write_lesson: { stage: "generate", note: "Writing all parts at the same time." },
  evaluate_lesson: { stage: "evaluate", note: "Checking accuracy, language, and examples." },
  revise_lesson: { stage: "regenerate", note: "Sending the reasons back and fixing what failed." },
  finalize_run: { stage: "output", note: "Finishing up." },
  learn: { stage: "output", note: "Saving what this run taught the system." },
};

export const PARTS = [
  { role: "intro", label: "Welcome" },
  { role: "what", label: "What it is" },
  { role: "why", label: "Why it matters" },
  { role: "how", label: "How it works" },
  { role: "example", label: "Worked example" },
  { role: "limits", label: "Limits" },
  { role: "recap", label: "Recap" },
];

export const DIMENSIONS = [
  { key: "accuracy", title: "Accurate and grounded" },
  { key: "beginner_language", title: "Beginner-friendly language" },
  { key: "examples", title: "Teaches by example" },
  { key: "clarity", title: "Clear, no unexplained jargon" },
  { key: "coverage", title: "Covers the key points" },
  { key: "flow", title: "Coherent teaching flow" },
];

export const SUGGESTIONS = [
  "Introduction to RAG (Retrieval-Augmented Generation)",
  "What is machine learning?",
  "What is a neural network?",
];
