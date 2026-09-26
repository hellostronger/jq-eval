# MinIO文件服务
import uuid
import re
from typing import Dict, List, Any, BinaryIO
from datetime import datetime, timedelta
import logging
from minio import Minio
from minio.error import S3Error
from minio.deleteobjects import DeleteObject

from app.core.config import settings
from app.core.exceptions import format_error

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
        self._buckets_ready = False
        self.ensure_buckets()

    def ensure_buckets(self) -> None:
        """确保必要的bucket存在（幂等；未就绪时后续调用会重试）

        MinIO 未就绪时 bucket_exists 抛 urllib3 连接级异常而非 S3Error，
        构造器在模块导入时执行——不吞掉会让整个应用启动失败。
        """
        if self._buckets_ready:
            return
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
            except Exception as e:
                logger.warning(f"MinIO 暂不可达（{type(e).__name__}），bucket 检查延后重试: {e}")
                return
        self._buckets_ready = True

    @staticmethod
    def _sanitize_object_path(file_name: str) -> tuple:
        """把调用方传入的文件名拆成 (基础名, 目录前缀)

        目录前缀会被保留（文档解析按 datasets/<id>/ 前缀筛选数据集内源文件），
        但每段都要单独清洗：过滤危险字符、丢弃空段与 "." / ".."，
        因此无法通过 ../ 之类的输入跳出预期目录。
        """
        raw = (file_name or "file").replace("\\", "/")
        segments = [s for s in raw.split("/") if s not in ("", ".", "..")]

        def clean(seg: str) -> str:
            return re.sub(r"[^A-Za-z0-9._\-一-鿿]", "_", seg).strip("._")

        if not segments:
            return "file", ""

        base = clean(segments[-1]) or "file"
        dirs = [clean(s) for s in segments[:-1]]
        dirs = [d for d in dirs if d]
        prefix = "/".join(dirs) + "/" if dirs else ""
        return base, prefix

    async def upload_file(
        self,
        bucket: str,
        file_data: BinaryIO,
        file_name: str,
        content_type: str = None,
        metadata: Dict[str, str] = None
    ) -> Dict[str, Any]:
        """上传文件

        file_name 可以带目录前缀（如 datasets/<id>/report.pdf），前缀会被保留：
        文档解析的「数据集内源文件」就靠 datasets/<id>/ 前缀来按数据集筛选，
        早期版本用 os.path.basename 把前缀丢掉了，导致按数据集列源文件永远是空。
        安全性靠逐段清洗保证——每段都过滤危险字符并丢弃 "." / ".."，无法穿越目录。
        """
        try:
            safe_name, safe_prefix = self._sanitize_object_path(file_name)
            # 生成唯一对象名
            date_prefix = datetime.utcnow().strftime('%Y/%m/%d')
            object_name = f"{safe_prefix}{date_prefix}/{uuid.uuid4()}_{safe_name}"

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
            return {"success": False, "error": format_error(e)}

    async def download_file(
        self,
        bucket: str,
        object_name: str
    ) -> Dict[str, Any]:
        """下载文件"""
        try:
            response = self.client.get_object(bucket, object_name)
            try:
                data = response.read()
            finally:
                # 读流中途异常也要归还连接，否则 urllib3 连接泄漏
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
            return {"success": False, "error": format_error(e)}

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
            return {"success": False, "error": format_error(e)}

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
            return {"success": False, "error": format_error(e)}

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
            return {"success": False, "error": format_error(e)}

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
            return {"success": False, "error": format_error(e)}

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
            return {"error": format_error(e)}

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
    """获取MinIO服务实例（使用前补齐启动时未就绪的 bucket）"""
    minio_service.ensure_buckets()
    return minio_service