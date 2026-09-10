# Celery 配置正确性与就绪探针测试
#
# Celery 对拼错的配置键不报错、静默忽略——Beat 任务名打错 = 定时任务永远不跑，
# 重试配置写错 = 故障时才发现根本没重试。本文件用自省把这类"配了但没生效"钉死：
# 所有用户侧配置键必须存在于 Celery 官方 SETTING_KEYS；Beat 引用的任务名必须已注册；
# broker/result URL 与 .env.example 模板必须同源不漂移。
# 另覆盖 /api/v1/ready 的就绪语义：降级必须 503、两种状态响应体结构一致、探针有超时。
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest
from celery.app.defaults import SETTING_KEYS

from app.core.celery_app import celery_app
from app.core.config import Settings, settings

# celery 读取过时键时写入的内部记账键，非用户配置，不参与有效性检查
_CELERY_INTERNAL_KEYS = {"deprecated_settings"}


def test_all_user_celery_config_keys_are_valid():
    """历史教训：result_backend_connection_* 与 broker_connection_retry_delay 是臆造键，
    Celery 5.6 实测不在 SETTING_KEYS，配了完全无效——此测试防止同类再犯"""
    user_keys = set(celery_app._preconf) - _CELERY_INTERNAL_KEYS
    invalid = {k for k in user_keys if k not in SETTING_KEYS}
    assert not invalid, f"无效 Celery 配置键（会被静默忽略）: {invalid}"


def test_beat_schedule_task_names_registered():
    """Beat 引用未注册任务名不会让 Beat 报错失败，只会被 worker 拒收后反复重投。
    与 worker 启动同款链路：loader.import_default_modules() 加载 conf.imports 清单。
    （注：单纯访问 celery_app.tasks 不会加载 conf.imports——这是本测试第一版踩的坑）"""
    celery_app.loader.import_default_modules()
    entries = celery_app.conf.beat_schedule
    assert entries, "beat_schedule 不应为空"
    known = set(celery_app.tasks)
    unknown = {e["task"] for e in entries.values()} - known
    assert not unknown, f"Beat 调度了未注册的任务: {unknown}"


def test_imports_list_modules_all_register_tasks():
    """conf.imports 清单里的模块若不存在/导入炸/没定义任务，worker 会带病启动；
    导入后逐个断言其模块内至少注册了一个任务"""
    from celery.app.task import Task
    celery_app.loader.import_default_modules()
    import importlib
    registered = set(celery_app.tasks)
    for module_path in celery_app.conf.imports:
        mod = importlib.import_module(module_path)
        task_names = {
            obj.name for attr, obj in vars(mod).items()
            if isinstance(obj, Task) and obj.name in registered
        }
        assert task_names, f"{module_path} 未向 celery_app 注册任何任务（疑似死模块）"


def test_result_backend_retry_effectively_configured():
    assert celery_app.conf.result_backend_always_retry is True


def test_celery_urls_single_source_and_db_split():
    """URL 只能有一个事实来源（config.py），且 broker 与 result 必须分库：
    同库时结果键与队列键混在一个 DB，清理/FLUSHDB 互相波及"""
    assert celery_app.conf.broker_url == settings.CELERY_BROKER_URL
    assert celery_app.conf.result_backend == settings.CELERY_RESULT_BACKEND
    assert urlparse(settings.CELERY_BROKER_URL).path != urlparse(settings.CELERY_RESULT_BACKEND).path


def test_env_example_celery_db_numbers_in_sync():
    """模板与代码默认值只比对 Redis DB 编号（主机/密码允许因部署环境不同而覆盖）"""
    pure = Settings(_env_file=None)
    env_example = Path(__file__).resolve().parents[2] / ".env.example"
    text = env_example.read_text(encoding="utf-8")
    lines = dict(
        line.split("=", 1) for line in text.splitlines()
        if line.startswith(("CELERY_BROKER_URL=", "CELERY_RESULT_BACKEND="))
    )
    assert urlparse(lines["CELERY_BROKER_URL"]).path == urlparse(pure.CELERY_BROKER_URL).path
    assert urlparse(lines["CELERY_RESULT_BACKEND"]).path == urlparse(pure.CELERY_RESULT_BACKEND).path


# ---------- /ready 就绪探针契约 ----------
# 探针全部 monkeypatch：不依赖开发机/CI 上中间件的真实状态（恒 200 断言会随机飘），
# 只验证端点自身的状态聚合与 HTTP 语义

class _FakeRedis:
    async def ping(self):
        return True

    async def aclose(self):
        return None


@pytest.fixture
def patched_probes(monkeypatch, test_engine):
    """默认全健康；测试可覆盖单个探针函数。DB 探针用测试 SQLite 引擎"""
    import app.api.v1.health as h
    monkeypatch.setattr(h, "async_engine", test_engine)
    monkeypatch.setattr(h, "aioredis", SimpleNamespace(from_url=lambda *a, **k: _FakeRedis()))
    monkeypatch.setattr(h, "_probe_milvus", lambda: None)
    monkeypatch.setattr(h, "_probe_minio", lambda: None)
    return h


@pytest.mark.asyncio
async def test_ready_all_healthy_returns_200(client, patched_probes):
    resp = await client.get("/api/v1/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert all(s["status"] == "healthy" for s in body["services"].values())


@pytest.mark.asyncio
async def test_ready_degraded_returns_503_with_details(client, patched_probes, monkeypatch):
    """就绪语义核心：降级必须 503（恒 200 会让编排照常放流，探针形同虚设），
    但响应体结构一致——前端从 503 的 body 渲染分项红/绿标签而非整页报错"""
    def _down():
        raise ConnectionError("milvus refused")
    monkeypatch.setattr(patched_probes, "_probe_milvus", _down)
    resp = await client.get("/api/v1/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["services"]["milvus"]["status"] == "unhealthy"
    assert "milvus refused" in body["services"]["milvus"]["error"]
    assert body["services"]["redis"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_ready_probe_timeout(client, patched_probes, monkeypatch):
    """被防火墙 DROP 的主机让 TCP 连接挂起分钟级——探针必须有自身超时，
    否则就绪检查比故障本身更难发现"""
    import time
    monkeypatch.setattr(patched_probes, "PROBE_TIMEOUT", 0.2)
    monkeypatch.setattr(patched_probes, "_probe_minio", lambda: time.sleep(5))
    resp = await client.get("/api/v1/ready")
    assert resp.status_code == 503
    svc = resp.json()["services"]["minio"]
    assert svc["status"] == "unhealthy" and "超时" in svc["error"]


@pytest.mark.asyncio
async def test_health_stays_liveness_only(client):
    """/health 是存活探针：不探测依赖、恒 200，与 /ready 职责分离"""
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy"}
