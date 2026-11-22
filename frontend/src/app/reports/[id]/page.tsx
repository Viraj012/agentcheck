import type { Metadata } from "next";
import { Suspense } from "react";

import { ReportView } from "@/components/report-view";

export const metadata: Metadata = { title: "Readiness report" };

export default function ReportPage() {
  return (
    <main className="mx-auto max-w-[46rem] px-5 pt-12 pb-16">
      <Suspense fallback={<p className="text-graphite">Loading the report…</p>}>
        <ReportView />
      </Suspense>
    </main>
  );
}
