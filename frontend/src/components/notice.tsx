import Link from "next/link";
import type { ReactNode } from "react";

export function Notice({ title, children, tone = "plain" }: { title: string; children: ReactNode; tone?: "plain" | "problem" }) {
  return (
    <div role={tone === "problem" ? "alert" : "status"} className="mt-8 border-l-4 border-rule pl-4 data-[tone=problem]:border-notready" data-tone={tone}>
      <h2 className="font-display text-2xl font-bold">{title}</h2>
      <div className="mt-1 max-w-[62ch] text-graphite">{children}</div>
      <p className="mt-3">
        <Link href="/">Check another help center</Link>
      </p>
    </div>
  );
}
