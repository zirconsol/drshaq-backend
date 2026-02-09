from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.dependencies import require_roles
from app.models import News, Product, UserRole
from app.schemas import AssetUploadRequest, AssetUploadResponse
from app.storage_utils import build_public_asset_url

router = APIRouter(prefix='/assets', tags=['assets'])
settings = get_settings()


def _safe_filename(name: str) -> str:
    cleaned = ''.join(char if char.isalnum() or char in {'.', '-', '_'} else '-' for char in name.lower())
    return cleaned.strip('-')


def _build_object_key(payload: AssetUploadRequest) -> str:
    entity_type = payload.entity_type
    file_name = payload.file_name
    now = datetime.now(timezone.utc)
    ext = Path(file_name).suffix or '.bin'
    base = Path(file_name).stem
    safe_base = _safe_filename(base)[:60] or 'file'

    if payload.product_id and entity_type == 'product-cover':
        return f'products/{payload.product_id}/cover{ext}'
    if payload.product_id and entity_type.startswith('product'):
        return f'products/{payload.product_id}/gallery/{uuid4()}-{safe_base}{ext}'

    return f'{entity_type}/{now.year}/{now.month:02d}/{uuid4()}-{safe_base}{ext}'


def _public_url_for(object_key: str) -> str | None:
    return build_public_asset_url(object_key)


@router.post('/upload-strategy', response_model=AssetUploadResponse, dependencies=[Depends(require_roles(UserRole.admin, UserRole.editor))])
def get_upload_strategy(
    payload: AssetUploadRequest,
    db: Session = Depends(get_db),
) -> AssetUploadResponse:
    if payload.product_id and not db.get(Product, payload.product_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Producto no encontrado para upload')
    if payload.news_id and not db.get(News, payload.news_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Noticia no encontrada para upload')

    object_key = _build_object_key(payload)
    public_url = _public_url_for(object_key)

    if settings.asset_provider == 's3':
        if not all([settings.s3_bucket, settings.s3_region, settings.s3_access_key_id, settings.s3_secret_access_key]):
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail='Configuracion S3 incompleta')
        try:
            import boto3
        except ImportError as exc:
            raise HTTPException(status_code=500, detail='boto3 no instalado para presigned URLs') from exc

        client = boto3.client(
            's3',
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
        )
        upload_url = client.generate_presigned_url(
            ClientMethod='put_object',
            Params={'Bucket': settings.s3_bucket, 'Key': object_key, 'ContentType': payload.content_type},
            ExpiresIn=900,
        )
        return AssetUploadResponse(
            provider='s3',
            object_key=object_key,
            public_url=public_url,
            upload_url=upload_url,
            expires_in=900,
            note='Subir directo al bucket con PUT y guardar public_url en DB',
        )

    if settings.asset_provider == 'supabase':
        if not all([settings.supabase_url, settings.supabase_service_role_key, settings.supabase_storage_bucket]):
            raise HTTPException(status_code=500, detail='Configuracion Supabase incompleta')
        endpoint = (
            f"{settings.supabase_url.rstrip('/')}/storage/v1/object/upload/sign/"
            f"{settings.supabase_storage_bucket}/{object_key}"
        )
        headers = {
            'apikey': settings.supabase_service_role_key,
            'Authorization': f'Bearer {settings.supabase_service_role_key}',
            'Content-Type': 'application/json',
        }
        response = httpx.post(endpoint, json={'expiresIn': 900}, headers=headers, timeout=10)
        if response.is_success:
            payload_json = response.json()
            signed_path = payload_json.get('signedURL') or payload_json.get('url')
            upload_url = None
            if signed_path:
                if signed_path.startswith('http'):
                    upload_url = signed_path
                else:
                    upload_url = f"{settings.supabase_url.rstrip('/')}{signed_path}"
            return AssetUploadResponse(
                provider='supabase',
                object_key=object_key,
                public_url=public_url,
                upload_url=upload_url,
                expires_in=900,
                note='Guardar public_url en DB luego de subir el archivo',
            )

        return AssetUploadResponse(
            provider='supabase',
            object_key=object_key,
            public_url=public_url,
            upload_url=None,
            expires_in=None,
            note='No se pudo generar signed URL. Subir con SDK de Supabase y conservar la public_url en DB.',
        )

    return AssetUploadResponse(
        provider='external',
        object_key=object_key,
        public_url=public_url,
        upload_url=None,
        expires_in=None,
        note='La API guarda solo URLs en DB; la carga ocurre fuera de este backend.',
    )
