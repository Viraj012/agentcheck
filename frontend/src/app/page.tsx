import { APP_NAME } from "@/lib/brand";

import { HealthStatus } from "./health-status";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-4 px-4 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">{APP_NAME}</h1>
      <p className="text-zinc-600">
        Paste a help-center URL and get a deployment-readiness report for an AI support agent.
      </p>
      <HealthStatus />
    </main>
  );
}
