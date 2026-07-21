from __future__ import annotations

from datetime import timedelta

import alibabacloud_oss_v2 as oss
from alibabacloud_oss_v2.credentials import StaticCredentialsProvider
from fastapi import APIRouter, HTTPException

from app.common.settings import get_settings


router = APIRouter()


def _build_client() -> oss.Client:
    settings = get_settings()
    if not settings.oss_access_key_id or not settings.oss_access_key_secret or not settings.oss_bucket:
        raise HTTPException(
            status_code=500,
            detail="OSS credentials are missing. Fill OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET, and OSS_BUCKET.",
        )

    credentials_provider = StaticCredentialsProvider(
        access_key_id=settings.oss_access_key_id,
        access_key_secret=settings.oss_access_key_secret,
    )
    config = oss.config.load_default()
    config.credentials_provider = credentials_provider
    config.region = "cn-beijing"
    return oss.Client(config)


@router.get("/oss/presign")
def create_presigned_upload(filename: str):
    content_type_map = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
    }
    extension = filename.split(".")[-1].lower() if "." in filename else "jpg"
    content_type = content_type_map.get(extension, "application/octet-stream")

    settings = get_settings()
    client = _build_client()
    presigned = client.presign(
        oss.PutObjectRequest(
            bucket=settings.oss_bucket,
            key=filename,
            content_type=content_type,
        ),
        expires=timedelta(seconds=3600),
    )

    return {
        "uploadUrl": presigned.url.strip('"'),
        "contentType": content_type,
        "accessUrl": f"https://{settings.oss_bucket}.{settings.oss_endpoint}/{filename}",
    }
