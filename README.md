# Dashboard API (backend)

API privada para el dashboard interno (no para uso publico en la landing), con:

- JWT auth + roles (`admin`, `editor`)
- CRUD de productos y catalogos con estados (`draft`, `published`, `archived`)
- categorias de drop + tipos de producto, orden e imagenes (se guarda `path` en DB)
- tracking de eventos CTA (`impression`, `click`) con `page`, `source`, `session_id`, timestamp
- tracking anonimo de embudo (`cta_click`, `add_to_request`, `request_submitted`) con `session_id`/`visitor_id`
- requests de productos sin login de usuario (estado: `submitted`, `paid`, `fulfilled`, `declined_*`)
- reporting de KPIs por rango de fechas (totales, por producto, por catalogo, UTM/referrer)
- reporting de embudo CTA->request->fulfilled y productos mas pedidos
- auditoria de cambios (`quien`, `que`, `cuando`, estado previo/posterior)
- rate limiting basico para ingesta de eventos
- CORS restringido por `CORS_ALLOWED_ORIGINS`

## Ejecutar local

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8001
```

Docs: `http://localhost:8001/docs`

## Credenciales seed

En startup se crean usuarios si no existen:

- `admin` / `ADMIN_SEED_PASSWORD`
- `editor` / `EDITOR_SEED_PASSWORD`

Tambien se siembra taxonomia base de drops:

- Categorias: `montana`, `ye-apparel`, `camperas`
- Tipos de producto: `remeras`, `pantalones`, `camperas`
- Asignaciones iniciales:
  - `montana` -> `remeras`, `pantalones`
  - `ye-apparel` -> `remeras`, `pantalones`
  - `camperas` -> `camperas`

## Endpoints principales

- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`

- `POST|GET|PATCH|DELETE /api/v1/taxonomy/categories...`
- `POST|GET|PATCH|DELETE /api/v1/taxonomy/collections...`
- `POST|GET|PATCH|DELETE /api/v1/taxonomy/product-types...` (alias de `collections`)
- `GET /api/v1/taxonomy/categories/{category_id}/product-types`
- `POST|DELETE /api/v1/taxonomy/categories/{category_id}/product-types/{collection_id}`

- `GET /api/v1/public/products`
- `GET /api/v1/public/products/{product_id}`
- `GET /api/v1/public/taxonomy/categories`
- `GET /api/v1/public/taxonomy/collections`
- `GET /api/v1/public/catalog` (`drop_slug`, `cat`, `collection_slug`, `q`)

- `POST|GET /api/v1/products`
- `GET|PATCH|DELETE /api/v1/products/{product_id}`
- `POST /api/v1/products/{product_id}/publish`
- `POST /api/v1/products/{product_id}/archive`
- `POST /api/v1/products/{product_id}/order`
- `POST|PATCH|DELETE /api/v1/products/{product_id}/images...`
- `POST /api/v1/admin/products/{product_id}/image/cover` (`multipart/form-data`)
- `POST /api/v1/admin/products/{product_id}/image/gallery` (`multipart/form-data`)
- `DELETE /api/v1/admin/products/{product_id}/image`

Regla de negocio en productos: si se informa `collection_id` (tipo), `category_id` es obligatorio y ese tipo debe estar vinculado a la categoria.

- `POST|GET /api/v1/news`
- `GET /api/v1/news/featured`
- `GET|PATCH|DELETE /api/v1/news/{news_id}`
- `POST /api/v1/news/{news_id}/feature`
- `POST|PATCH|DELETE /api/v1/news/{news_id}/images...`
- `POST /api/v1/admin/news/{news_id}/image/banner` (`multipart/form-data`)
- `POST /api/v1/admin/news/{news_id}/image/gallery` (`multipart/form-data`)
- `DELETE /api/v1/admin/news/{news_id}/image/banner`

- `POST|GET /api/v1/catalogs`
- `GET|PATCH|DELETE /api/v1/catalogs/{catalog_id}`
- `POST /api/v1/catalogs/{catalog_id}/publish`
- `POST /api/v1/catalogs/{catalog_id}/archive`
- `POST /api/v1/catalogs/{catalog_id}/order`
- `POST /api/v1/catalogs/{catalog_id}/products`
- `PATCH|DELETE /api/v1/catalogs/{catalog_id}/products/{product_id}`
- `POST|PATCH|DELETE /api/v1/catalogs/{catalog_id}/images...`

- `POST /api/v1/analytics/events`
- `POST /api/v1/analytics/public/events` (ingesta publica para landing; opcional `X-Events-Key`)
- `GET /api/v1/analytics/public/metrics` (metrica de ingesta; solo admin/editor)

- `POST /api/v1/requests/public` (crea request anonimo de productos)
- `GET /api/v1/requests`
- `GET /api/v1/requests/{request_id}`
- `PATCH /api/v1/requests/{request_id}/status`

- `GET /api/v1/reporting/kpis`
- `GET /api/v1/reporting/top-products`
- `GET /api/v1/reporting/utm-referrer`
- `GET /api/v1/reporting/funnel`
- `GET /api/v1/reporting/top-requested-products`

- `GET /api/v1/audit/logs` (solo `admin`)

- `POST /api/v1/assets/upload-strategy`

## Contrato publico de tracking

`POST /api/v1/analytics/public/events` acepta contrato estricto:

- `event_name`: `impression | click | cta_click | add_to_request | request_submitted`
- `source` (canonico): `hero_cta | product_card | product_detail | category_grid | catalog_grid | floating_whatsapp | nav_cta | dashboard | unknown`
- `visitor_id`, `session_id`: formato acotado y validado
- `page_path`: path relativo (`/algo`)
- `idempotency_key`: obligatorio para dedupe server-side
- `occurred_at`: opcional; backend tambien guarda `received_at`
- Si `TRUST_PROXY_HEADERS=true`, el rate limit usa IP real derivada de headers (`CF-Connecting-IP`, `True-Client-IP`, `X-Forwarded-For`) solo cuando el peer pertenece a `TRUSTED_PROXY_CIDRS`.

`POST /api/v1/requests/public`:

- requiere `idempotency_key`
- `source` usa la misma taxonomia canonica
- crea automaticamente evento `request_submitted` vinculado al request
- soporta snapshot por item (`variant_size`, `variant_color`, `unit_price_cents`)

Maquina de estados de request (backend-enforced):

- `submitted -> paid -> fulfilled | declined_customer | declined_business`
- Compatibilidad legacy: `in_progress`/`contacted` se normalizan a `paid` en API.
- Reapertura a `submitted` solo si `REQUEST_ALLOW_REOPEN_TO_SUBMITTED=true`

Reporting para dashboard:

- `GET /api/v1/reporting/funnel` y `GET /api/v1/reporting/top-requested-products` aceptan `from`, `to`, `tz` (ademas de `start_at`, `end_at` para compatibilidad).
- Respuesta versionada con `version: "v1"` en ambos endpoints.

Retencion de tracking:

- Config: `TRACKING_RETENTION_DAYS`
- Comando dry-run:
  - `python -m app.retention --dry-run`
- Comando apply:
  - `python -m app.retention --apply`
- El comando registra metricas de purge (`candidates`, `deleted`, `elapsed_ms`) en logs.

Lectura publica de catalogo:

- Endpoints `/api/v1/public/*` no requieren JWT (solo lectura).
- Devuelven solo productos `published` (`status=active` en contrato publico).
- Campos administrativos/sensibles quedan fuera del contrato publico.
- Soportan cache headers:
  - `Cache-Control: public, s-maxage=60, stale-while-revalidate=300`
  - `ETag`
  - `Last-Modified`
- Para CORS de estos endpoints, incluir los dominios frontend en `CORS_ALLOWED_ORIGINS`.
- Soportan control operativo opcional con `X-Public-Read-Key` (`PUBLIC_READ_REQUIRE_KEY`, `PUBLIC_READ_KEY`, `PUBLIC_READ_KEYS`).

## Estrategia de assets

Este backend guarda `path` de imagen en DB (no URL completa):

- Cover de producto: `products.primary_image_path`
- Galeria de producto: `product_images.url` (path interno)
- Banner de noticia: `news.banner_image_path`
- Galeria de noticia: `news_images.url` (path interno)
- Imagenes de catalogo: `catalog_images.url` (path interno o URL externa segun flujo)

Flujo recomendado:

1. Dashboard sube archivo via `POST /api/v1/admin/products/{id}/image/cover` o `/gallery`.
2. Backend sube el binario a Supabase Storage.
3. Backend guarda solo `path` en DB.
4. API devuelve `public_url` calculada para render en frontend.

Esto evita subir binarios al backend y mantiene el API orientado a metadatos y gobierno editorial.

Reglas adicionales:

- Al eliminar un producto (`DELETE /api/v1/products/{id}`), el backend elimina primero `cover` y `gallery` del bucket (si `ASSET_PROVIDER=supabase`) y luego borra el registro en DB.
- Al eliminar una noticia (`DELETE /api/v1/news/{id}`), el backend elimina primero `banner` y `gallery` del bucket (si `ASSET_PROVIDER=supabase`) y luego borra el registro en DB.
- Para `POST /api/v1/assets/upload-strategy`, si `entity_type` empieza con `product`, `product_id` es obligatorio y debe existir en DB.
- Para `POST /api/v1/assets/upload-strategy`, si `entity_type` empieza con `news`, `news_id` es obligatorio y debe existir en DB.
  - Sugeridos: `product-cover` (path `products/{product_id}/cover.ext`) y `product-gallery` (path `products/{product_id}/gallery/...`).
  - Sugeridos: `news-banner` (path `news/{news_id}/cover.ext`) y `news-gallery` (path `news/{news_id}/gallery/...`).
