export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const HEALTH_TIMEOUT_MS = 5000;

export type BackendHealth = "ok" | "unreachable";

export async function fetchHealth(): Promise<BackendHealth> {
  try {
    const response = await fetch(`${API_URL}/api/health`, {
      signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS),
      cache: "no-store",
    });
    if (!response.ok) return "unreachable";
    const body: { status?: string } = await response.json();
    return body.status === "ok" ? "ok" : "unreachable";
  } catch {
    return "unreachable";
  }
}
