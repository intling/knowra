"""模型管理的请求与公开响应，API Key 不进入响应结构。"""

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from app.schemas.common import UtcDateTime

ModelKind = Literal["chat", "embedding", "rerank", "query_rewrite"]


class ModelFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    base_url: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=255)
    enabled: bool = True
    api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    timeout_seconds: float = Field(default=15, ge=1, le=120)
    max_retries: int = Field(default=1, ge=0, le=3)
    dimensions: Literal[2560] | None = None
    api_format: Literal["compatible", "dashscope"] | None = None

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        try:
            url = urlsplit(value)
            valid = (
                url.scheme in ("http", "https")
                and url.hostname
                and not url.username
                and not url.password
                and not url.query
                and not url.fragment
                and url.port != 0
                and not any(c.isspace() for c in value)
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("API 地址须为 HTTP(S)，且不能包含凭据、查询参数或片段")
        return value.rstrip("/")


class ModelCreate(ModelFields):
    kind: ModelKind

    @model_validator(mode="after")
    def purpose_fields(self):
        if self.kind == "embedding":
            self.dimensions = 2560
        elif self.dimensions is not None:
            raise ValueError("仅 Embedding 配置可设置维度")
        if self.kind == "rerank":
            self.api_format = self.api_format or "compatible"
            self.max_retries = 0
        elif self.api_format is not None:
            raise ValueError("仅重排配置可设置重排协议")
        return self


class ModelUpdate(ModelFields):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    model: str | None = Field(default=None, min_length=1, max_length=255)
    enabled: bool | None = None
    timeout_seconds: float | None = Field(default=None, ge=1, le=120)
    max_retries: int | None = Field(default=None, ge=0, le=3)
    clear_api_key: bool = False

    @model_validator(mode="after")
    def secret_intent(self):
        if self.clear_api_key and self.api_key.get_secret_value():
            raise ValueError("不能同时清除和替换 API Key")
        if any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("更新字段不能为 null，请省略不修改的字段")
        return self


class ModelRead(BaseModel):
    id: UUID
    name: str
    kind: ModelKind
    base_url: str
    model: str
    enabled: bool
    is_default: bool
    has_api_key: bool
    timeout_seconds: float
    max_retries: int
    dimensions: int | None
    api_format: str | None
    created_at: datetime
    updated_at: datetime
    revision: int


class ModelProbeRead(BaseModel):
    probe_id: UUID
    status: Literal["running", "passed", "failed", "interrupted"]
    code: str
    detail: str
    latency_ms: float | None
    checked_at: UtcDateTime
    config_revision: int
    is_current: bool


class ModelProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(strict=True, ge=1)


class EffectiveModel(BaseModel):
    kind: ModelKind
    source: Literal["profile", "environment"]
    enabled: bool
    profile_id: UUID | None
    model: str
    profile_revision: int | None
    binding_revision: int
    configuration_status: Literal["ok", "unavailable", "disabled"]
    latest_probe: ModelProbeRead | None


class ModelPage(BaseModel):
    items: list[ModelRead]
    total: int
    offset: int
    limit: int
