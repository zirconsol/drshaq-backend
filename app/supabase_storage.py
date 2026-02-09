from app.config import get_settings

import httpx

settings = get_settings()


class SupabaseStorageError(Exception):
    pass


def _resolve_bucket(bucket: str | None) -> str:
    return bucket or settings.supabase_storage_bucket or ''


def _ensure_supabase_ready(bucket: str | None = None) -> tuple[str, str, str]:
    resolved_bucket = _resolve_bucket(bucket)
    if not settings.supabase_url or not settings.supabase_service_role_key or not resolved_bucket:
        raise SupabaseStorageError('Configuracion Supabase incompleta para upload')
    return (
        settings.supabase_url.rstrip('/'),
        settings.supabase_service_role_key,
        resolved_bucket,
    )


def upload_bytes_to_supabase(
    storage_path: str,
    content: bytes,
    content_type: str,
    bucket: str | None = None,
) -> None:
    supabase_url, service_key, bucket_name = _ensure_supabase_ready(bucket=bucket)
    endpoint = f'{supabase_url}/storage/v1/object/{bucket_name}/{storage_path}'
    headers = {
        'apikey': service_key,
        'Authorization': f'Bearer {service_key}',
        'Content-Type': content_type,
        'x-upsert': 'true',
    }

    with httpx.Client(timeout=25) as client:
        response = client.post(endpoint, headers=headers, content=content)

    if not response.is_success:
        raise SupabaseStorageError(f'Error subiendo a Supabase Storage: {response.status_code}')


def delete_from_supabase(storage_path: str, bucket: str | None = None) -> None:
    supabase_url, service_key, bucket_name = _ensure_supabase_ready(bucket=bucket)
    endpoint = f'{supabase_url}/storage/v1/object/{bucket_name}/{storage_path}'
    headers = {
        'apikey': service_key,
        'Authorization': f'Bearer {service_key}',
    }

    with httpx.Client(timeout=15) as client:
        response = client.delete(endpoint, headers=headers)

    if not response.is_success and response.status_code != 404:
        raise SupabaseStorageError(f'Error eliminando de Supabase Storage: {response.status_code}')
