"""One OpenAI-compatible client for Google AI Studio, OpenRouter and OrcaRouter, with per-task fallback chains."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from .config import ModelChoice, Settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class LLMError(RuntimeError):
    pass


def extract_json(text: str) -> dict | list:
    """Parse the JSON object in a model answer, tolerating code fences and surrounding prose."""
    cleaned = _FENCE.sub("", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (cleaned.find("{"), cleaned.find("[")) if i != -1]
    if not starts:
        raise ValueError("no JSON found in the answer")
    start = min(starts)
    end = max(cleaned.rfind("}"), cleaned.rfind("]"))
    return json.loads(cleaned[start : end + 1])


class LLM:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._clients: dict[str, AsyncOpenAI] = {}

    def _client(self, provider: str) -> AsyncOpenAI:
        if provider not in self._clients:
            cfg = self.settings.app.llm.providers[provider]
            headers = {"HTTP-Referer": "https://github.com/rubenvp2/jev-game", "X-Title": "veille"}
            self._clients[provider] = AsyncOpenAI(
                api_key=self.settings.api_key(provider),
                base_url=cfg.base_url,
                timeout=180,
                max_retries=1,
                default_headers=headers if provider == "openrouter" else None,
            )
        return self._clients[provider]

    def chain(self, task: str) -> list[ModelChoice]:
        choices = self.settings.app.llm.tasks.get(task, [])
        usable = [c for c in choices if c.provider in self.settings.app.llm.providers and self.settings.api_key(c.provider)]
        if not usable:
            raise LLMError(f"no LLM provider with an API key configured for task {task!r}")
        return usable

    async def complete(self, task: str, messages: list[dict], temperature: float = 0.7, max_tokens: int = 4000) -> str:
        errors = []
        for choice in self.chain(task):
            try:
                resp = await self._client(choice.provider).chat.completions.create(
                    model=choice.model, messages=messages, temperature=temperature, max_tokens=max_tokens
                )
                text = resp.choices[0].message.content or ""
                if not text.strip():
                    raise LLMError("empty answer")
                log.info("%s answered by %s/%s", task, choice.provider, choice.model)
                return text
            except Exception as exc:  # noqa: BLE001 - any provider failure moves on to the next one
                log.warning("%s failed on %s/%s: %s", task, choice.provider, choice.model, exc)
                errors.append(f"{choice.provider}/{choice.model}: {exc}")
        raise LLMError(f"every provider failed for {task!r}: " + " | ".join(errors))

    async def complete_json(
        self,
        task: str,
        system: str,
        user: str,
        schema: type[T],
        temperature: float = 0.7,
        max_tokens: int = 4000,
        repairs: int = 2,
        check: Callable[[T], list[str]] | None = None,
    ) -> T:
        """Ask for JSON, validate it against `schema` (and `check`), and send the errors back to the model to fix."""
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        last_error = ""
        for _ in range(repairs + 1):
            text = await self.complete(task, messages, temperature=temperature, max_tokens=max_tokens)
            try:
                result = schema.model_validate(extract_json(text))
                problems = check(result) if check else []
                if problems:
                    raise ValueError("\n".join(problems))
                return result
            except (ValueError, ValidationError) as exc:
                last_error = str(exc)
                log.info("%s returned invalid JSON, asking for a fix: %s", task, last_error[:300])
                messages += [
                    {"role": "assistant", "content": text},
                    {
                        "role": "user",
                        "content": "Your JSON is invalid:\n"
                        f"{last_error}\n\nReturn the full corrected JSON object only, nothing else.",
                    },
                ]
        raise LLMError(f"{task}: still invalid after {repairs} repair attempts: {last_error}")
