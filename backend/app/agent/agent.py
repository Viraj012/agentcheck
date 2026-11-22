"""Answer questions grounded in retrieved chunks, several questions per LLM call."""

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel

from app.agent.prompt import SYSTEM_PROMPT, AgentQuestion, build_prompt
from app.llm.base import LLMClient, LLMError

NO_CONTEXT_ANSWER = (
    "I don't have information about that in the help center. Please contact support."
)
DECLINE_ANSWER = "Sorry, I can't help with that here. Please contact support."

__all__ = ["AgentQuestion", "AgentResult", "answer_questions"]


class _Answer(BaseModel):
    question_id: int
    answer: str
    citations: list[int]
    abstained: bool


class _Batch(BaseModel):
    answers: list[_Answer]


@dataclass(frozen=True)
class AgentResult:
    question_id: int
    answer: str
    citations: list[int]
    abstained: bool
    retrieved_ids: list[int]
    invalid_citations: list[int]


async def answer_questions(llm: LLMClient, items: Sequence[AgentQuestion]) -> list[AgentResult]:
    """One LLM call for every question that has context; results in the order given."""
    with_context = [item for item in items if item.chunks]
    answers: dict[int, _Answer] = {}
    if with_context:
        batch = await llm.generate_json(
            build_prompt(with_context), schema=_Batch, system=SYSTEM_PROMPT
        )
        answers = {answer.question_id: answer for answer in batch.answers}
        missing = [item.id for item in with_context if item.id not in answers]
        if missing:
            raise LLMError(f"model gave no answer for question ids {missing}")
    return [_result(item, answers.get(item.id)) for item in items]


def _result(item: AgentQuestion, answer: _Answer | None) -> AgentResult:
    retrieved = [chunk.id for chunk in item.chunks]
    if answer is None:
        return AgentResult(item.id, NO_CONTEXT_ANSWER, [], True, retrieved, [])
    text = answer.answer.strip()
    abstained = answer.abstained or not text
    cited = list(dict.fromkeys(answer.citations))
    valid = [] if abstained else [c for c in cited if c in retrieved]
    invalid = [c for c in cited if c not in retrieved]
    return AgentResult(item.id, text or DECLINE_ANSWER, valid, abstained, retrieved, invalid)
