import { CheckForm } from "@/components/check-form";
import { Samples } from "@/components/samples";

const STEPS = [
  "Read your help center, up to 40 pages.",
  "Build a support agent that answers only from those pages and cites them.",
  "Give it an exam: real customer questions, questions your docs don't answer, off-topic requests and prompt-injection attempts.",
  "Grade every answer and write the report: a go/no-go verdict, what failed and why, gaps in your docs, and a handover package.",
];

export default function Home() {
  return (
    <main className="mx-auto max-w-[46rem] px-5 pt-14 pb-16 sm:pt-20">
      <h1 className="font-display text-[2.75rem] leading-[1.02] font-extrabold sm:text-[3.8rem]">
        Is your support agent ready to go live?
      </h1>
      <p className="mt-5 max-w-[60ch] text-lg text-graphite">
        Paste your help center&apos;s address. We build a support agent from it, put it through a
        24-question exam, and tell you whether it&apos;s safe to deploy and what to fix first.
      </p>
      <CheckForm />
      <Samples />
      <section aria-labelledby="how-title" className="mt-14 border-t border-rule pt-8">
        <h2 id="how-title" className="font-display text-3xl font-bold">
          How a check works
        </h2>
        <ol className="mt-4 list-decimal space-y-2 pl-6 marker:text-graphite">
          {STEPS.map((step) => (
            <li key={step} className="max-w-[62ch] pl-1">
              {step}
            </li>
          ))}
        </ol>
        <p className="mt-4 text-graphite">A check takes about two minutes.</p>
      </section>
    </main>
  );
}
