import type { Report } from "@/lib/api";

export function Gaps({ gaps }: { gaps: Report["gaps"] }) {
  return (
    <section aria-labelledby="gaps-title" className="mt-12">
      <h2 id="gaps-title" className="font-display text-3xl font-bold">
        Gaps in your docs
      </h2>
      <h3 className="mt-5 font-semibold">Missing: customers will ask, the docs don&apos;t say</h3>
      {gaps.missing_content.length === 0 ? (
        <p className="text-graphite">None found.</p>
      ) : (
        <ul className="mt-2 space-y-4">
          {gaps.missing_content.map((t) => (
            <li key={t.topic}>
              <p className="font-semibold">{t.topic}</p>
              <p className="text-graphite">{t.suggestion}</p>
              <ul className="mt-1 list-disc pl-5 text-[0.95rem]">
                {t.questions.map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
      <h3 className="mt-6 font-semibold">Hard to find: the answer exists, but search missed it</h3>
      {gaps.hard_to_find.length === 0 ? (
        <p className="text-graphite">None found.</p>
      ) : (
        <ul className="mt-2 list-disc space-y-2 pl-5">
          {gaps.hard_to_find.map((h) => (
            <li key={h.test_case_id}>
              {h.question}{" "}
              {h.page_url && (
                <span className="text-graphite">
                  Answered at <a href={h.page_url}>{h.page_url}</a>
                  {h.heading_path && ` under "${h.heading_path}"`}. Give it a clearer heading or its own page.
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
