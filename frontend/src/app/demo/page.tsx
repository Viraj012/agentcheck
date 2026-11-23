import type { Metadata } from "next";

import { ReportBody } from "@/components/report-view";
import type { Report } from "@/lib/api";
import demo from "@/lib/demo-report.json";

export const metadata: Metadata = { title: "Sample report" };

export default function DemoPage() {
  return (
    <main className="mx-auto max-w-[46rem] px-5 pt-12 pb-16">
      <p className="mb-8 border-l-4 border-rule pl-4 text-graphite">
        This is a saved report from a real check of Northwind Supply Co., a made-up store&apos;s help center
        that ships with the project, with planted gaps and a hidden prompt injection. It loads without the
        server, so the chat with the agent is turned off here.
      </p>
      <ReportBody report={demo as Report} demo />
    </main>
  );
}
