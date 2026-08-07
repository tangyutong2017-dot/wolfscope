"""One-model-per-game DeepSeek profiles for M2."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ModelProfile(StrEnum):
    TEST = "test"
    PRODUCTION = "production"


class DeepSeekModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = "deepseek"
    model_name: str = Field(min_length=1)
    base_url: str = "https://api.deepseek.com"
    thinking_enabled: bool = True
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1500, ge=1)
    vote_max_tokens: int = Field(default=2000, ge=1)
    request_timeout_seconds: float = Field(default=60.0, gt=0.0)
    request_max_retries: int = Field(default=2, ge=0, le=5)
    schema_repair_attempts: int = Field(default=1, ge=0, le=1)


_MODEL_PROFILES = {
    ModelProfile.TEST: DeepSeekModelConfig(model_name="deepseek-v4-flash"),
    ModelProfile.PRODUCTION: DeepSeekModelConfig(
        model_name="deepseek-v4-pro",
        temperature=0.5,
    ),
}


def model_config_for(profile: ModelProfile) -> DeepSeekModelConfig:
    return _MODEL_PROFILES[profile]
