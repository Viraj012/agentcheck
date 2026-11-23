"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { AskAgent } from "@/components/ask-agent";
import { Failures } from "@/components/failures";
import { Gaps } from "@/components/gaps";
import { Handover } from "@/components/handover";
import { Notice } from "@/components/notice";
import { Scorecard } from "@/components/scorecard";
import { ShareLink } from "@/components/share-link";
import { ApiError, getReport, type Report } from "@/lib/api";
import { VERDICT_COLOR, VERDICT_LABEL, VERDICT_MEANING, hostOf } from "@/lib/labels";

export function ReportView() {
  const { id } = useParams<{ id: string }>();
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    getReport(id).then(setReport, (err) => setError(err instanceof ApiError ? err : new ApiError(0, "")));
  }, [id]);

  if (error?.status === 404) {
    return <Notice title="This report doesn't exist" tone="problem">The link may be wrong, or the check hasn&apos;t finished yet.</Notice>;
  }
  if (error) {
    return <Notice title="The report didn't load" tone="problem">{error.message} Reload the page to try again.</Notice>;
  }
  if (!report) return <p className="text-graphite" role="status">Loading the report…</p>;
  return <ReportBody report={report} />;
}

/** The report itself. A saved demo report has no live agent behind it, so it can't be chatted with. */
export function ReportBody({ report, demo = false }: { report: Report; demo?: boolean }) {
  const summary = report.category_scores;
  const finished = new Date(report.finished_at).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" });
  return (
    <article>
      <p className="text-graphite">
        Readiness report for{" "}
        {demo ? hostOf(report.start_url) : <a href={report.start_url}>{hostOf(report.start_url)}</a>}, checked{" "}
        {finished}
      </p>
      <h1 className="sr-only">Readiness report: {VERDICT_LABEL[report.verdict]}</h1>
      <div className="mt-6 flex flex-wrap items-end gap-x-8 gap-y-4">
        <div className={`stamp ${VERDICT_COLOR[report.verdict]}`} aria-hidden="true">
          {VERDICT_LABEL[report.verdict].toUpperCase()}
        </div>
        <p className="font-display text-5xl leading-none font-extrabold">
          {Math.round(report.score)}
          <span className="text-2xl text-graphite">/100</span>
          <span className="sr-only"> overall score</span>
        </p>
      </div>
      <p className="mt-6 max-w-[62ch] text-lg">{VERDICT_MEANING[report.verdict]}</p>
      <p className="mt-2 max-w-[62ch] text-graphite">
        Answered {Math.round(summary.answerable_accuracy * 100)}% of documented questions correctly.{" "}
        {summary.hallucinations === 0
          ? "Made up no facts."
          : `Made up facts ${summary.hallucinations} ${summary.hallucinations === 1 ? "time" : "times"}.`}{" "}
        {summary.injection_tested === false
          ? "No injection attempts were tested."
          : summary.injection_all_pass
            ? "Resisted every injection attempt."
            : "Followed at least one injected instruction."}
      </p>

      <Scorecard categories={summary.categories} />
      <Failures failures={report.failures} />
      <Gaps gaps={report.gaps} />
      <Handover reportId={report.report_id} handover={report.handover} />
      {!demo && <AskAgent reportId={report.report_id} />}

      <footer className="mt-14 flex flex-wrap items-center justify-between gap-4 border-t border-rule pt-6 text-sm text-graphite">
        <p>
          Checked {report.usage.pages} pages using {report.usage.llm_calls} AI calls (
          {(report.usage.input_tokens + report.usage.output_tokens).toLocaleString()} tokens).
        </p>
        <ShareLink />
      </footer>
    </article>
  );
}
