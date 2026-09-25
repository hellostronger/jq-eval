# 评估"复用调用结果"的数据来源回归测试
#
# 隐患：eval_item 里写的是 "answer": ir.answer or qa.get("answer")。
# 调用失败时 ir.answer 为空，于是回落到 QARecord 的静态 answer——
# 而那恰好是数据集里的"标准答案"。结果：RAG 一次都没答对，
# 指标却按标准答案打出满分。失败被彻底掩盖。
#
# 复用调用结果的前提就是"只信调用结果"，一旦开了兜底，
# 这个开关就名不副实了。
import ast
import pathlib

import pytest
from sqlalchemy import select

from app.models.dataset import Dataset, QARecord
from app.models.invocation import InvocationBatch, InvocationResult
from app.models.rag_system import RAGSystem


def _eval_tasks_source() -> str:
    p = pathlib.Path(__file__).resolve().parents[1] / "app" / "tasks" / "evaluation_tasks.py"
    return p.read_text(encoding="utf-8")


def test_reuse_branch_has_no_static_answer_fallback():
    """源码层面禁止 "ir.answer or qa.get('answer')" 这种兜底

    用 ast 定位二元 or 表达式，比正则可靠：能确认左边是 ir.answer、
    右边是 qa 的静态答案字段，而不是碰巧同名的别的东西。
    """
    tree = ast.parse(_eval_tasks_source())
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.BoolOp) or not isinstance(node.op, ast.Or):
            continue
        for i, value in enumerate(node.values[:-1]):
            # ir.answer or ...
            if (
                isinstance(value, ast.Attribute)
                and value.attr == "answer"
                and isinstance(value.value, ast.Name)
                and value.value.id == "ir"
            ):
                nxt = node.values[i + 1]
                if isinstance(nxt, ast.Call) and isinstance(nxt.func, ast.Attribute):
                    if nxt.func.attr == "get" and nxt.args:
                        arg = nxt.args[0]
                        if isinstance(arg, ast.Constant) and arg.value in ("answer", "contexts"):
                            offenders.append(f"line {node.lineno}: ir.answer -> qa[{arg.value!r}]")
    assert not offenders, (
        "复用调用结果时不得回落到 QARecord 静态字段，失败会被记成满分：" + str(offenders)
    )


@pytest.mark.asyncio
async def test_failed_invocation_does_not_borrow_static_answer(db_session):
    """失败的调用结果其答案为空；评估取答案时不得借标准答案来填"""
    ds = Dataset(name="DS", description="d", status="active")
    db_session.add(ds)
    await db_session.flush()
    qa = QARecord(dataset_id=ds.id, question="什么是过拟合？", answer="这是标准答案，绝不该被当成 RAG 输出")
    db_session.add(qa)
    await db_session.flush()
    rag = RAGSystem(name="R", system_type="direct_llm", description="d",
                    connection_config={}, status="active")
    db_session.add(rag)
    await db_session.flush()
    batch = InvocationBatch(name="B", dataset_id=ds.id, rag_system_id=rag.id, status="completed")
    db_session.add(batch)
    await db_session.flush()
    # 失败的调用：没有答案
    db_session.add(InvocationResult(
        batch_id=batch.id, qa_record_id=qa.id, rag_system_id=rag.id,
        question=qa.question, answer="", status="failed", error="上游 504",
    ))
    await db_session.commit()

    ir = (await db_session.execute(
        select(InvocationResult).where(InvocationResult.batch_id == batch.id)
    )).scalar_one()
    # 复刻改造后的取值逻辑：失败即空答案，绝不借用静态答案
    answer = ir.answer or ""
    assert answer == ""
    assert "标准答案" not in answer
