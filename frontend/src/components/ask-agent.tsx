"use client";

import { type FormEvent, useState } from "react";

import { ApiError, askAgent, type ChatReply } from "@/lib/api";
import { hostOf } from "@/lib/labels";

type Turn = { question: string; reply?: ChatReply; error?: string };

export function AskAgent({ reportId }: { reportId: string }) {
  const [message, setMessage] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [sending, setSending] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const question = message.trim();
    if (!question) return;
    setSending(true);
    setMessage("");
    try {
      const reply = await askAgent(reportId, question);
      setTurns((t) => [...t, { question, reply }]);
    } catch (err) {
      const error =
        err instanceof ApiError && err.status === 429
          ? "You've used all your questions for this report."
          : err instanceof ApiError
            ? err.message
            : "The agent didn't answer. Try again.";
      setTurns((t) => [...t, { question, error }]);
    } finally {
      setSending(false);
    }
  }

  return (
    <section aria-labelledby="ask-title" className="mt-12">
      <h2 id="ask-title" className="font-display text-3xl font-bold">
        Ask the agent
      </h2>
      <p className="mt-2 text-graphite">Try it yourself. It answers only from this help center and shows its sources.</p>
      <ol className="mt-4 space-y-5" aria-live="polite">
        {turns.map((turn, i) => (
          <li key={i}>
            <p className="font-semibold">{turn.question}</p>
            {turn.error && <p className="text-notready">{turn.error}</p>}
            {turn.reply && (
              <>
                <p className="mt-1">{turn.reply.answer}</p>
                {turn.reply.citations.length > 0 && (
                  <p className="mt-1 text-sm text-graphite">
                    Sources:{" "}
                    {turn.reply.citations.map((c, j) => (
                      <span key={c.id}>
                        {j > 0 && ", "}
                        <a href={c.page_url}>{c.heading_path || hostOf(c.page_url)}</a>
                      </span>
                    ))}
                  </p>
                )}
              </>
            )}
          </li>
        ))}
      </ol>
      <form onSubmit={onSubmit} className="mt-4 flex flex-col gap-2 sm:flex-row">
        <label htmlFor="ask" className="sr-only">
          Your question
        </label>
        <input
          id="ask"
          value={message}
          maxLength={500}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="How long does shipping take?"
          className="min-w-0 flex-1 rounded-md border border-rule bg-field px-3 py-2.5 text-ink placeholder:text-graphite"
        />
        <button
          type="submit"
          disabled={sending || message.trim() === ""}
          className="rounded-md bg-accent px-5 py-2.5 font-semibold text-paper disabled:opacity-50"
        >
          {sending ? "Asking…" : "Ask"}
        </button>
      </form>
    </section>
  );
}
