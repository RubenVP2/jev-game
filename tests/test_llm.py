from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from veille.llm import LLM, LLMError, extract_json


class FakeClient:
    """Stands in for AsyncOpenAI: each call pops the next answer (a string, or an exception to raise)."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.requests.append(kwargs)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=answer))])


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
