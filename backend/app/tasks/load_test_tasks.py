# 压测任务Celery实现
import asyncio
from typing import Dict, List, Any
from datetime import datetime
import logging
import time
import statistics
from uuid import UUID
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.core.celery_app import celery_app
from app.core.database import get_db_context
from app.models import LoadTest, LoadTestStatus, RAGSystem
from app.models.dataset import QARecord
from app.services.adapters import AdapterFactory, RAGResponse
from sqlalchemy import text

logger = logging.getLogger(__name__)


def run_async(coro):
    """在同步环境中运行异步函数"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, name="load_test_task")
def load_test_task(self, load_test_id: str) -> Dict[str, Any]:
    """执行压测任务

    Args:
        load_test_id: 压测任务ID (UUID字符串格式)
    """
    return run_async(_run_load_test(self, UUID(load_test_id)))


async def _run_load_test(task, load_test_id: UUID) -> Dict[str, Any]:
    """异步执行压测"""
    async with get_db_context() as db:
        # 获取压测配置
        load_test = await db.get(LoadTest, load_test_id)
        if not load_test:
            return {"error": f"压测任务 {load_test_id} 不存在"}

        # 更新状态
        load_test.status = LoadTestStatus.RUNNING.value
        load_test.started_at = datetime.utcnow()
        await db.commit()

        try:
            # 获取RAG系统配置
            rag_system = await db.get(RAGSystem, load_test.rag_system_id)
            if not rag_system:
                raise ValueError(f"RAG系统 {load_test.rag_system_id} 不存在")

            # 获取测试问题
            questions = load_test.questions or []
            if not questions and load_test.dataset_id:
                # 从数据集获取问题
                qa_records = await db.execute(
                    text("SELECT question FROM qa_records WHERE dataset_id = :dataset_id"),
                    {"dataset_id": load_test.dataset_id}
                )
                questions = [r._mapping["question"] for r in qa_records.fetchall()]

            if not questions:
                raise ValueError("没有可用的测试问题")

            # 创建RAG适配器
            adapter = AdapterFactory.create(
                rag_system.system_type,
                rag_system.connection_config
            )

            # 执行压测
            result = await _execute_load_test(
                task=task,
                adapter=adapter,
                questions=questions,
                test_type=load_test.test_type,
                latency_threshold=load_test.latency_threshold,
                concurrency=load_test.concurrency
            )

            # 保存结果
            load_test.result = result
            load_test.status = LoadTestStatus.COMPLETED.value
            load_test.completed_at = datetime.utcnow()
            load_test.progress = 100
            await db.commit()

            return {
                "load_test_id": str(load_test_id),
                "status": "completed",
                "result": result
            }

        except Exception as e:
            logger.error(f"压测任务 {load_test_id} 失败: {e}")
            await db.rollback()
            load_test = await db.get(LoadTest, load_test_id)
            if load_test:
                load_test.status = LoadTestStatus.FAILED.value
                load_test.error = str(e)
                load_test.completed_at = datetime.utcnow()
                await db.commit()
            return {"error": str(e)}


async def _execute_load_test(
    task,
    adapter,
    questions: List[str],
    test_type: str,
    latency_threshold: float,
    concurrency: int
) -> Dict[str, Any]:
    """执行并发压测"""
    # 根据测试类型选择调用方法
    is_first_token = test_type == "first_token"
    query_method = adapter.query_stream if is_first_token else adapter.query

    # 准备测试数据：循环使用问题
    test_questions = questions * (concurrency // len(questions) + 1)
    test_questions = test_questions[:concurrency]

    # 记录所有请求的延迟
    latencies: List[float] = []
    errors: List[str] = []
    success_count = 0

    # 使用信号量控制并发
    semaphore = asyncio.Semaphore(concurrency)

    async def single_request(question: str) -> Dict[str, Any]:
        """执行单个请求"""
        async with semaphore:
            try:
                start_time = time.time()
                response: RAGResponse = await query_method(question)
                latency = time.time() - start_time

                # 根据测试类型判断成功与否
                if is_first_token:
                    # 首token时间判断
                    actual_latency = response.first_token_latency or latency
                else:
                    # 完整响应时间判断
                    actual_latency = latency

                return {
                    "success": response.success and actual_latency <= latency_threshold,
                    "latency": actual_latency,
                    "full_latency": latency,
                    "error": response.error
                }
            except Exception as e:
                return {
                    "success": False,
                    "latency": 0,
                    "full_latency": 0,
                    "error": str(e)
                }

    # 记录整体开始时间
    overall_start = time.time()

    # 并发执行所有请求
    tasks = [single_request(q) for q in test_questions]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 记录整体结束时间
    overall_time = time.time() - overall_start

    # 统计结果
    for result in results:
        if isinstance(result, Exception):
            errors.append(str(result))
        elif result.get("success"):
            success_count += 1
            latencies.append(result["latency"])
        else:
            if result.get("error"):
                errors.append(result["error"])

    # 计算QPS
    qps = success_count / overall_time if overall_time > 0 else 0

    # 计算延迟统计
    latency_stats = {}
    if latencies:
        latency_stats = {
            "mean": statistics.mean(latencies),
            "median": statistics.median(latencies),
            "min": min(latencies),
            "max": max(latencies),
            "p50": statistics.median(latencies),
            "p90": statistics.quantiles(latencies, n=10)[8] if len(latencies) >= 10 else max(latencies),
            "p99": statistics.quantiles(latencies, n=100)[98] if len(latencies) >= 100 else max(latencies),
        }

    result = {
        "total_requests": len(test_questions),
        "success_count": success_count,
        "failed_count": len(test_questions) - success_count,
        "qps": qps,
        "overall_time": overall_time,
        "latency_threshold": latency_threshold,
        "test_type": test_type,
        "concurrency": concurrency,
        "latency_stats": latency_stats,
        "errors": errors[:10]  # 只保留前10个错误
    }

    logger.info(f"压测完成: QPS={qps:.2f}, 成功={success_count}/{len(test_questions)}, 耗时={overall_time:.2f}s")

    return result