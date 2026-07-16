from dataclasses import dataclass

from aijaa.core.config import get_settings
from aijaa.llm import fakes
from aijaa.llm.base import (
    AnswerLLM,
    ConfirmationLLM,
    IntakeLLM,
    JDAnalysisLLM,
    RerankLLM,
    ResumeLLM,
    TailorLLM,
)


@dataclass
class LLMBundle:
    intake: IntakeLLM
    resume: ResumeLLM
    jd: JDAnalysisLLM
    tailor: TailorLLM
    rerank: RerankLLM
    answers: AnswerLLM
    confirmation: ConfirmationLLM
    mode: str = "fake"


_bundle: LLMBundle | None = None


def get_llms() -> LLMBundle:
    global _bundle
    if _bundle is not None:
        return _bundle
    settings = get_settings()
    if settings.fake_llm or not settings.anthropic_api_key:
        f = fakes
        _bundle = LLMBundle(
            intake=f.FakeIntakeLLM(),
            resume=f.FakeResumeLLM(),
            jd=f.FakeJDAnalysisLLM(),
            tailor=f.FakeTailorLLM(),
            rerank=f.FakeRerankLLM(),
            answers=f.FakeAnswerLLM(),
            confirmation=f.FakeConfirmationLLM(),
            mode="fake",
        )
    else:
        from aijaa.llm.claude import ClaudeLLM
        from aijaa.llm.usage import record_usage

        c = ClaudeLLM(usage_hook=record_usage)
        _bundle = LLMBundle(
            intake=c, resume=c, jd=c, tailor=c, rerank=c,
            answers=c, confirmation=c, mode="claude",
        )
    return _bundle


def reset_for_tests() -> None:
    global _bundle
    _bundle = None
