import type { Failure } from "@/lib/api";
import { CATEGORY_LABEL, hostOf } from "@/lib/labels";

const VERDICT_TEXT: Record<string, string> = {
  incorrect: "Wrong answer",
  partial: "Partly right",
  hallucinated: "Made up facts",
  fail: "Failed",
};

export function Failures({ failures }: { failures: Failure[] }) {
  return (
    <section aria-labelledby="failures-title" className="mt-12">
      <h2 id="failures-title" className="font-display text-3xl font-bold">
        Where it went wrong
      </h2>
      {failures.length === 0 ? (
        <p className="mt-2 text-graphite">Nothing. Every exam question was handled as expected.</p>
      ) : (
        <>
          <p className="mt-2 text-graphite">
            {failures.length} of the exam questions. Open one to see the answer, the grader&apos;s reason and what search found.
          </p>
          <ul className="mt-4 border-t border-rule">
            {failures.map((f) => (
              <li key={f.test_case_id} className="border-b border-rule">
                <details className="group py-3">
                  <summary className="cursor-pointer">
                    <span className="mr-2 font-semibold text-notready">{VERDICT_TEXT[f.verdict] ?? f.verdict}</span>
                    <span>{f.question}</span>
                    <span className="block text-sm text-graphite">{CATEGORY_LABEL[f.category]}</span>
                  </summary>
                  <dl className="mt-3 space-y-3 pl-4 text-[0.95rem]">
                    <Field term="The agent said">{f.answer}</Field>
                    {f.reference_answer && <Field term="The docs say">{f.reference_answer}</Field>}
                    {f.judge_reason && <Field term="Why it failed">{f.judge_reason}</Field>}
                    {f.category === "answerable" && (
                      <Field term="Search">
                        {f.retrieval_miss
                          ? "Didn't find the page that answers this. The content exists but is hard to find."
                          : "Found the right page; the agent misused it."}
                      </Field>
                    )}
                    {f.retrieved.length > 0 && (
                      <Field term="What search gave the agent">
                        <ol className="mt-1 list-decimal space-y-2 pl-5">
                          {f.retrieved.map((p) => (
                            <li key={p.id}>
                              <a href={p.page_url}>{hostOf(p.page_url) + new URL(p.page_url).pathname}</a>
                              {p.heading_path && <span className="text-graphite"> ({p.heading_path})</span>}
                              <p className="mt-0.5 line-clamp-3 text-graphite">{p.text.replace(/^#+\s*/gm, "")}</p>
                            </li>
                          ))}
                        </ol>
                      </Field>
                    )}
                  </dl>
                </details>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function Field({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-sm font-semibold text-graphite">{term}</dt>
      <dd>{children}</dd>
    </div>
  );
}
