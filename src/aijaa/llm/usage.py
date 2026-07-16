"""Per-tenant LLM usage accounting. The current seeker is bound via
contextvars so LLM call sites stay clean."""

from contextvars import ContextVar

from aijaa.core.db import session_factory
from aijaa.core.repo import add_llm_usage

current_seeker_id: ContextVar[str] = ContextVar("current_seeker_id", default="")


async def record_usage(component: str, model: str, input_tokens: int, output_tokens: int) -> None:
    async with session_factory()() as s:
        await add_llm_usage(
            s,
            seeker_id=current_seeker_id.get(),
            component=component,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
