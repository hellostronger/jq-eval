# 更新模型不能把没被界面暴露的 params 悄悄抹掉
#
# 隐患：PUT /models/{id} 用 data 整体重建 model.params，只写
# temperature / max_tokens / extra_params / parse_config。而
# llm_client.create_llm_from_config 读的是 params.timeout 和
# params.max_retries——这两个只能直接改数据库设，一旦从界面编辑一次
# 模型就无声丢失，出站超时悄悄回落到 300s。
#
# 思考型模型在有网关上限的环境里正是靠这个超时活着（本次排查中
# 上游 300s 就掐掉了一批调用），所以这里锁死"能配、且编辑不丢"。
import pytest

from app.api.v1.models import ModelCreate, update_model


class _FakeModel:
    """update_model 需要的最小模型对象"""

    def __init__(self, params):
        self.id = "00000000-0000-0000-0000-000000000000"
        self.name = "m"
        self.model_type = "llm"
        self.provider = "openai"
        self.model_name = "gpt"
        self.endpoint = "http://x/v1"
        self.api_key_encrypted = "sk-orig"
        self.params = params
        self.is_default = False
        self.dimension = None
        self.max_input_length = None
        self.save_logs = False
        self.is_vlm = False
        self.status = "active"


class _FakeDB:
    def __init__(self, model):
        self._model = model
        self.committed = False

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        pass


class _Ctx:
    """模拟 get_or_404：直接返回给定对象"""

    def __init__(self, model):
        self.model = model

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def patched(monkeypatch):
    from app.api.v1 import models as models_api

    holder = {}

    def install(model):
        holder["model"] = model
        holder["db"] = _FakeDB(model)

        async def fake_get_or_404(db, cls, obj_id, msg):
            return model

        monkeypatch.setattr(models_api, "get_or_404", fake_get_or_404)
        return holder

    return install


@pytest.mark.asyncio
async def test_update_keeps_timeout_when_not_submitted(patched):
    """界面没提交 timeout 时，库里已有的值必须原样保留"""
    model = _FakeModel({"temperature": 0.7, "max_tokens": 2048, "timeout": 1200})
    env = patched(model)

    await update_model(
        model.id,
        ModelCreate(name="m", model_type="llm", temperature=0.9, max_tokens=4096),
        env["db"],
    )

    assert model.params["timeout"] == 1200, "编辑一次就把超时配置抹了"
    assert model.params["max_tokens"] == 4096, "显式提交的字段要正常更新"


@pytest.mark.asyncio
async def test_update_writes_timeout_when_submitted(patched):
    """显式提交 timeout 时要写进 params，供 llm_client 读取"""
    model = _FakeModel({"temperature": 0.7, "max_tokens": 2048})
    env = patched(model)

    await update_model(
        None,
        ModelCreate(name="m", model_type="llm", timeout=900, max_retries=1),
        env["db"],
    )

    assert model.params["timeout"] == 900
    assert model.params["max_retries"] == 1


@pytest.mark.asyncio
async def test_absent_timeout_is_not_written(patched):
    """没配过就不要写入 0/None，llm_client 才有默认值可用"""
    model = _FakeModel({"temperature": 0.7, "max_tokens": 2048})
    env = patched(model)

    await update_model(None, ModelCreate(name="m", model_type="llm"), env["db"])

    assert "timeout" not in model.params
    assert "max_retries" not in model.params


@pytest.mark.asyncio
async def test_llm_client_actually_reads_these_keys():
    """params 里的键名必须和 llm_client 读的一致，否则改了也不生效"""
    import inspect

    from app.services.llm.llm_client import create_llm_from_config

    src = inspect.getsource(create_llm_from_config)
    assert 'params.get("timeout"' in src, "llm_client 不读 timeout，暴露这个配置就是假的"
    assert 'params.get("max_retries"' in src
