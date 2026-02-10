import json
from functools import lru_cache
from typing import Annotated, List, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'DrShaq Dashboard API'
    environment: Literal['local', 'staging', 'production'] = 'local'
    api_prefix: str = '/api/v1'
    debug: bool = False

    database_url: str = 'sqlite:///./dashboard.db'

    jwt_secret_key: str = Field(default='change-me-in-env', min_length=16)
    jwt_algorithm: str = 'HS256'
    access_token_expire_minutes: int = Field(default=60, ge=5, le=1440)

    cors_allowed_origins: Annotated[List[str], NoDecode] = Field(
        default_factory=lambda: ['http://localhost:3000']
    )

    event_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    event_rate_limit_requests: int = Field(default=120, ge=1, le=5000)
    public_event_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    public_event_rate_limit_requests: int = Field(default=300, ge=1, le=10000)
    public_event_write_key: str | None = None
    public_tracking_allowed_origins: Annotated[List[str], NoDecode] = Field(default_factory=list)

    admin_seed_username: str = 'admin'
    admin_seed_password: str = Field(default='admin12345', min_length=8)
    editor_seed_username: str = 'editor'
    editor_seed_password: str = Field(default='editor12345', min_length=8)

    asset_provider: Literal['supabase', 's3', 'external'] = 'external'
    asset_public_base_url: str | None = None

    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    supabase_storage_bucket: str | None = None
    supabase_news_storage_bucket: str | None = None

    s3_bucket: str | None = None
    s3_region: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None

    @field_validator('cors_allowed_origins', mode='before')
    @classmethod
    def split_cors_origins(cls, value: str | List[str]) -> List[str]:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith('['):
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            return [item.strip() for item in value.split(',') if item.strip()]
        return value

    @field_validator('public_tracking_allowed_origins', mode='before')
    @classmethod
    def split_public_tracking_origins(cls, value: str | List[str]) -> List[str]:
        return cls.split_cors_origins(value)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
