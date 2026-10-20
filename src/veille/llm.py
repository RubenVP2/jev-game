"""One OpenAI-compatible client for Google AI Studio, OpenRouter and OrcaRouter.

Each task has a fallback chain of models. For structured output, one model owns the whole
generate -> validate -> repair loop, so a draft is never half written by one model and patched by
another; the next model in the chain only takes over from scratch if the previous one gives up.
Per-model profiles (config.yaml `llm.profiles`) smooth out provider quirks.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import TypeVar

from openai import AsyncOpenAI, BadRequestError, NotFoundError
from pydantic import BaseModel, ValidationError

from .config import ModelChoice, ModelProfile, Settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


class LLMError(RuntimeError):
    pass


def extract_json(text: str) -> dict | list:
    """Parse the JSON object in a model answer, tolerating reasoning tags, code fences and surrounding prose."""
    cleaned = _FENCE.sub("", _THINK.sub("", text).strip())
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


_VARIANTS = {"image", "tts", "audio", "embedding", "embed", "lite", "nano", "vision", "live", "customtools",
             "search", "banana", "native", "computer", "robotics", "batch", "realtime", "transcribe", "mini"}
_FLOATING = {"latest", "preview", "exp", "experimental"}


def _tokens(model: str) -> list[str]:
    return [t for t in re.split(r"[/\-_:~]+", model.lower().removeprefix("models/")) if t]


def _version(model: str) -> tuple[float, ...]:
    return tuple(float(n) for n in re.findall(r"\d+(?:\.\d+)?", model.removeprefix("models/")))


def pick_replacement(requested: str, available: list[str]) -> str | None:
    """Newest model of the same family: 'gemini-pro-latest' -> newest '*gemini*pro*', skipping lite/image/tts variants."""
    words = {t for t in _tokens(requested) if not re.fullmatch(r"v?[\d.]+", t) and t not in _FLOATING}
    skip = _VARIANTS - words
    candidates = []
    for model in available:
        tokens = set(_tokens(model))
        if ":" in model or not words <= tokens or tokens & skip:
            continue
        stable = not tokens & _FLOATING
        # Extra words ("oss", "codex", "sol") mean another product line: closest names first.
        extra = len({t for t in tokens - words - _FLOATING if not re.fullmatch(r"v?[\d.]+[a-z]?", t)})
        candidates.append((-extra, _version(model), stable, model))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][3].removeprefix("models/")


def is_unknown_model(exc: Exception) -> bool:
    if isinstance(exc, NotFoundError):
        return True
    message = str(exc).lower()
    return isinstance(exc, BadRequestError) and "model" in message and any(
        k in message for k in ("not found", "invalid", "does not exist", "not supported", "unknown", "no endpoints", "not a valid")
    )


@dataclass
class Completion:
    text: str
    provider: str
    model: str

    @property
    def label(self) -> str:
        return f"{self.provider}/{self.model}"


class LLM:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._clients: dict[str, AsyncOpenAI] = {}
        self.last_model: str = ""  # provider/model that produced the last successful answer
        # "provider/model" configured -> model id actually used, when the configured id was unknown.
        self.resolved: dict[str, str] = {}
        self._catalogs: dict[str, list[str]] = {}

    def _client(self, provider: str) -> AsyncOpenAI:
        if provider not in self._clients:
            cfg = self.settings.app.llm.providers[provider]
            headers = {"HTTP-Referer": "https://github.com/rubenvp2/jev-game", "X-Title": "veille"}
            self._clients[provider] = AsyncOpenAI(
                api_key=self.settings.api_key(provider),
                base_url=cfg.base_url,
                timeout=240,
                max_retries=2,
                default_headers=headers if provider == "openrouter" else None,
            )
        return self._clients[provider]

    def profile(self, choice: ModelChoice) -> ModelProfile:
        """Merge every profile whose pattern matches provider/model, in config order."""
        merged: dict = {}
        for pattern, profile in self.settings.app.llm.profiles.items():
            if fnmatch(f"{choice.provider}/{choice.model}", pattern):
                merged |= profile.model_dump(exclude_unset=True)
        return ModelProfile(**merged)

    def chain(self, task: str) -> list[ModelChoice]:
        choices = self.settings.app.llm.tasks.get(task, [])
        usable = [c for c in choices if c.provider in self.settings.app.llm.providers and self.settings.api_key(c.provider)]
        if not usable:
            raise LLMError(f"no LLM provider with an API key configured for task {task!r}")
        return usable

    async def catalog(self, provider: str) -> list[str]:
        if provider not in self._catalogs:
            page = await self._client(provider).models.list()
            self._catalogs[provider] = [m.id for m in page.data]
        return self._catalogs[provider]

    async def call(
        self, choice: ModelChoice, messages: list[dict], temperature: float, max_tokens: int, json_output: bool = False
    ) -> Completion:
        """Call a model. If the provider no longer knows the configured id, use the newest model of its family."""
        label = f"{choice.provider}/{choice.model}"
        if label in self.resolved:
            choice = ModelChoice(provider=choice.provider, model=self.resolved[label])
        try:
            return await self._call(choice, messages, temperature, max_tokens, json_output)
        except Exception as exc:
            if label in self.resolved or not is_unknown_model(exc):
                raise
            try:
                replacement = pick_replacement(choice.model, await self.catalog(choice.provider))
            except Exception:  # noqa: BLE001 - no catalog endpoint: report the original error
                raise exc from None
            if not replacement or replacement == choice.model:
                raise
            log.warning("%s is unknown to the provider, using %s instead: update config.yaml", label, replacement)
            self.resolved[label] = replacement
            return await self._call(ModelChoice(provider=choice.provider, model=replacement), messages, temperature, max_tokens, json_output)

    async def _call(
        self, choice: ModelChoice, messages: list[dict], temperature: float, max_tokens: int, json_output: bool = False
    ) -> Completion:
        profile = self.profile(choice)
        if profile.extra_system and messages and messages[0]["role"] == "system":
            messages = [{"role": "system", "content": messages[0]["content"] + "\n\n" + profile.extra_system}, *messages[1:]]
        kwargs: dict = {"model": choice.model, "messages": messages, "max_tokens": profile.max_tokens or max_tokens}
        if not profile.omit_temperature:
            kwargs["temperature"] = profile.temperature if profile.temperature is not None else temperature
        if json_output and profile.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = await self._client(choice.provider).chat.completions.create(**kwargs)
        text = _THINK.sub("", resp.choices[0].message.content or "").strip()
        if not text:
            raise LLMError("empty answer")
        return Completion(text=text, provider=choice.provider, model=choice.model)

    async def complete(self, task: str, messages: list[dict], temperature: float = 0.7, max_tokens: int = 4000) -> str:
        errors = []
        for choice in self.chain(task):
            try:
                completion = await self.call(choice, messages, temperature, max_tokens)
                log.info("%s answered by %s", task, completion.label)
                self.last_model = completion.label
                return completion.text
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
        accept: Callable[[list[str]], bool] | None = None,
    ) -> T:
        """Ask for JSON, validate it against `schema` (and `check`), and send the errors back to the same model.

        `accept` decides, after the last repair, whether the remaining `check` problems are tolerable.
        """
        errors = []
        for choice in self.chain(task):
            try:
                result = await self._json_with(choice, task, system, user, schema, temperature, max_tokens, repairs, check, accept)
                self.last_model = f"{choice.provider}/{choice.model}"
                return result
            except Exception as exc:  # noqa: BLE001 - API error or still invalid: next model starts from scratch
                log.warning("%s failed on %s/%s: %s", task, choice.provider, choice.model, str(exc)[:500])
                errors.append(f"{choice.provider}/{choice.model}: {str(exc)[:300]}")
        raise LLMError(f"every provider failed for {task!r}: " + " | ".join(errors))

    async def _json_with(
        self,
        choice: ModelChoice,
        task: str,
        system: str,
        user: str,
        schema: type[T],
        temperature: float,
        max_tokens: int,
        repairs: int,
        check: Callable[[T], list[str]] | None,
        accept: Callable[[list[str]], bool] | None = None,
    ) -> T:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        last_error = ""
        for attempt in range(repairs + 1):
            completion = await self.call(choice, messages, temperature, max_tokens, json_output=True)
            try:
                result = schema.model_validate(extract_json(completion.text))
                problems = check(result) if check else []
                if problems and attempt == repairs and accept is not None and accept(problems):
                    log.info("%s: %s accepted with minor issues: %s", task, completion.label, problems)
                    return result
                if problems:
                    raise ValueError("\n".join(f"- {p}" for p in problems))
                log.info("%s answered by %s (attempt %d)", task, completion.label, attempt + 1)
                return result
            except (ValueError, ValidationError) as exc:
                last_error = str(exc)
                log.info("%s: %s needs a fix: %s", task, completion.label, last_error[:300])
                messages += [
                    {"role": "assistant", "content": completion.text},
                    {
                        "role": "user",
                        "content": "Your answer breaks these rules:\n"
                        f"{last_error}\n\nFix every point and return the full corrected JSON object only, nothing else.",
                    },
                ]
        raise LLMError(f"still invalid after {repairs} repair attempts: {last_error}")
