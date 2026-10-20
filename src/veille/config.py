"""Configuration: secrets from the environment (.env), everything else from config.yaml."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    google_ai_api_key: str = ""
    openrouter_api_key: str = ""
    orcarouter_api_key: str = ""

    github_token: str = ""
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "veille/0.1"

    discord_bot_token: str = ""
    discord_channel_id: str = ""
    discord_allowed_user_ids: str = ""

    domain: str = ""
    public_base_url: str = ""

    threads_access_token: str = ""
    threads_user_id: str = "me"
    threads_app_id: str = ""
    threads_app_secret: str = ""
    threads_redirect_uri: str = ""

    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    tiktok_redirect_uri: str = ""

    veille_config: Path = Path("config.yaml")
    veille_data_dir: Path = Path("data")

    @model_validator(mode="after")
    def _derive_urls(self) -> Secrets:
        """DOMAIN alone is enough: the public URL and the TikTok callback derive from it."""
        if not self.public_base_url and self.domain:
            self.public_base_url = f"https://{self.domain}"
        base = self.public_base_url.rstrip("/")
        if not self.tiktok_redirect_uri and base:
            self.tiktok_redirect_uri = f"{base}/tiktok/callback"
        if not self.threads_redirect_uri and base:
            self.threads_redirect_uri = f"{base}/threads/callback"
        return self

    @property
    def channel_id(self) -> int:
        return int(self.discord_channel_id) if self.discord_channel_id.strip().isdigit() else 0

    @property
    def allowed_user_ids(self) -> set[int]:
        return {int(x) for x in self.discord_allowed_user_ids.replace(" ", "").split(",") if x.isdigit()}


class ScheduleConfig(BaseModel):
    slots: list[str] = ["08:00", "19:00"]
    draft_lead_minutes: int = 120


class BrandConfig(BaseModel):
    name: str = "SIGNAL"
    tagline: str = "Engineering signal, no noise."
    handle: str = ""
    accent: str = "#7CFFB2"
    # Always present on TikTok, after the topic hashtags.
    tiktok_hashtags: list[str] = ["#softwareengineering", "#tech"]


class GithubConfig(BaseModel):
    enabled: bool = True
    languages: list[str] = [""]
    since: str = "daily"
    min_stars_today: int = 80


class HackerNewsConfig(BaseModel):
    enabled: bool = True
    min_points: int = 120
    lookback_hours: int = 36


class RedditConfig(BaseModel):
    enabled: bool = True
    subreddits: list[str] = ["programming"]
    min_score: int = 150
    period: str = "day"


class SourcesConfig(BaseModel):
    github: GithubConfig = GithubConfig()
    hackernews: HackerNewsConfig = HackerNewsConfig()
    reddit: RedditConfig = RedditConfig()


class RankingConfig(BaseModel):
    shortlist_size: int = 25
    dedup_days: int = 21


class ProviderConfig(BaseModel):
    base_url: str
    api_key_env: str


class ModelChoice(BaseModel):
    provider: str
    model: str


class ModelProfile(BaseModel):
    """Per-model adjustments, matched on "provider/model" with shell patterns (e.g. "openrouter/openai/*")."""

    temperature: float | None = None  # overrides the task temperature
    omit_temperature: bool = False  # for reasoning models that reject the parameter
    max_tokens: int | None = None
    json_mode: bool = False  # send response_format={"type": "json_object"}
    extra_system: str = ""  # appended to the system prompt, to correct a model's known habits


class LLMConfig(BaseModel):
    providers: dict[str, ProviderConfig] = {}
    tasks: dict[str, list[ModelChoice]] = {}
    profiles: dict[str, ModelProfile] = {}


class HarnessConfig(BaseModel):
    """Consistency harness: keeps the voice identical whatever model writes."""

    judge_enabled: bool = True
    min_score: float = 7.5  # judge score (0-10) under which the draft is revised
    max_revisions: int = 2
    exemplars: int = 3  # approved posts injected as style references
    enforce_grounding: bool = True  # every figure in the post must appear in the dossier


class CarouselConfig(BaseModel):
    width: int = 1080
    height: int = 1350
    min_slides: int = 5
    max_slides: int = 8


class ThreadsPublishConfig(BaseModel):
    enabled: bool = True
    attach_carousel: bool = True


class TikTokPublishConfig(BaseModel):
    enabled: bool = True
    mode: str = "MEDIA_UPLOAD"
    privacy_level: str = "PUBLIC_TO_EVERYONE"


class PublishConfig(BaseModel):
    threads: ThreadsPublishConfig = ThreadsPublishConfig()
    tiktok: TikTokPublishConfig = TikTokPublishConfig()


class AppConfig(BaseModel):
    timezone: str = "Europe/Paris"
    schedule: ScheduleConfig = ScheduleConfig()
    brand: BrandConfig = BrandConfig()
    sources: SourcesConfig = SourcesConfig()
    ranking: RankingConfig = RankingConfig()
    llm: LLMConfig = LLMConfig()
    carousel: CarouselConfig = CarouselConfig()
    publish: PublishConfig = PublishConfig()
    harness: HarnessConfig = HarnessConfig()


class Settings(BaseModel):
    secrets: Secrets
    app: AppConfig = Field(default_factory=AppConfig)

    @property
    def data_dir(self) -> Path:
        return self.secrets.veille_data_dir

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "veille.db"

    def api_key(self, provider: str) -> str:
        cfg = self.app.llm.providers.get(provider)
        if cfg is None:
            return ""
        return os.environ.get(cfg.api_key_env) or getattr(self.secrets, cfg.api_key_env.lower(), "")


def load_app_config(path: Path) -> AppConfig:
    if not path.exists():
        return AppConfig()
    return AppConfig.model_validate(yaml.safe_load(path.read_text()) or {})


@lru_cache
def get_settings() -> Settings:
    secrets = Secrets()
    settings = Settings(secrets=secrets, app=load_app_config(secrets.veille_config))
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    return settings
