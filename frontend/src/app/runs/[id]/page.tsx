import type { Metadata } from "next";
import { Suspense } from "react";

import { RunProgress } from "@/components/run-progress";

export const metadata: Metadata = { title: "Checking" };

export default function RunPage() {
  return (
    <main className="mx-auto max-w-[46rem] px-5 pt-12 pb-16">
      <Suspense fallback={<p className="text-graphite">Loading…</p>}>
        <RunProgress />
      </Suspense>
    </main>
  );
}
