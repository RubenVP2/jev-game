from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from conftest import FakeClient
from veille.config import ModelChoice, ModelProfile
from veille.llm import LLM, LLMError, extract_json


def llm_with(settings, **clients):
    llm = LLM(settings)
    llm._clients.update(clients)
    return llm


def test_extract_json_tolerates_fences_and_prose():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Here you go: {"a": [1, 2]} hope it helps') == {"a": [1, 2]}
    with pytest.raises(ValueError):
        extract_json("no json at all")


async def test_fallback_to_next_provider(settings):
    first, second = FakeClient([RuntimeError("500")]), FakeClient(["hello"])
    text = await llm_with(settings, first=first, second=second).complete("write", [{"role": "user", "content": "hi"}])
    assert text == "hello"
    assert first.requests[0]["model"] == "m1"
    assert second.requests[0]["model"] == "m2"


async def test_empty_answer_falls_back(settings):
    llm = llm_with(settings, first=FakeClient(["  "]), second=FakeClient(["ok"]))
    assert await llm.complete("write", []) == "ok"


async def test_all_providers_failing_raises(settings):
    llm = llm_with(settings, first=FakeClient([RuntimeError("a")]), second=FakeClient([RuntimeError("b")]))
    with pytest.raises(LLMError, match="every provider failed"):
        await llm.complete("write", [])


def test_providers_without_key_are_skipped(settings, monkeypatch):
    monkeypatch.delenv("FIRST_KEY")
    assert [c.provider for c in LLM(settings).chain("write")] == ["second"]
    monkeypatch.delenv("SECOND_KEY")
    with pytest.raises(LLMError, match="no LLM provider"):
        LLM(settings).chain("write")


class Answer(BaseModel):
    value: int


async def test_complete_json_repairs_invalid_answer(settings):
    client = FakeClient(['{"value": "not a number"}', '{"value": 3}', '{"value": 7}'])
    llm = llm_with(settings, first=client)
    result = await llm.complete_json("write", "sys", "user", Answer, check=lambda a: ["too small"] if a.value < 5 else [])
    assert result.value == 7
    assert len(client.requests) == 3
    # The check failure is sent back to the model.
    assert "too small" in client.requests[-1]["messages"][-1]["content"]


async def test_complete_json_gives_up(settings):
    llm = llm_with(settings, first=FakeClient(["nope"] * 3))
    with pytest.raises(LLMError, match="still invalid"):
        await llm.complete_json("write", "sys", "user", Answer, repairs=2)


async def test_repairs_stay_on_the_same_model(settings):
    """A model that cannot produce valid output is replaced from scratch, never patched by another one."""
    first = FakeClient(["bad"] * 3)
    second = FakeClient(['{"value": 9}'])
    llm = llm_with(settings, first=first, second=second)
    result = await llm.complete_json("write", "sys", "user", Answer, repairs=2)
    assert result.value == 9
    assert len(first.requests) == 3
    assert len(second.requests[0]["messages"]) == 2  # fresh conversation, no trace of the first model
    assert llm.last_model == "second/m2"


async def test_profiles_adjust_the_request(settings):
    settings.app.llm.profiles = {
        "first/*": ModelProfile(json_mode=True, omit_temperature=True, extra_system="Be brief."),
        "*m1": ModelProfile(max_tokens=123),
    }
    client = FakeClient(['{"value": 1}'])
    await llm_with(settings, first=client).complete_json("write", "SYSTEM", "user", Answer)
    request = client.requests[0]
    assert "temperature" not in request
    assert request["max_tokens"] == 123
    assert request["response_format"] == {"type": "json_object"}
    assert request["messages"][0]["content"] == "SYSTEM\n\nBe brief."


def test_reasoning_tags_are_ignored():
    assert extract_json('<think>{"a": 0}</think>{"a": 1}') == {"a": 1}


def test_profile_merge_order(settings):
    settings.app.llm.profiles = {"*": ModelProfile(temperature=0.2), "first/m1": ModelProfile(temperature=0.9)}
    assert LLM(settings).profile(ModelChoice(provider="first", model="m1")).temperature == 0.9
    assert LLM(settings).profile(ModelChoice(provider="second", model="m2")).temperature == 0.2


def test_pick_replacement_prefers_the_same_product_line():
    from veille.llm import pick_replacement

    catalog = ["models/gemini-2.5-pro", "models/gemini-3.1-pro-preview", "models/gemini-3.8-flash",
               "models/gemini-3.8-flash-lite", "models/gemini-3.8-flash-image", "models/text-embedding-004"]
    assert pick_replacement("gemini-pro-latest", catalog) == "gemini-3.1-pro-preview"
    assert pick_replacement("gemini-flash-latest", catalog) == "gemini-3.8-flash"
    openrouter = ["openai/gpt-5.5", "openai/gpt-oss-120b", "openai/gpt-5.6-sol", "anthropic/claude-sonnet-5.5"]
    assert pick_replacement("openai/gpt-9", openrouter) == "openai/gpt-5.5"
    assert pick_replacement("anthropic/claude-sonnet-9", openrouter) == "anthropic/claude-sonnet-5.5"
    assert pick_replacement("mistral/large", openrouter) is None


async def test_unknown_model_is_resolved_from_the_catalog(settings):
    import httpx
    from openai import NotFoundError

    request = httpx.Request("POST", "https://first.test/v1/chat/completions")
    not_found = NotFoundError("model not found", response=httpx.Response(404, request=request), body=None)
    client = FakeClient([not_found, "hello", "again"])
    client.models = SimpleNamespace(list=lambda: _async(SimpleNamespace(data=[SimpleNamespace(id="acme-pro-2"), SimpleNamespace(id="acme-flash-3")])))
    settings.app.llm.tasks["write"] = [ModelChoice(provider="first", model="acme-pro-latest")]
    llm = llm_with(settings, first=client)
    assert await llm.complete("write", [{"role": "user", "content": "hi"}]) == "hello"
    assert llm.resolved == {"first/acme-pro-latest": "acme-pro-2"}
    assert client.requests[1]["model"] == "acme-pro-2"
    await llm.complete("write", [{"role": "user", "content": "hi"}])
    assert client.requests[2]["model"] == "acme-pro-2"  # remembered, no second failing call


async def _async(value):
    return value
