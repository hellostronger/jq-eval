# 评估派发前的 LLM 依赖校验
#
# 真实故障：模型「Qwen3.8-Flash-Next」入库时没填 API Key，评估照样创建并派发成功，
# worker 里 ChatOpenAI 抛 langchain 自己的校验文本
# （"Did not find openai_api_key, please add an environment variable…"），
# 7.8s 后把评估置成 failed。用户在详情页只看到一段内部报错，
# 分不清是模型没配还是系统坏了，还白烧了一次 worker 往返。
import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.evaluations import _llm_dependent_metrics, require_llm_credentials
from app.models import Dataset, Model

GENERATION_METRICS = ["faithfulness", "answer_correctness"]
RETRIEVAL_METRICS = ["recall_k", "mrr_k", "hit_rate_k"]


async def _keyless_model(db: AsyncSession, api_key=None) -> Model:
    model = Model(
        name="网关模型", model_type="llm", provider="openai",
        model_name="Qwen3.8-Flash-Next", endpoint="http://gateway:3000/v1",
        api_key_encrypted=api_key, status="active",
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return model


class TestMetricRequirementSource:
    def test_llm_dependent_metrics_come_from_registry(self):
        # 生成类要 LLM，纯检索类不要——守卫只该拦前者
        assert set(_llm_dependent_metrics(GENERATION_METRICS + RETRIEVAL_METRICS)) == {
            "faithfulness", "answer_correctness"
        }
        assert _llm_dependent_metrics(RETRIEVAL_METRICS) == []

    def test_unknown_metric_does_not_crash_the_guard(self):
        assert _llm_dependent_metrics(["not_a_metric"]) == []


@pytest.mark.asyncio
async def test_guard_rejects_keyless_model(db_session: AsyncSession):
    model = await _keyless_model(db_session, api_key=None)
    with pytest.raises(HTTPException) as exc:
        await require_llm_credentials(db_session, GENERATION_METRICS, model.id)
    assert exc.value.status_code == 400
    detail = exc.value.detail
    assert "网关模型" in detail and "API Key" in detail
    # 报错要点名被挡住的指标，否则用户不知道少配了什么
    assert "faithfulness" in detail


@pytest.mark.asyncio
async def test_guard_rejects_blank_key(db_session: AsyncSession):
    """空串/空格等于没配：ChatOpenAI 同样会拒绝"""
    model = await _keyless_model(db_session, api_key="   ")
    with pytest.raises(HTTPException):
        await require_llm_credentials(db_session, GENERATION_METRICS, model.id)


@pytest.mark.asyncio
async def test_guard_rejects_missing_endpoint(db_session: AsyncSession):
    model = await _keyless_model(db_session, api_key="sk-x")
    model.endpoint = None
    await db_session.commit()
    with pytest.raises(HTTPException) as exc:
        await require_llm_credentials(db_session, GENERATION_METRICS, model.id)
    assert "endpoint" in exc.value.detail


@pytest.mark.asyncio
async def test_guard_lets_retrieval_only_evaluation_through(db_session: AsyncSession):
    """纯检索评估不碰 LLM，缺密钥也必须放行——否则召回对比根本跑不起来"""
    model = await _keyless_model(db_session, api_key=None)
    assert await require_llm_credentials(db_session, RETRIEVAL_METRICS, model.id) is None


@pytest.mark.asyncio
async def test_create_evaluation_blocked_before_key_configured(
    client: AsyncClient, db_session: AsyncSession, sample_dataset: Dataset
):
    model = await _keyless_model(db_session, api_key=None)
    resp = await client.post("/api/v1/evaluations", json={
        "name": "端到端评测", "dataset_id": str(sample_dataset.id),
        "llm_model_id": str(model.id), "metrics": GENERATION_METRICS + RETRIEVAL_METRICS,
    })
    assert resp.status_code == 400, resp.text
    assert "API Key" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_create_evaluation_passes_once_key_filled(
    client: AsyncClient, db_session: AsyncSession, sample_dataset: Dataset
):
    """补上密钥后同一份请求必须能建——守卫不能变成新的人工改库"""
    model = await _keyless_model(db_session, api_key="sk-real")
    resp = await client.post("/api/v1/evaluations", json={
        "name": "端到端评测", "dataset_id": str(sample_dataset.id),
        "llm_model_id": str(model.id), "metrics": GENERATION_METRICS + RETRIEVAL_METRICS,
    })
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_run_blocked_after_key_deleted(
    client: AsyncClient, db_session: AsyncSession, sample_dataset: Dataset
):
    """创建之后密钥被删：run 也要拦，且不能把状态留在 running"""
    model = await _keyless_model(db_session, api_key="sk-real")
    created = await client.post("/api/v1/evaluations", json={
        "name": "eval-later", "dataset_id": str(sample_dataset.id),
        "llm_model_id": str(model.id), "metrics": ["faithfulness"],
    })
    assert created.status_code == 200, created.text
    eval_id = created.json()["id"]

    model.api_key_encrypted = None
    await db_session.commit()

    resp = await client.post(f"/api/v1/evaluations/{eval_id}/run")
    assert resp.status_code == 400, resp.text
    assert "API Key" in resp.json()["detail"]

    after = await client.get(f"/api/v1/evaluations/{eval_id}")
    assert after.json()["status"] == "pending", "被拦下的任务不该被置成 running"
