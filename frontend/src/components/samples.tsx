"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { getSamples, type Sample } from "@/lib/api";
import { VERDICT_LABEL, hostOf } from "@/lib/labels";

export function Samples() {
  const [samples, setSamples] = useState<Sample[]>([]);

  useEffect(() => {
    getSamples().then(setSamples, () => setSamples([]));
  }, []);

  return (
    <section aria-labelledby="samples-title" className="mt-10">
      <h2 id="samples-title" className="font-semibold">
        Or open a sample report
      </h2>
      <ul className="mt-2 space-y-1">
        <li>
          <Link href="/demo">Northwind Supply Co.</Link>
          <span className="text-graphite"> (a made-up store&apos;s help center, saved report)</span>
        </li>
        {samples.map((s) => (
          <li key={s.report_id}>
            <Link href={`/reports/${s.report_id}`}>{hostOf(s.start_url)}</Link>
            <span className="text-graphite">
              {" "}
              ({VERDICT_LABEL[s.verdict]}, {Math.round(s.score)}/100)
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
