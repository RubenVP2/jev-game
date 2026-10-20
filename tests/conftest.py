import json
from pathlib import Path

import pytest

from veille.config import AppConfig, ModelChoice, ProviderConfig, Secrets, Settings
from veille.db import Database
from veille.models import PostContent

SAMPLE = Path(__file__).parents[1] / "src" / "veille" / "carousel" / "sample.json"


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
    }
    monkeypatch.setenv("FIRST_KEY", "k1")
    monkeypatch.setenv("SECOND_KEY", "k2")
    secrets = Secrets(_env_file=None, veille_data_dir=tmp_path, public_base_url="https://media.test")
    s = Settings(secrets=secrets, app=app)
    s.media_dir.mkdir(parents=True, exist_ok=True)
    return s


@pytest.fixture
def db() -> Database:
    return Database(":memory:")
