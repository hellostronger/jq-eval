# 回归测试：任务里用 text() 裸 SQL 绑 UUID，在 SQLite 上直接炸
#
# 起因：为"适配器 success=False 必须落库为 failed"补测试时，_run_invocation
# 在 SQLite 上根本跑不起来：
#   InterfaceError: Error binding parameter 0 - probably unsupported type
#   [SQL: SELECT id, question FROM qa_records WHERE dataset_id = ?]
#   [parameters: (UUID('...'),)]
#
# text() 是裸 SQL，绕过 SQLAlchemy 的类型转换层。PostgreSQL 能隐式把
# UUID 对象转成字符串，SQLite 不行，于是同一段代码换个库就挂——
# 单元测试根本覆盖不到这些任务。
import ast
import pathlib

import pytest
from sqlalchemy import select

from app.models.dataset import Dataset, QARecord


def _task_files():
    root = pathlib.Path(__file__).resolve().parents[1] / "app" / "tasks"
    return sorted(root.glob("*.py"))


def test_no_raw_sql_binds_uuid_params():
    """任务层不该再用 text() 裸 SQL 绑定 UUID 参数

    用 ast 判断参数名，只盯着 *_id 这类确定会绑 UUID 的占位符，
    避免误伤正常的字符串查询。
    """
    offenders = []
    for path in _task_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "execute"):
                continue
            # 找出同一次调用里传入的参数字典
            for arg in node.args[1:]:
                if isinstance(arg, ast.Dict):
                    for k in arg.keys:
                        if (
                            isinstance(k, ast.Constant)
                            and isinstance(k.value, str)
                            and k.value.endswith("_id")
                        ):
                            offenders.append(f"{path.name}:{node.lineno} binds {k.value}")
    assert not offenders, "text() 裸 SQL 绑 UUID 在 SQLite 上会失败，请改用 ORM 查询：" + str(offenders)


@pytest.mark.asyncio
async def test_orm_query_with_uuid_filters_on_sqlite(db_session):
    """ORM 查询带 UUID 过滤条件在 SQLite 上正常工作（对照组）"""
    ds = Dataset(name="D", description="d", status="active")
    db_session.add(ds)
    await db_session.flush()
    db_session.add(QARecord(dataset_id=ds.id, question="q1", answer="a1"))
    await db_session.commit()

    rows = (await db_session.execute(
        select(QARecord.id, QARecord.question).where(QARecord.dataset_id == ds.id)
    )).all()
    assert len(rows) == 1
    assert rows[0].question == "q1"
