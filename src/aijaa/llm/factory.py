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
    provider = settings.llm_provider.lower()
    if settings.fake_llm or provider == "fake":
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
    elif provider == "openai" or (settings.openai_api_key and not settings.anthropic_api_key):
        if not settings.openai_api_key:
            raise RuntimeError("AIJAA_OPENAI_API_KEY is required when AIJAA_LLM_PROVIDER=openai")
        from aijaa.llm.openai_provider import OpenAILLM
        from aijaa.llm.usage import record_usage

        o = OpenAILLM(usage_hook=record_usage)
        _bundle = LLMBundle(
            intake=o, resume=o, jd=o, tailor=o, rerank=o,
            answers=o, confirmation=o, mode="openai",
        )
    else:
        from aijaa.llm.claude import ClaudeLLM
        from aijaa.llm.usage import record_usage

        if not settings.anthropic_api_key:
            raise RuntimeError("AIJAA_ANTHROPIC_API_KEY is required for Anthropic LLM mode")
        c = ClaudeLLM(usage_hook=record_usage)
        _bundle = LLMBundle(
            intake=c, resume=c, jd=c, tailor=c, rerank=c,
            answers=c, confirmation=c, mode="claude",
        )
    return _bundle


def reset_for_tests() -> None:
    global _bundle
    _bundle = None
