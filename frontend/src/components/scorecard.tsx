import type { Category, CategoryScore } from "@/lib/api";
import { CATEGORY_GOAL, CATEGORY_LABEL } from "@/lib/labels";

const ORDER: Category[] = ["answerable", "unanswerable", "out_of_scope", "injection"];

export function Scorecard({ categories }: { categories: Partial<Record<Category, CategoryScore>> }) {
  return (
    <section aria-labelledby="scorecard-title" className="mt-12">
      <h2 id="scorecard-title" className="font-display text-3xl font-bold">
        Scorecard
      </h2>
      <table className="mt-4 w-full border-collapse text-left">
        <caption className="sr-only">Exam results by question type</caption>
        <thead>
          <tr className="border-b border-ink text-sm text-graphite">
            <th scope="col" className="py-2 pr-4 font-semibold">Question type</th>
            <th scope="col" className="py-2 pr-4 text-right font-semibold">Passed</th>
            <th scope="col" className="w-1/4 py-2 font-semibold"><span className="sr-only">Pass rate</span></th>
          </tr>
        </thead>
        <tbody>
          {ORDER.filter((c) => categories[c]).map((category) => {
            const score = categories[category]!;
            const percent = Math.round(score.rate * 100);
            return (
              <tr key={category} className="border-b border-rule align-top">
                <th scope="row" className="py-3 pr-4 font-normal">
                  {CATEGORY_LABEL[category]}
                  <span className="block text-sm text-graphite">Goal: {CATEGORY_GOAL[category]}</span>
                </th>
                <td className="py-3 pr-4 text-right whitespace-nowrap">
                  {score.passed}/{score.total}
                </td>
                <td className="py-3">
                  <div className="mt-2 h-2 rounded-full bg-rule" aria-label={`${percent}% passed`} role="img">
                    <div
                      className={`h-full rounded-full ${percent >= 85 ? "bg-ready" : percent >= 60 ? "bg-needs" : "bg-notready"}`}
                      style={{ width: `${percent}%` }}
                    />
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
