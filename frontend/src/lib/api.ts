export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type RunState = "queued" | "running" | "needs_js" | "failed" | "done";
export type Verdict = "ready" | "needs_work" | "not_ready";
export type Category = "answerable" | "unanswerable" | "out_of_scope" | "injection";

export type RunStatus = {
  run_id: string;
  status: RunState;
  phase: string | null;
  progress: number;
  error: string | null;
  report_id: string | null;
};

export type RetrievedPassage = { id: number; page_url: string; heading_path: string; text: string };

export type Failure = {
  test_case_id: number;
  category: Category;
  question: string;
  reference_answer: string | null;
  answer: string;
  abstained: boolean;
  verdict: string;
  judge_reason: string | null;
  retrieval_miss: boolean;
  retrieved: RetrievedPassage[];
};

export type CategoryScore = { total: number; passed: number; rate: number };

export type Report = {
  report_id: string;
  start_url: string;
  finished_at: string;
  score: number;
  verdict: Verdict;
  category_scores: {
    categories: Partial<Record<Category, CategoryScore>>;
    answerable_accuracy: number;
    hallucinations: number;
    injection_all_pass: boolean;
  };
  failures: Failure[];
  gaps: {
    missing_content: { topic: string; suggestion: string; questions: string[] }[];
    hard_to_find: { test_case_id: number; question: string; page_url: string | null; heading_path: string | null }[];
  };
  handover: { config: Record<string, unknown>; markdown: string };
  usage: { pages: number; llm_calls: number; input_tokens: number; output_tokens: number };
};

export type Sample = { report_id: string; start_url: string; verdict: Verdict; score: number };

export type ChatReply = {
  answer: string;
  abstained: boolean;
  citations: { id: number; page_url: string; title: string; heading_path: string }[];
};

export type CreateRunReply = { run_id: string } | { report_id: string; cached: true };

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const UNREACHABLE = "Can't reach the server. Check your connection and try again.";

async function request<T>(path: string, init?: RequestInit, timeoutMs = 20000): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      // Only requests with a body declare JSON, so GETs stay "simple" and skip the CORS preflight.
      headers: init?.body ? { "Content-Type": "application/json", ...init.headers } : init?.headers,
      signal: AbortSignal.timeout(timeoutMs),
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, UNREACHABLE);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : `Request failed (${response.status}).`;
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export const createRun = (url: string, turnstileToken: string | null) =>
  request<CreateRunReply>("/api/runs", {
    method: "POST",
    body: JSON.stringify({ url, turnstile_token: turnstileToken }),
  });
export const getRun = (id: string) => request<RunStatus>(`/api/runs/${id}`);
export const getReport = (id: string) => request<Report>(`/api/reports/${id}`);
export const getSamples = () => request<Sample[]>("/api/samples");
export const askAgent = (id: string, message: string) =>
  request<ChatReply>(`/api/reports/${id}/chat`, { method: "POST", body: JSON.stringify({ message }) }, 60000);

/** Free hosting sleeps when idle; the first request can take up to a minute. */
export async function wakeServer(): Promise<boolean> {
  try {
    await request<{ status: string }>("/api/health", undefined, 90000);
    return true;
  } catch {
    return false;
  }
}
