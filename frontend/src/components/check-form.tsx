"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { Turnstile } from "@/components/turnstile";

import { ApiError, createRun, wakeServer } from "@/lib/api";

type ServerState = "unknown" | "waking" | "up" | "down";

export function CheckForm() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [server, setServer] = useState<ServerState>("unknown");
  const [token, setToken] = useState<string | null>(null);
  const [resetKey, setResetKey] = useState(0);

  useEffect(() => {
    const slow = setTimeout(() => setServer((s) => (s === "unknown" ? "waking" : s)), 2500);
    wakeServer().then((up) => setServer(up ? "up" : "down"));
    return () => clearTimeout(slow);
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const reply = await createRun(url, token);
      router.push("report_id" in reply ? `/reports/${reply.report_id}` : `/runs/${reply.run_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Try again.");
      setSubmitting(false);
      setResetKey((k) => k + 1);
    }
  }

  return (
    <form onSubmit={onSubmit} className="mt-8" noValidate>
      <label htmlFor="url" className="block font-semibold">
        Help center URL
      </label>
      <p id="url-hint" className="text-sm text-graphite">
        A public help center or docs site, for example https://help.example.com
      </p>
      <div className="mt-2 flex flex-col gap-2 sm:flex-row">
        <input
          id="url"
          name="url"
          type="url"
          inputMode="url"
          autoComplete="url"
          required
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          aria-describedby={error ? "url-hint url-error" : "url-hint"}
          aria-invalid={error ? true : undefined}
          placeholder="https://"
          className="min-w-0 flex-1 rounded-md border border-rule bg-field px-3 py-2.5 text-ink placeholder:text-graphite"
        />
        <button
          type="submit"
          disabled={submitting || url.trim() === "" || token === null}
          className="rounded-md bg-accent px-5 py-2.5 font-semibold text-paper disabled:opacity-50"
        >
          {submitting ? "Starting…" : "Run the check"}
        </button>
      </div>
      <Turnstile onToken={setToken} resetKey={resetKey} />
      {error && (
        <p id="url-error" role="alert" className="mt-2 text-notready">
          {error}
        </p>
      )}
      <p aria-live="polite" className="mt-2 min-h-6 text-sm text-graphite">
        {server === "waking" && "Starting the server. Free hosting sleeps when idle, so this can take up to a minute."}
        {server === "down" && "The server isn't responding right now. You can still try; it may be waking up."}
      </p>
    </form>
  );
}
