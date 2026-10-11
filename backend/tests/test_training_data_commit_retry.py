# 长评估任务收尾落库：连接被掐断后必须换连接重试，而不是把算完的分数全丢掉
#
# 实测事故：200 条 embedding 数据评估跑了 12 分钟（400 次远程 embedding 调用），
# 远端 PG 的空闲连接被网关掐断，收尾 commit 抛 ConnectionDoesNotExistError，
# 任务标记 failed 且一条结果都没存进去。
import pytest
from sqlalchemy.exc import OperationalError

from app.tasks.training_data_eval_tasks import _commit_safely


def _conn_lost() -> OperationalError:
    return OperationalError("UPDATE training_data_evals ...", {}, Exception("connection was closed in the middle of operation"))


class _FakeDB:
    """最小会话替身：按脚本抛错，记录 commit/rollback 次数"""

    def __init__(self, errors):
        self._errors = list(errors)
        self.commits = 0
        self.rollbacks = 0

    async def commit(self):
        self.commits += 1
        if self._errors:
            raise self._errors.pop(0)

    async def rollback(self):
        self.rollbacks += 1


def test_first_commit_failure_is_retried_on_new_connection():
    db = _FakeDB([_conn_lost()])
    import asyncio
    asyncio.run(_commit_safely(db))
    assert db.commits == 2, "第一次失败后要换新连接再提交一次"
    assert db.rollbacks == 1, "重试前必须先 rollback，否则会话卡在失败事务里"


def test_healthy_session_commits_once():
    db = _FakeDB([])
    import asyncio
    asyncio.run(_commit_safely(db))
    assert db.commits == 1
    assert db.rollbacks == 0


def test_persistent_failure_still_raises():
    db = _FakeDB([_conn_lost(), _conn_lost()])
    import asyncio
    with pytest.raises(OperationalError):
        asyncio.run(_commit_safely(db))
    assert db.commits == 2, "重试次数有上限，不能无限重连"