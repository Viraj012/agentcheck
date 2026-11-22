"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Notice } from "@/components/notice";
import { ApiError, getRun, type RunStatus } from "@/lib/api";
import { PHASES, asSentence } from "@/lib/labels";

const POLL_MS = 2000;

export function RunProgress() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [run, setRun] = useState<RunStatus | null>(null);
  const [problem, setProblem] = useState<"missing" | "offline" | null>(null);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await getRun(id);
        if (stopped) return;
        setRun(next);
        setProblem(null);
        if (next.status === "done" && next.report_id) {
          router.replace(`/reports/${next.report_id}`);
          return;
        }
        if (next.status === "failed" || next.status === "needs_js") return;
      } catch (err) {
        if (stopped) return;
        if (err instanceof ApiError && err.status === 404) {
          setProblem("missing");
          return;
        }
        setProblem("offline");
      }
      timer = setTimeout(poll, POLL_MS);
    }
    poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [id, router]);

  if (problem === "missing") {
    return <Notice title="We can't find that check" tone="problem">The link may be wrong, or the check was removed.</Notice>;
  }
  if (run?.status === "needs_js") {
    return (
      <Notice title="We couldn't read this site" tone="problem">
        {asSentence(run.error ?? "")} Try the site&apos;s docs or support pages directly, or another help center.
      </Notice>
    );
  }
  if (run?.status === "failed") {
    return (
      <Notice title="The check didn't finish" tone="problem">
        {asSentence(run.error ?? "Something went wrong")} Try again in a few minutes.
      </Notice>
    );
  }

  const current = PHASES.findIndex((p) => p.key === run?.phase);
  const percent = Math.round((run?.progress ?? 0) * 100);
  return (
    <>
      <h1 className="font-display text-4xl font-extrabold sm:text-5xl">Checking the help center</h1>
      <p className="mt-2 text-graphite" aria-live="polite">
        {!run && "Loading…"}
        {run?.status === "queued" && "Waiting in line. Another check is running; yours starts next."}
        {run?.status === "running" && "This takes about two minutes. You can leave this page open; the report opens by itself."}
      </p>
      {problem === "offline" && (
        <p role="status" className="mt-2 text-needs">
          Lost contact with the server. Retrying…
        </p>
      )}
      <div
        role="progressbar"
        aria-label="Check progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        className="mt-6 h-2 overflow-hidden rounded-full bg-rule"
      >
        <div className="h-full bg-accent transition-[width] duration-700 motion-reduce:transition-none" style={{ width: `${percent}%` }} />
      </div>
      <ol className="mt-6 space-y-3">
        {PHASES.map((phase, index) => {
          const state = run?.status === "running" ? (index < current ? "done" : index === current ? "now" : "next") : "next";
          return (
            <li key={phase.key} className="flex items-center gap-3" aria-current={state === "now" ? "step" : undefined}>
              <StepMark state={state} />
              <span className={state === "now" ? "font-semibold" : state === "done" ? "" : "text-graphite"}>
                {phase.label}
                <span className="sr-only">{state === "done" ? " (done)" : state === "now" ? " (in progress)" : ""}</span>
              </span>
            </li>
          );
        })}
      </ol>
    </>
  );
}

function StepMark({ state }: { state: "done" | "now" | "next" }) {
  if (state === "done") {
    return (
      <svg aria-hidden="true" viewBox="0 0 20 20" className="size-5 text-ready">
        <circle cx="10" cy="10" r="9" fill="currentColor" />
        <path d="M6 10.5l2.5 2.5L14 7.5" stroke="var(--paper)" strokeWidth="2" fill="none" />
      </svg>
    );
  }
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20" className={`size-5 ${state === "now" ? "text-accent" : "text-rule"}`}>
      <circle cx="10" cy="10" r="8" stroke="currentColor" strokeWidth="2.5" fill={state === "now" ? "currentColor" : "none"} />
    </svg>
  );
}
