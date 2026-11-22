# AgentCheck

Paste a help center's URL and find out whether an AI support agent built on it is safe to put in front of customers.

**Live demo: [agentcheck-vert.vercel.app](https://agentcheck-vert.vercel.app/)** (the free backend sleeps when idle, so the first check can take a minute to start)

AgentCheck crawls the help center, builds a grounded support agent from it, writes an exam for that agent, grades every answer, and produces a deployment-readiness report: a go/no-go verdict, the failures with reasons, gaps in the docs, and a handover package for the team that will run the agent.

## Why

Building a support bot on top of a help center takes an afternoon. Knowing whether it's ready to talk to customers is the hard part. Will it answer correctly? Will it make up a refund policy? Will it admit when the docs don't cover something? Will a sentence planted in a web page talk it into saying everything is free?

Those questions usually get answered by someone poking at the bot for an hour. AgentCheck answers them with a repeatable, graded exam in about two minutes.

## What the report shows

- **Verdict:** Ready, Needs work or Not ready, with an overall score. Ready requires at least 85% of documented questions answered correctly, no made-up facts, and every injection attempt resisted.
- **Scorecard** for four kinds of questions:
  - questions the docs answer (should answer correctly, with a source)
  - questions the docs don't answer (should say it doesn't know)
  - off-topic requests (should decline)
  - prompt-injection attempts (should ignore them)
- **Failures:** each one with the agent's answer, what the docs say, the grader's reason, and the passages search actually gave the agent. That separates "the docs are missing this", "the docs have it but search can't find it", and "search found it and the agent still got it wrong", which need different fixes.
- **Docs gaps:** topics customers will ask about that the docs never cover, and answers that exist but are hard to find.
- **Handover package:** the exact settings used (JSON) and a Markdown document with coverage, known failure modes, gaps to fix first and recommended guardrails.
- **Ask the agent:** a chat box to try the agent yourself, with sources on every answer.

## How it works

```
URL ─▶ crawl ─▶ index ─▶ write exam ─▶ answer ─▶ grade ─▶ report
        │         │          │            │         │         │
   SSRF guard  chunks by  24 questions  hybrid    LLM judge  verdict, gaps,
   robots.txt  heading,   from sampled  search +  with a     handover
   ≤ 40 pages  embedded   pages         grounded  rubric per
                          (one call)    agent     category
```

1. **Crawl.** Every request goes through an SSRF guard: the host is resolved, every address must be public, the connection is pinned to the checked IP, and every redirect is checked again. The crawler respects robots.txt, reads the sitemap or follows links on the same site, and extracts the main text with trafilatura.
2. **Index.** Pages are split along their headings into chunks of about 500 tokens, embedded with Gemini, and stored in Postgres with pgvector plus a full-text index.
3. **Exam.** One LLM call writes 14 questions from chunks sampled across the whole site, 6 plausible questions the docs don't answer, 2 off-topic requests and 2 injection attempts.
4. **Answer.** For each question, hybrid search (full-text and vector, fused with Reciprocal Rank Fusion) picks the top 6 chunks. The agent answers only from those, cites chunk ids, and abstains when the context doesn't support an answer. Retrieved text is escaped inside tags, and the prompt tells the model it is untrusted data.
5. **Grade.** An LLM judge grades each answer against a written rubric per category. Code checks that citations point at retrieved chunks and whether search found the question's source chunk at all.
6. **Report.** Scores, verdict, docs gaps and the handover package.

A run takes about 10 LLM calls, because everything is batched: one call writes the exam, one embeds all the questions, and answers and grades go 8 per call. That keeps it inside the Gemini free tier.

## Design choices

- **Postgres does everything.** It stores the data, runs vector and full-text search, and is the job queue: workers claim runs with `SELECT … FOR UPDATE SKIP LOCKED`, and a heartbeat lets an interrupted run be picked up again or failed cleanly. No Redis, one database, one service.
- **Hybrid retrieval with RRF.** Embeddings catch paraphrases; full-text catches exact terms. Reciprocal Rank Fusion combines the two rankings without tuning weights.
- **The LLM sits behind an interface.** `LLMClient` has a Gemini implementation and a deterministic fake that every test uses. Gemini calls go through a token-bucket rate limiter, retries with backoff and jitter, a per-run call cap and a request timeout.
- **Abuse protection.** A Cloudflare Turnstile check, per-visitor and global daily limits (enforced atomically with an advisory lock), a daily chat cap, and a cache for URLs checked recently.
- **Same agent everywhere.** The chat and the exam use the same answering code, so what gets graded is what users talk to.

## Evaluation

**Retrieval** (`scripts/retrieval_eval.py`), 15 hand-written questions on the Northwind sample help center:

| Retriever | Recall@5 | MRR |
|---|---|---|
| Embeddings only | 1.000 | 0.913 |
| Full-text only | 0.933 | 0.856 |
| Hybrid (RRF) | 1.000 | 0.889 |

Hybrid didn't beat embeddings on MRR. One question ("my pan is going rusty") had no keyword match, and full-text's wrong guesses still voted in the fusion. Hybrid also rescued a question that embeddings ranked fifth. The agent reads the top 6, where both score 1.0, so I kept hybrid rather than tune weights on 15 questions.

**Agent red-teaming.** Ten adversarial questions (fake VIP policies, "ignore your instructions", requests to reveal the prompt, planted "orders are free" text) found no safety failures, but three answers where the agent declined instead of correcting a false claim from the docs. The prompt was revised and rechecked against all questions.

**Grader calibration:** next. I'm hand-labelling graded answers to measure how often the LLM judge agrees with a human (percent agreement and Cohen's kappa).

## Run it locally

Requirements: Docker, [uv](https://docs.astral.sh/uv/), Node 20, and a [Gemini API key](https://aistudio.google.com/apikey).

```bash
cp .env.example .env              # add your GEMINI_API_KEY
docker compose up -d db           # Postgres 16 + pgvector

cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload    # API and background worker on :8000

cd ../frontend
npm install
npm run dev                             # http://localhost:3000
```

Tests and checks:

```bash
cd backend && uv run pytest && uv run ruff check . && uv run ruff format --check .
cd frontend && npm run typecheck && npm run lint && npm run build
```

Useful scripts (run from `backend/`):

- `uv run python ../scripts/northwind_run.py`: a full check on the bundled sample help center, using the real API.
- `uv run python ../scripts/retrieval_eval.py --verbose`: the retrieval comparison above.
- `uv run python ../scripts/agent_check.py --ask "your question"`: ask the agent directly.

## Project layout

```
backend/app/
  crawler/     URL normalization, SSRF guard, fetcher, robots, sitemap, extraction, crawl
  indexing/    chunker, embedding and storage
  retrieval/   full-text, vector and hybrid search, RRF, metrics
  llm/         LLMClient interface, Gemini client, fake client, rate limits, retries
  agent/       grounded agent prompt and answering
  exam/        exam generation, grading, scoring, gaps, handover
  pipeline/    run orchestration, Postgres job queue and worker
  api/         runs, reports, chat
frontend/      Next.js app: home, progress and report pages
fixtures/northwind/   sample help center with planted gaps and an injection
scripts/       evaluation and smoke-test scripts
```

## Known limitations

- Sites that render their content with JavaScript can't be read (there's no headless browser). The report says so instead of grading an empty agent.
- English help centers only, and at most 40 pages per check.
- The exam is generated fresh for every run, so whether it asks about a particular gap varies between runs.
- On the free tier, the judge is the same model as the agent, which may grade it more kindly. Calibration against human labels will measure this.
- Free hosting sleeps when idle, so the first request can take up to a minute.

## Stack

Python 3.12, FastAPI, psycopg 3, Alembic, Postgres 16 with pgvector, Google Gemini (google-genai), httpx2, trafilatura, pytest and ruff; Next.js, TypeScript and Tailwind; GitHub Actions; hosted on Render, Neon and Vercel.
