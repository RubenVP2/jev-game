import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from veille.config import AppConfig, ModelChoice, ProviderConfig, Secrets, Settings
from veille.db import Database
from veille.models import PostContent

SAMPLE = Path(__file__).parents[1] / "src" / "veille" / "carousel" / "sample.json"

# Chromium shipped outside the default Playwright location (e.g. /opt/pw-browsers in some sandboxes).
CHROMIUM = os.environ.get("CHROMIUM_PATH") or next(iter(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome")), None)


def chromium_available() -> bool:
    if CHROMIUM:
        return True
    browsers = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or Path.home() / ".cache" / "ms-playwright")
    return any(browsers.glob("chromium-*"))


requires_chromium = pytest.mark.skipif(not chromium_available(), reason="Chromium not installed")


@pytest.fixture(autouse=True)
def chromium_path(monkeypatch):
    if CHROMIUM and not os.environ.get("CHROMIUM_PATH"):
        monkeypatch.setenv("CHROMIUM_PATH", str(CHROMIUM))


@pytest.fixture
def sample_content() -> PostContent:
    return PostContent.model_validate(json.loads(SAMPLE.read_text()))


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    for var in ("GOOGLE_AI_API_KEY", "OPENROUTER_API_KEY", "ORCAROUTER_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    app = AppConfig()
    app.llm.providers = {
        "first": ProviderConfig(base_url="https://first.test/v1", api_key_env="FIRST_KEY"),
        "second": ProviderConfig(base_url="https://second.test/v1", api_key_env="SECOND_KEY"),
    }
    app.llm.tasks = {
        "write": [ModelChoice(provider="first", model="m1"), ModelChoice(provider="second", model="m2")],
        "triage": [ModelChoice(provider="first", model="m1")],
        "facts": [ModelChoice(provider="first", model="m1")],
        "judge": [ModelChoice(provider="first", model="m1")],
    }
    monkeypatch.setenv("FIRST_KEY", "k1")
    monkeypatch.setenv("SECOND_KEY", "k2")
    secrets = Secrets(_env_file=None, veille_data_dir=tmp_path, public_base_url="https://media.test")
    s = Settings(secrets=secrets, app=app)
    s.media_dir.mkdir(parents=True, exist_ok=True)
    return s


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


@pytest.fixture
def db() -> Database:
    return Database(":memory:")
