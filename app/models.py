from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

STRATEGIES = Literal["auto", "html", "rsc", "json", "api"]
CHANNEL_TYPES = Literal[
    "email", "telegram", "webhook", "bark", "serverchan", "pushplus", "ntfy", "twilio", "console"
]


class SourceBase(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=8, max_length=1000)
    strategy: STRATEGIES = "auto"
    interval_minutes: int = Field(default=60, ge=5, le=10080)
    enabled: bool = True
    use_proxy: bool = True
    locale: str = Field(default="zh", max_length=12)
    keywords_include: str = Field(default="", max_length=500)
    keywords_exclude: str = Field(default="", max_length=500)
    selectors: dict[str, Any] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=500)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("URL 必须以 http:// 或 https:// 开头")
        return v


class SourceCreate(SourceBase):
    pass


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    url: str | None = Field(default=None, min_length=8, max_length=1000)
    strategy: STRATEGIES | None = None
    interval_minutes: int | None = Field(default=None, ge=5, le=10080)
    enabled: bool | None = None
    use_proxy: bool | None = None
    locale: str | None = None
    keywords_include: str | None = None
    keywords_exclude: str | None = None
    selectors: dict[str, Any] | None = None
    notes: str | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("URL 必须以 http:// 或 https:// 开头")
        return v


class ChannelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    type: CHANNEL_TYPES
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class ChannelUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    config: dict[str, Any] | None = None


class FeasibilityRequest(BaseModel):
    url: str = Field(min_length=8, max_length=1000)
    name: str = Field(default="", max_length=80)
    use_ai: bool = True
    use_proxy: bool = True

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("URL 必须以 http:// 或 https:// 开头")
        return v


class PresetInstall(BaseModel):
    key: str | None = None
    enabled: bool = True


class ScanRequest(BaseModel):
    force: bool = False


class SettingsPatch(BaseModel):
    values: dict[str, Any]


class TestAIRequest(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    provider: str | None = None


class ProxyTestRequest(BaseModel):
    url: str | None = None


class BrowserTestRequest(BaseModel):
    url: str | None = None
