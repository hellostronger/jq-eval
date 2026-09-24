# MinerU 官方 API doc_parser 测试：探活请求构建 + test_model 分支

from app.api.v1.models import _build_doc_parser_test_request


class _M:
    def __init__(self, endpoint, api_key):
        self.endpoint = endpoint
        self.api_key_encrypted = api_key


def test_mineru_api_build_request_uses_file_urls_batch():
    """MinerU 官方API 无健康检查端点：用 POST /file-urls/batch 空请求验证 Token"""
    req = _build_doc_parser_test_request("mineru_api", _M(None, "sk-test"))
    assert req["url"] == "https://mineru.net/api/v4/file-urls/batch"
    assert req["method"] == "POST"
    assert req["headers"]["Authorization"] == "Bearer sk-test"
    assert req["body"] == {"files": [], "model_version": "vlm"}


def test_mineru_api_without_key_returns_empty_url():
    """未配置 API Key 时不应构造外网请求"""
    req = _build_doc_parser_test_request("mineru_api", _M(None, ""))
    assert req["url"] == ""
