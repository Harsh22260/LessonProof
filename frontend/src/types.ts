export interface RubricCheck {
  id: string;
  label: string;
  dimension: string;
  kind: string;
  criterion: string;
}

export interface Defect {
  id: string;
  expected_check: string;
  description: string;
}

export interface Config {
  default_topic: string;
  writer_model: string;
  judge_model: string;
  max_retries: number;
  rubric: RubricCheck[];
  defects: Defect[];
  has_passing_lesson: boolean;
  active_job: string | null;
}

export interface CheckResult {
  check_id: string;
  dimension: string;
  passed: boolean;
  reason: string;
  fix: string;
  evidence: string[];
}

export interface EvaluationReport {
  attempt: number;
  results: CheckResult[];
  complete: boolean;
  reused_checks: string[];
}

export interface ChangeNote {
  check_id: string;
  change: string;
}

export interface Revision {
  sections_changed: string[];
  notes: ChangeNote[];
}

export interface AttemptRecord {
  attempt: number;
  report: EvaluationReport;
  revision: Revision | null;
  code_fixes: string[];
  repaired_rule_failures: CheckResult[];
}

export interface Section {
  role: string;
  heading: string;
  body: string;
}

export interface Lesson {
  title: string;
  sections: Section[];
}

export interface RunDetails {
  run_id: string;
  topic: string;
  status: "shipped" | "rejected";
  grounding: string;
  attempts: AttemptRecord[];
  lesson_markdown?: string;
  evolution_events: string[];
  seconds?: number;
  from_saved?: boolean;
}

export interface RunSummary {
  run_id: string;
  topic: string;
  status: string;
  attempts: number;
}

export interface Guideline {
  check_id: string;
  text: string;
}

export interface Memory {
  guidelines: Guideline[];
}

export interface InjectionResult {
  defect: Defect;
  caught: boolean;
  report: EvaluationReport;
}

export type RunEvent =
  | { event: "step_started"; step: string }
  | { event: "section_ready"; section: Section }
  | { event: "draft_ready"; lesson: Lesson }
  | { event: "checks_done"; results: CheckResult[] }
  | { event: "attempt"; record: AttemptRecord }
  | { event: "starting_over" }
  | ({ event: "preview" } & RunDetails)
  | ({ event: "finished" } & RunDetails)
  | { event: "failed"; message: string; reason: string; retry_after: number | null }
  | { event: "closed" };
