# 文件存储API
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

from app.services.storage import get_minio_service, MinIOService
from app.core.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


class FileUploadResponse(BaseModel):
    """文件上传响应"""
    success: bool
    bucket: str
    object_name: str
    original_name: str
    size: int
    url: Optional[str] = None
    error: Optional[str] = None


class FileInfo(BaseModel):
    """文件信息"""
    object_name: str
    size: int
    last_modified: Optional[str] = None
    etag: Optional[str] = None
    content_type: Optional[str] = None


class BucketStats(BaseModel):
    """Bucket统计"""
    bucket: str
    file_count: int
    total_size: int
    total_size_mb: float


@router.post("/upload/{bucket}", response_model=FileUploadResponse)
async def upload_file(
    bucket: str,
    file: UploadFile = File(...),
    minio: MinIOService = Depends(get_minio_service)
):
    """上传文件到指定bucket"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    # 检查bucket是否存在
    buckets = await minio.list_buckets()
    if bucket not in buckets:
        raise HTTPException(status_code=400, detail=f"Bucket '{bucket}' 不存在")

    result = await minio.upload_file(
        bucket=bucket,
        file_data=file.file,
        file_name=file.filename,
        content_type=file.content_type
    )

    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["error"])

    return FileUploadResponse(**result)


@router.post("/upload-dataset")
async def upload_dataset_file(
    file: UploadFile = File(...),
    minio: MinIOService = Depends(get_minio_service)
):
    """上传数据集文件（CSV, JSON, Excel）"""
    allowed_extensions = [".csv", ".json", ".xlsx", ".xls"]
    file_ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename else ""

    if f".{file_ext}" not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式，仅支持: {allowed_extensions}"
        )

    result = await minio.upload_file(
        bucket="datasets",
        file_data=file.file,
        file_name=file.filename,
        content_type=file.content_type
    )

    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["error"])

    return result


@router.get("/download/{bucket}/{object_name:path}")
async def get_download_url(
    bucket: str,
    object_name: str,
    expires: int = Query(3600, ge=60, le=86400),
    minio: MinIOService = Depends(get_minio_service)
):
    """获取文件下载URL"""
    url = minio.get_presigned_url(bucket, object_name, expires)
    if not url:
        raise HTTPException(status_code=404, detail="文件不存在或无法生成URL")

    return {"url": url, "expires_in": expires}


@router.get("/info/{bucket}/{object_name:path}")
async def get_file_info(
    bucket: str,
    object_name: str,
    minio: MinIOService = Depends(get_minio_service)
):
    """获取文件信息"""
    result = await minio.get_file_info(bucket, object_name)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.delete("/delete/{bucket}/{object_name:path}")
async def delete_file(
    bucket: str,
    object_name: str,
    minio: MinIOService = Depends(get_minio_service)
):
    """删除文件"""
    result = await minio.delete_file(bucket, object_name)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["error"])
    return {"message": "文件已删除"}


@router.post("/delete-batch/{bucket}")
async def delete_files_batch(
    bucket: str,
    object_names: List[str],
    minio: MinIOService = Depends(get_minio_service)
):
    """批量删除文件"""
    result = await minio.delete_files(bucket, object_names)
    return result


@router.get("/list/{bucket}", response_model=List[FileInfo])
async def list_files(
    bucket: str,
    prefix: str = Query("", description="文件前缀过滤"),
    recursive: bool = Query(True, description="是否递归列出"),
    minio: MinIOService = Depends(get_minio_service)
):
    """列出bucket中的文件"""
    files = await minio.list_files(bucket, prefix, recursive)
    return [FileInfo(**f) for f in files]


@router.get("/stats/{bucket}", response_model=BucketStats)
async def get_bucket_stats(
    bucket: str,
    minio: MinIOService = Depends(get_minio_service)
):
    """获取bucket统计信息"""
    stats = await minio.get_bucket_stats(bucket)
    if "error" in stats:
        raise HTTPException(status_code=500, detail=stats["error"])
    return BucketStats(**stats)


@router.get("/buckets")
async def list_buckets(
    minio: MinIOService = Depends(get_minio_service)
):
    """列出所有bucket"""
    buckets = await minio.list_buckets()
    return {"buckets": buckets}


@router.post("/copy")
async def copy_file(
    source_bucket: str,
    source_object: str,
    dest_bucket: str,
    dest_object: str,
    minio: MinIOService = Depends(get_minio_service)
):
    """复制文件"""
    result = await minio.copy_file(source_bucket, source_object, dest_bucket, dest_object)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.post("/upload-url/{bucket}/{object_name:path}")
async def get_upload_url(
    bucket: str,
    object_name: str,
    expires: int = Query(3600, ge=60, le=86400),
    minio: MinIOService = Depends(get_minio_service)
):
    """获取上传预签名URL（用于客户端直传）"""
    url = minio.get_presigned_upload_url(bucket, object_name, expires)
    if not url:
        raise HTTPException(status_code=500, detail="无法生成上传URL")

    return {"url": url, "expires_in": expires, "object_name": object_name}