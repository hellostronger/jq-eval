# MinIO 对象名构造测试
#
# 回归背景：upload_file 曾用 os.path.basename 丢弃调用方传入的目录前缀，
# 而文档解析的「数据集内源文件」正是靠 datasets/<id>/ 前缀按数据集筛选，
# 于是源文件列表永远是空的、发起解析永远选不到文件。
# 现在改为逐段清洗并保留前缀，安全性靠丢弃 "." / ".." 保证。
import pytest

from app.services.storage.minio_service import MinIOService


class TestSanitizeObjectPath:
    """纯函数，不需要数据库/中间件"""

    def test_plain_filename_keeps_no_prefix(self):
        base, prefix = MinIOService._sanitize_object_path("report.pdf")
        assert base == "report.pdf"
        assert prefix == ""

    def test_dataset_prefix_is_preserved(self):
        base, prefix = MinIOService._sanitize_object_path("datasets/abc-123/report.pdf")
        assert base == "report.pdf"
        assert prefix == "datasets/abc-123/"

    def test_nested_prefix_preserved(self):
        _, prefix = MinIOService._sanitize_object_path("datasets/abc/2026/09/report.pdf")
        assert prefix == "datasets/abc/2026/09/"

    def test_empty_and_none_fall_back_to_file(self):
        for value in ("", None, "..", "///"):
            base, prefix = MinIOService._sanitize_object_path(value)
            assert base == "file"
            assert prefix == ""

    @pytest.mark.parametrize("evil", [
        "../../etc/passwd",
        "datasets/../../x/../../y.pdf",
        "a/b/../../../c.pdf",
        "datasets/abc/../../../../root/.ssh/id_rsa",
    ])
    def test_path_traversal_segments_are_dropped(self, evil):
        """不能靠 ../ 跳出预期目录：所有 ".." 段都必须被丢弃"""
        base, prefix = MinIOService._sanitize_object_path(evil)
        assert ".." not in base
        assert ".." not in prefix
        assert not prefix.startswith("/")
        assert ".." not in prefix.split("/")

    def test_dangerous_chars_replaced(self):
        base, _ = MinIOService._sanitize_object_path("a b;rm -rf.pdf")
        assert " " not in base
        assert ";" not in base

    def test_chinese_name_preserved(self):
        base, prefix = MinIOService._sanitize_object_path("datasets/abc/机器学习.pdf")
        assert base == "机器学习.pdf"
        assert prefix == "datasets/abc/"

    def test_backslash_treated_as_separator(self):
        base, prefix = MinIOService._sanitize_object_path("datasets\\abc\\r.pdf")
        assert base == "r.pdf"
        assert prefix == "datasets/abc/"
