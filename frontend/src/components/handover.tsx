"use client";

import { APP_NAME } from "@/lib/brand";
import type { Report } from "@/lib/api";

function download(filename: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = Object.assign(document.createElement("a"), { href: url, download: filename });
  // Some browsers start the download asynchronously: keep the link and URL alive briefly.
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export function Handover({ reportId, handover }: { reportId: string; handover: Report["handover"] }) {
  const base = `${APP_NAME.toLowerCase()}-${reportId.slice(0, 8)}`;
  return (
    <section aria-labelledby="handover-title" className="mt-12">
      <h2 id="handover-title" className="font-display text-3xl font-bold">
        Handover package
      </h2>
      <p className="mt-2 max-w-[62ch] text-graphite">
        For the team that will run the agent: the exact settings used, plus a document with what it covers,
        known failure modes, gaps to fix first and recommended guardrails.
      </p>
      <div className="mt-4 flex flex-wrap gap-3">
        <button
          type="button"
          onClick={() => download(`${base}-handover.md`, handover.markdown, "text/markdown")}
          className="rounded-md bg-accent px-4 py-2 font-semibold text-paper"
        >
          Download handover document
        </button>
        <button
          type="button"
          onClick={() => download(`${base}-config.json`, JSON.stringify(handover.config, null, 2), "application/json")}
          className="rounded-md border border-accent px-4 py-2 font-semibold text-accent"
        >
          Download config
        </button>
      </div>
    </section>
  );
}
