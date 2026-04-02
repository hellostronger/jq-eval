# MinIO文件服务
import io
import uuid
from typing import Dict, List, Any, Optional, BinaryIO
from datetime import datetime, timedelta
import logging
from pathlib import Path

from minio import Minio
from minio.error import S3Error
from minio.deleteobjects import DeleteObject

from app.core.config import settings

logger = logging.getLogger(__name__)


class MinIOService:
    """MinIO文件存储服务"""

    def __init__(self):
        self.client = Minio(
            f"{settings.MINIO_HOST}:{settings.MINIO_PORT}",
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE
        )
        self._ensure_buckets()

    def _ensure_buckets(self):
        """确保必要的bucket存在"""
        buckets = [
            "datasets",      # 数据集文件（CSV, JSON, Excel）
            "documents",     # 文档文件
            "exports",       # 导出文件
            "temp",          # 临时文件
            "models",        # 模型相关文件
        ]

        for bucket in buckets:
            try:
                if not self.client.bucket_exists(bucket):
                    self.client.make_bucket(bucket)
                    logger.info(f"Created bucket: {bucket}")
            except S3Error as e:
                logger.error(f"Error creating bucket {bucket}: {e}")

    async def upload_file(
        self,
        bucket: str,
        file_data: BinaryIO,
        file_name: str,
        content_type: str = None,
        metadata: Dict[str, str] = None
    ) -> Dict[str, Any]:
        """上传文件"""
        try:
            # 生成唯一对象名
            object_name = f"{datetime.utcnow().strftime('%Y/%m/%d')}/{uuid.uuid4()}_{file_name}"

            # 获取文件大小
            file_data.seek(0, 2)
            file_size = file_data.tell()
            file_data.seek(0)

            # 上传
            self.client.put_object(
                bucket_name=bucket,
                object_name=object_name,
                data=file_data,
                length=file_size,
                content_type=content_type,
                metadata=metadata
            )

            return {
                "success": True,
                "bucket": bucket,
                "object_name": object_name,
                "original_name": file_name,
                "size": file_size,
                "url": self.get_presigned_url(bucket, object_name)
            }

        except S3Error as e:
            logger.error(f"Upload failed: {e}")
            return {"success": False, "error": str(e)}

    async def upload_from_path(
        self,
        bucket: str,
        file_path: str,
        object_name: str = None
    ) -> Dict[str, Any]:
        """从本地路径上传文件"""
        try:
            path = Path(file_path)
            if not path.exists():
                return {"success": False, "error": "File not found"}

            if not object_name:
                object_name = f"{datetime.utcnow().strftime('%Y/%m/%d')}/{uuid.uuid4()}_{path.name}"

            self.client.fput_object(
                bucket_name=bucket,
                object_name=object_name,
                file_path=file_path
            )

            return {
                "success": True,
                "bucket": bucket,
                "object_name": object_name,
                "original_name": path.name,
                "size": path.stat().st_size
            }

        except S3Error as e:
            logger.error(f"Upload from path failed: {e}")
            return {"success": False, "error": str(e)}

    async def download_file(
        self,
        bucket: str,
        object_name: str
    ) -> Dict[str, Any]:
        """下载文件"""
        try:
            response = self.client.get_object(bucket, object_name)
            data = response.read()
            response.close()
            response.release_conn()

            return {
                "success": True,
                "data": data,
                "bucket": bucket,
                "object_name": object_name
            }

        except S3Error as e:
            logger.error(f"Download failed: {e}")
            return {"success": False, "error": str(e)}

    async def download_to_path(
        self,
        bucket: str,
        object_name: str,
        file_path: str
    ) -> Dict[str, Any]:
        """下载文件到本地路径"""
        try:
            self.client.fget_object(bucket, object_name, file_path)
            return {
                "success": True,
                "bucket": bucket,
                "object_name": object_name,
                "local_path": file_path
            }

        except S3Error as e:
            logger.error(f"Download to path failed: {e}")
            return {"success": False, "error": str(e)}

    def get_presigned_url(
        self,
        bucket: str,
        object_name: str,
        expires: int = 3600
    ) -> str:
        """获取预签名URL"""
        try:
            url = self.client.presigned_get_object(
                bucket,
                object_name,
                expires=timedelta(seconds=expires)
            )
            return url
        except S3Error as e:
            logger.error(f"Get presigned URL failed: {e}")
            return ""

    def get_presigned_upload_url(
        self,
        bucket: str,
        object_name: str,
        expires: int = 3600
    ) -> str:
        """获取上传预签名URL"""
        try:
            url = self.client.presigned_put_object(
                bucket,
                object_name,
                expires=timedelta(seconds=expires)
            )
            return url
        except S3Error as e:
            logger.error(f"Get presigned upload URL failed: {e}")
            return ""

    async def delete_file(
        self,
        bucket: str,
        object_name: str
    ) -> Dict[str, Any]:
        """删除文件"""
        try:
            self.client.remove_object(bucket, object_name)
            return {"success": True, "bucket": bucket, "object_name": object_name}
        except S3Error as e:
            logger.error(f"Delete failed: {e}")
            return {"success": False, "error": str(e)}

    async def delete_files(
        self,
        bucket: str,
        object_names: List[str]
    ) -> Dict[str, Any]:
        """批量删除文件"""
        try:
            delete_objects = [DeleteObject(name) for name in object_names]
            errors = list(self.client.remove_objects(bucket, delete_objects))

            if errors:
                for err in errors:
                    logger.error(f"Delete error: {err}")

            return {
                "success": len(errors) == 0,
                "deleted": len(object_names) - len(errors),
                "errors": errors
            }

        except S3Error as e:
            logger.error(f"Batch delete failed: {e}")
            return {"success": False, "error": str(e)}

    async def list_files(
        self,
        bucket: str,
        prefix: str = "",
        recursive: bool = True
    ) -> List[Dict[str, Any]]:
        """列出文件"""
        try:
            objects = self.client.list_objects(bucket, prefix=prefix, recursive=recursive)
            files = []

            for obj in objects:
                files.append({
                    "object_name": obj.object_name,
                    "size": obj.size,
                    "last_modified": obj.last_modified.isoformat() if obj.last_modified else None,
                    "etag": obj.etag,
                    "content_type": obj.content_type
                })

            return files

        except S3Error as e:
            logger.error(f"List files failed: {e}")
            return []

    async def get_file_info(
        self,
        bucket: str,
        object_name: str
    ) -> Dict[str, Any]:
        """获取文件信息"""
        try:
            stat = self.client.stat_object(bucket, object_name)
            return {
                "success": True,
                "object_name": object_name,
                "size": stat.size,
                "last_modified": stat.last_modified.isoformat(),
                "etag": stat.etag,
                "content_type": stat.content_type,
                "metadata": stat.metadata
            }

        except S3Error as e:
            logger.error(f"Get file info failed: {e}")
            return {"success": False, "error": str(e)}

    async def copy_file(
        self,
        source_bucket: str,
        source_object: str,
        dest_bucket: str,
        dest_object: str
    ) -> Dict[str, Any]:
        """复制文件"""
        try:
            from minio.commonconfig import CopySource

            self.client.copy_object(
                dest_bucket,
                dest_object,
                CopySource(source_bucket, source_object)
            )

            return {
                "success": True,
                "source": f"{source_bucket}/{source_object}",
                "destination": f"{dest_bucket}/{dest_object}"
            }

        except S3Error as e:
            logger.error(f"Copy failed: {e}")
            return {"success": False, "error": str(e)}

    async def get_bucket_stats(self, bucket: str) -> Dict[str, Any]:
        """获取bucket统计信息"""
        try:
            objects = self.client.list_objects(bucket, recursive=True)
            total_size = 0
            file_count = 0

            for obj in objects:
                total_size += obj.size or 0
                file_count += 1

            return {
                "bucket": bucket,
                "file_count": file_count,
                "total_size": total_size,
                "total_size_mb": total_size / (1024 * 1024)
            }

        except S3Error as e:
            logger.error(f"Get bucket stats failed: {e}")
            return {"error": str(e)}

    async def list_buckets(self) -> List[str]:
        """列出所有bucket"""
        try:
            buckets = self.client.list_buckets()
            return [bucket.name for bucket in buckets]
        except S3Error as e:
            logger.error(f"List buckets failed: {e}")
            return []


# 全局实例
minio_service = MinIOService()


def get_minio_service() -> MinIOService:
    """获取MinIO服务实例"""
    return minio_service