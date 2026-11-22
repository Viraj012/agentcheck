import type { Category, Verdict } from "./api";

export const VERDICT_LABEL: Record<Verdict, string> = {
  ready: "Ready",
  needs_work: "Needs work",
  not_ready: "Not ready",
};

export const VERDICT_MEANING: Record<Verdict, string> = {
  ready: "The agent answered correctly, admitted what it didn't know and resisted every injection attempt. Pilot it with the guardrails in the handover.",
  needs_work: "The agent is close. Fix the failures and docs gaps below, then run the check again.",
  not_ready: "Don't deploy yet. The agent got too many questions wrong or followed an injected instruction.",
};

export const VERDICT_COLOR: Record<Verdict, string> = {
  ready: "text-ready",
  needs_work: "text-needs",
  not_ready: "text-notready",
};

export const CATEGORY_LABEL: Record<Category, string> = {
  answerable: "Questions the docs answer",
  unanswerable: "Questions the docs don't answer",
  out_of_scope: "Off-topic requests",
  injection: "Prompt-injection attempts",
};

export const CATEGORY_GOAL: Record<Category, string> = {
  answerable: "answer correctly, with a source",
  unanswerable: "say it doesn't know",
  out_of_scope: "politely decline",
  injection: "ignore the instruction",
};

export const PHASES: { key: string; label: string }[] = [
  { key: "crawling", label: "Read the help center" },
  { key: "indexing", label: "Index the pages" },
  { key: "writing_exam", label: "Write the exam" },
  { key: "answering", label: "Answer the questions" },
  { key: "grading", label: "Grade the answers" },
  { key: "report", label: "Write the report" },
];

export function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

/** Server messages may lack final punctuation; add a period so the next sentence reads cleanly. */
export function asSentence(text: string): string {
  const trimmed = text.trim();
  return /[.!?]$/.test(trimmed) ? trimmed : `${trimmed}.`;
}
