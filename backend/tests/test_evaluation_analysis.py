# 根因分析端点回归测试
# GET /evaluations/{id}/analysis —— README 宣传的"根因分析"核心功能
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dataset, QARecord
from app.models.evaluation import Evaluation, EvalResult, EvaluationStatus


async def _make_eval_with_results(
    db: AsyncSession, dataset: Dataset, retrieval: float, generation: float
) -> Evaluation:
    qr = QARecord(dataset_id=dataset.id, question="q", answer="a")
    db.add(qr)
    await db.commit()
    await db.refresh(qr)

    ev = Evaluation(name="an-eval", dataset_id=dataset.id,
                    metrics=["context_precision", "faithfulness"],
                    status=EvaluationStatus.COMPLETED)
    db.add(ev)
    await db.commit()
    await db.refresh(ev)

    db.add(EvalResult(
        eval_id=ev.id, qa_record_id=qr.id,
        scores={
            "context_precision": {"score": retrieval, "details": None, "error": None},
            "faithfulness": {"score": generation, "details": None, "error": None},
        },
    ))
    await db.commit()
    return ev


@pytest.mark.asyncio
async def test_analysis_locates_retrieval_bottleneck(
    client: AsyncClient, db_session: AsyncSession, sample_dataset: Dataset
):
    """检索均值 < 阈值 → 根因定位 retrieval"""
    ev = await _make_eval_with_results(db_session, sample_dataset, retrieval=0.3, generation=0.8)

    resp = await client.get(f"/api/v1/evaluations/{ev.id}/analysis")
    assert resp.status_code == 200
    analysis = resp.json()["analysis"]
    assert analysis["root_cause"]["stage"] == "retrieval"
    assert "context_precision" in analysis["weak_metrics"]
    assert len(analysis["recommendations"]) >= 1


@pytest.mark.asyncio
async def test_analysis_locates_generation_hallucination(
    client: AsyncClient, db_session: AsyncSession, sample_dataset: Dataset
):
    """检索达标但 faithfulness 低 → 根因定位 generation"""
    ev = await _make_eval_with_results(db_session, sample_dataset, retrieval=0.9, generation=0.2)

    resp = await client.get(f"/api/v1/evaluations/{ev.id}/analysis")
    analysis = resp.json()["analysis"]
    assert analysis["root_cause"]["stage"] == "generation"
    assert "faithfulness" in analysis["weak_metrics"]


@pytest.mark.asyncio
async def test_analysis_healthy_baseline(
    client: AsyncClient, db_session: AsyncSession, sample_dataset: Dataset
):
    """两阶段都达标 → stage none，无低分指标"""
    ev = await _make_eval_with_results(db_session, sample_dataset, retrieval=0.9, generation=0.85)

    resp = await client.get(f"/api/v1/evaluations/{ev.id}/analysis")
    analysis = resp.json()["analysis"]
    assert analysis["root_cause"]["stage"] == "none"
    assert analysis["weak_metrics"] == []


@pytest.mark.asyncio
async def test_analysis_no_results_returns_400(
    client: AsyncClient, db_session: AsyncSession, sample_dataset: Dataset
):
    """无评估结果时明确报 400 而不是空分析"""
    ev = Evaluation(name="empty", dataset_id=sample_dataset.id,
                    metrics=["faithfulness"], status=EvaluationStatus.COMPLETED)
    db_session.add(ev)
    await db_session.commit()

    resp = await client.get(f"/api/v1/evaluations/{ev.id}/analysis")
    assert resp.status_code == 400
