import pytest

import aijaa.llm.factory as llm_factory


def test_factory_defaults_to_fake(monkeypatch):
    monkeypatch.setenv("AIJAA_FAKE_LLM", "true")
    llm_factory.reset_for_tests()
    assert llm_factory.get_llms().mode == "fake"


def test_factory_requires_openai_key(monkeypatch):
    monkeypatch.setenv("AIJAA_FAKE_LLM", "false")
    monkeypatch.setenv("AIJAA_LLM_PROVIDER", "openai")
    monkeypatch.delenv("AIJAA_OPENAI_API_KEY", raising=False)
    llm_factory.reset_for_tests()
    with pytest.raises(RuntimeError, match="AIJAA_OPENAI_API_KEY"):
        llm_factory.get_llms()


def test_factory_selects_openai(monkeypatch):
    monkeypatch.setenv("AIJAA_FAKE_LLM", "false")
    monkeypatch.setenv("AIJAA_LLM_PROVIDER", "openai")
    monkeypatch.setenv("AIJAA_OPENAI_API_KEY", "sk-test")
    llm_factory.reset_for_tests()
    assert llm_factory.get_llms().mode == "openai"
