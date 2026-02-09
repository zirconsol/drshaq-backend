from urllib.parse import urlparse

from app.config import get_settings

settings = get_settings()


def normalize_storage_path(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        return value

    if value.startswith('http://') or value.startswith('https://'):
        parsed = urlparse(value)
        marker = '/storage/v1/object/public/'
        if marker in parsed.path:
            tail = parsed.path.split(marker, 1)[1]
            parts = tail.split('/', 1)
            if len(parts) == 2:
                _, path = parts
                return path
        return value

    return value.lstrip('/')


def build_public_asset_url(storage_path: str | None) -> str | None:
    return build_public_asset_url_for_bucket(storage_path, bucket=None)


def build_public_asset_url_for_bucket(storage_path: str | None, bucket: str | None = None) -> str | None:
    if not storage_path:
        return None

    clean_path = storage_path.lstrip('/')

    if settings.asset_public_base_url:
        return f"{settings.asset_public_base_url.rstrip('/')}/{clean_path}"

    resolved_bucket = bucket or settings.supabase_storage_bucket
    if settings.supabase_url and resolved_bucket:
        return (
            f"{settings.supabase_url.rstrip('/')}/storage/v1/object/public/"
            f"{resolved_bucket}/{clean_path}"
        )

    if settings.asset_provider == 's3' and settings.s3_bucket and settings.s3_region:
        return f'https://{settings.s3_bucket}.s3.{settings.s3_region}.amazonaws.com/{clean_path}'

    return None
