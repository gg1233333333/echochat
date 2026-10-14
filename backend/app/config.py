from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    deepseek_api_key: SecretStr
    app_env: Literal["development", "production"] = "development"
    gateway_token: SecretStr | None = None
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "[::1]"]
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    connect_timeout_seconds: float = Field(default=10, gt=0, le=60)
    read_timeout_seconds: float = Field(default=60, gt=0, le=300)
    stream_timeout_seconds: float = Field(default=300, gt=0, le=1800)
    heartbeat_seconds: float = Field(default=15, gt=0, le=30)
    max_concurrent_streams: int = Field(default=8, ge=1, le=100)
    max_request_bytes: int = Field(default=262144, ge=1024, le=1048576)
    max_output_tokens: int = Field(default=4096, ge=1, le=32768)

    @model_validator(mode="after")
    def validate_security(self):
        if not self.deepseek_api_key.get_secret_value().strip():
            raise ValueError("DEEPSEEK_API_KEY must be configured on the server")
        if self.app_env == "production":
            if not self.gateway_token or len(self.gateway_token.get_secret_value()) < 32:
                raise ValueError("Production requires a GATEWAY_TOKEN of at least 32 characters")
        if not self.allowed_hosts or "*" in self.allowed_hosts:
            raise ValueError("ALLOWED_HOSTS must contain explicit hosts")
        if any(origin == "*" for origin in self.cors_origins):
            raise ValueError("CORS_ORIGINS must contain explicit origins")
        return self
