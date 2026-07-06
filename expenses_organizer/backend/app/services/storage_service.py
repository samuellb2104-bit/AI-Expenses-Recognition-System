from __future__ import annotations

from pathlib import Path
from uuid import uuid4
from urllib import error, request

from app.core.config import settings


class StorageError(RuntimeError):
    pass


def _build_object_name(filename: str) -> str:
    safe_name = Path(filename).name or "document"
    return f"{uuid4()}_{safe_name}"


def store_file_locally(upload_dir: str, filename: str, content: bytes) -> str:
    uploads_root = Path(upload_dir)
    uploads_root.mkdir(parents=True, exist_ok=True)
    object_name = _build_object_name(filename)
    storage_path = uploads_root / object_name
    storage_path.write_bytes(content)
    return str(storage_path.as_posix())


def upload_to_supabase_storage(filename: str, content: bytes, content_type: str | None) -> str:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise StorageError("Supabase Storage is not configured.")

    object_name = _build_object_name(filename)
    upload_url = (
        f"{settings.supabase_url.rstrip('/')}/storage/v1/object/"
        f"{settings.supabase_storage_bucket}/{object_name}"
    )
    headers = {
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "apikey": settings.supabase_service_role_key,
        "Content-Type": content_type or "application/octet-stream",
        "x-upsert": "true",
    }
    req = request.Request(upload_url, data=content, headers=headers, method="POST")
    try:
        with request.urlopen(req) as resp:
            if resp.status not in (200, 201):
                raise StorageError(f"Unexpected storage response: {resp.status}")
    except error.HTTPError as exc:
        raise StorageError(f"Supabase Storage upload failed: {exc.read().decode('utf-8', errors='ignore')}") from exc
    except error.URLError as exc:
        raise StorageError(f"Supabase Storage connection failed: {exc.reason}") from exc

    return object_name
