# 压测任务Celery实现
import asyncio
from typing import Dict, List, Any, Optional
from datetime import datetime
import logging
import time
import statistics
from uuid import UUID
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.core.celery_app import celery_app
from app.core.database import get_db_context
from app.models import LoadTest, LoadTestStatus, LoadTestMode, RAGSystem
from app.models.dataset import QARecord
from app.models.model import Model
from app.services.adapters import AdapterFactory, RAGResponse
from sqlalchemy import text, select

logger = logging.getLogger(__name__)


async def _build_direct_llm_adapter(model: Model) -> Any:
    """为大模型直连压测构建适配器（复用 direct_llm 适配器）"""
    config = {
        "api_endpoint": model.endpoint,
        "api_key": model.api_key_encrypted or "",
        "model_name": model.model_name or model.name,
        "provider": model.provider or "openai",
    }
    if model.params:
        config["temperature"] = model.params.get("temperature", 0.7)
        config["max_tokens"] = model.params.get("max_tokens", 2048)
        extra = model.params.get("extra_params")
        if extra:
            config["extra_params"] = extra
    return AdapterFactory.create("direct_llm", config)


async def _prepare_direct_llm_config(connection_config: Dict[str, Any], db) -> Dict[str, Any]:
    """为直连LLM类型准备完整配置"""
    llm_model_id = connection_config.get("llm_model_id")
    if not llm_model_id:
        return connection_config

    try:
        result = await db.execute(select(Model).where(Model.id == UUID(llm_model_id)))
        model = result.scalar_one_or_none()
        if not model:
            return connection_config

        config = connection_config.copy()
        config["api_endpoint"] = model.endpoint
        config["api_key"] = model.api_key_encrypted or ""
        config["model_name"] = model.model_name or model.name
        config["provider"] = connection_config.get("provider") or model.provider or "openai"

        if model.params:
            config["temperature"] = connection_config.get("temperature") or model.params.get("temperature", 0.7)
            config["max_tokens"] = connection_config.get("max_tokens") or model.params.get("max_tokens", 2048)
            # 额外请求参数：调用方配置可覆盖模型默认
            extra = dict(model.params.get("extra_params") or {})
            extra.update(connection_config.get("extra_params") or {})
            if extra:
                config["extra_params"] = extra

        return config
    except Exception as e:
        logger.error(f"获取LLM模型配置失败: {e}")
        return connection_config


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
            # 确定压测对象：target_model_id（大模型直连）优先，其次 rag_system_id
            adapter = None
            if load_test.target_model_id:
                model = await db.get(Model, load_test.target_model_id)
                if not model or model.model_type != "llm":
                    raise ValueError(f"压测目标模型 {load_test.target_model_id} 不存在或不是 LLM 类型")
                adapter = await _build_direct_llm_adapter(model)
            else:
                # 获取RAG系统配置
                rag_system = await db.get(RAGSystem, load_test.rag_system_id)
                if not rag_system:
                    raise ValueError(f"RAG系统 {load_test.rag_system_id} 不存在")

                # 创建RAG适配器
                config = rag_system.connection_config
                if rag_system.system_type == "direct_llm":
                    config = await _prepare_direct_llm_config(config, db)
                adapter = AdapterFactory.create(
                    rag_system.system_type,
                    config
                )

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

            # 根据测试模式执行不同的压测逻辑
            if load_test.test_mode == LoadTestMode.QPS_LIMIT.value:
                result = await _execute_qps_limit_test(
                    task=task,
                    db=db,
                    load_test=load_test,
                    adapter=adapter,
                    questions=questions
                )
            elif load_test.test_mode == LoadTestMode.LATENCY_DIST.value:
                result = await _execute_latency_dist_test(
                    task=task,
                    db=db,
                    load_test=load_test,
                    adapter=adapter,
                    questions=questions
                )
            else:
                raise ValueError(f"未知的测试模式: {load_test.test_mode}")

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


async def _execute_qps_limit_test(
    task,
    db,
    load_test,
    adapter,
    questions: List[str]
) -> Dict[str, Any]:
    """执行QPS上限测试 - 自动递增并发找上限"""
    initial_concurrency = load_test.initial_concurrency or 10
    step = load_test.step or 10
    max_concurrency = load_test.max_concurrency or 100
    latency_threshold = load_test.latency_threshold
    test_type = load_test.test_type

    if latency_threshold is None:
        raise ValueError("QPS上限测试需要设置latency_threshold")

    step_results = []
    max_successful_qps = 0
    max_successful_concurrency = 0

    current_concurrency = initial_concurrency
    while current_concurrency <= max_concurrency:
        # 更新进度
        progress = int((current_concurrency / max_concurrency) * 80)
        load_test.progress = progress
        await db.commit()

        # 执行当前并发级别的测试
        result = await _execute_single_test(
            adapter=adapter,
            questions=questions,
            test_type=test_type,
            latency_threshold=latency_threshold,
            concurrency=current_concurrency
        )

        step_results.append({
            "concurrency": current_concurrency,
            "qps": result["qps"],
            "success_rate": result["success_count"] / result["total_requests"],
            "latency_stats": result["latency_stats"],
            "meets_threshold": result["success_count"] == result["total_requests"] and (
                not result["latency_stats"] or result["latency_stats"].get("max", 0) <= latency_threshold
            ),
            "failed_count": result["failed_count"],
            "error_summary": result.get("error_summary"),
        })

        logger.info(f"并发={current_concurrency}, QPS={result['qps']:.2f}, 成功率={result['success_count']}/{result['total_requests']}, 错误分类={result.get('error_summary', {}).get('error_categories')}")

        # 判断是否达标：全部成功且最大延迟在阈值内
        if result["success_count"] == result["total_requests"] and result["latency_stats"]:
            max_p99 = result["latency_stats"].get("max", 0)
            if max_p99 <= latency_threshold:
                max_successful_qps = result["qps"]
                max_successful_concurrency = current_concurrency
                current_concurrency += step
                continue

        # 不达标，记录终止原因后返回上一级结果
        stop_reason = "unknown"
        if result["success_count"] < result["total_requests"]:
            cats = (result.get("error_summary") or {}).get("error_categories") or {}
            stop_reason = "request_failed" if cats.get("延迟超阈值") != result["failed_count"] else "latency_exceeded"
            if not cats:
                stop_reason = "request_failed"
        elif result["latency_stats"] and result["latency_stats"].get("max", 0) > latency_threshold:
            stop_reason = "latency_exceeded"

        return {
            "test_mode": "qps_limit",
            "max_qps": max_successful_qps,
            "max_concurrency": max_successful_concurrency,
            "latency_threshold": latency_threshold,
            "test_type": test_type,
            "step_results": step_results,
            "stopped_at_concurrency": current_concurrency,
            "stop_reason": stop_reason,
        }

    # 全部并发级别都达标（正常结束循环）
    return {
        "test_mode": "qps_limit",
        "max_qps": max_successful_qps,
        "max_concurrency": max_successful_concurrency,
        "latency_threshold": latency_threshold,
        "test_type": test_type,
        "step_results": step_results,
        "stopped_at_concurrency": None,
        "stop_reason": "max_concurrency_reached",
    }


async def _execute_latency_dist_test(
    task,
    db,
    load_test,
    adapter,
    questions: List[str]
) -> Dict[str, Any]:
    """执行响应时间分布测试 - 多个并发级别测试"""
    concurrency_levels = load_test.concurrency_levels or [1, 5, 10, 20, 50, 100]
    latency_threshold = load_test.latency_threshold
    test_type = load_test.test_type

    levels_results = []
    total_levels = len(concurrency_levels)

    for idx, concurrency in enumerate(concurrency_levels):
        # 更新进度
        progress = int((idx / total_levels) * 80)
        load_test.progress = progress
        await db.commit()

        # 执行当前并发级别的测试
        result = await _execute_single_test(
            adapter=adapter,
            questions=questions,
            test_type=test_type,
            latency_threshold=latency_threshold,
            concurrency=concurrency
        )

        meets_threshold = False
        if latency_threshold is not None and result["latency_stats"]:
            max_latency = result["latency_stats"].get("max", 0)
            meets_threshold = result["success_count"] == result["total_requests"] and max_latency <= latency_threshold

        levels_results.append({
            "concurrency": concurrency,
            "qps": result["qps"],
            "success_rate": result["success_count"] / result["total_requests"],
            "latency_stats": result["latency_stats"],
            "meets_threshold": meets_threshold,
            "failed_count": result["failed_count"],
            "error_summary": result.get("error_summary"),
        })

        logger.info(f"并发={concurrency}, QPS={result['qps']:.2f}, 延迟分布={result['latency_stats']}")

    return {
        "test_mode": "latency_dist",
        "test_type": test_type,
        "latency_threshold": latency_threshold,
        "levels": levels_results
    }


def _summarize_errors(results: List[Any], is_first_token: bool, latency_threshold: Optional[float]) -> Dict[str, Any]:
    """把单步请求结果汇总成错误分类统计 + 失败样本明细

    分类维度：请求异常(抛错) / 接口报错(适配器返回error) / 延迟超阈值 / 空响应
    """
    error_categories: Dict[str, int] = {}
    failed_samples: List[Dict[str, Any]] = []
    slow_count = 0
    request_fail_count = 0

    def classify(error: str) -> str:
        e = (error or "").lower()
        if "timeout" in e or "timed out" in e:
            return "请求超时"
        if "connect" in e and ("error" in e or "refused" in e or "failed" in e):
            return "连接失败"
        if "401" in e or "unauthorized" in e or "api key" in e or "invalid_request_error" in e and "api" in e:
            return "鉴权失败"
        if "429" in e or "rate limit" in e:
            return "限流(429)"
        if "500" in e or "502" in e or "503" in e or "internal server" in e:
            return "服务端错误(5xx)"
        return "其他错误"

    for idx, r in enumerate(results):
        if isinstance(r, Exception):
            error_categories["请求异常"] = error_categories.get("请求异常", 0) + 1
            request_fail_count += 1
            if len(failed_samples) < 20:
                failed_samples.append({
                    "index": idx,
                    "fail_type": "exception",
                    "error": str(r)[:500],
                })
            continue

        success = r.get("success")
        error = r.get("error")
        latency = r.get("latency") or 0
        full_latency = r.get("full_latency") or 0

        if success:
            continue

        # 失败原因分类
        if is_first_token and not error and r.get("first_token_latency") is None:
            category = "无首token输出"
        elif latency_threshold is not None and not error and full_latency > 0 and latency > latency_threshold:
            category = "延迟超阈值"
            slow_count += 1
        elif error:
            category = classify(error)
            request_fail_count += 1
        else:
            category = "空响应"
            request_fail_count += 1

        error_categories[category] = error_categories.get(category, 0) + 1
        if len(failed_samples) < 20:
            failed_samples.append({
                "index": idx,
                "fail_type": "slow" if category == "延迟超阈值" else "request_error",
                "latency": round(full_latency, 3),
                "error": (error or category)[:500],
            })

    # 提取最常见的原始错误信息（截断去重）
    top_errors: List[str] = []
    seen = set()
    for r in results:
        if isinstance(r, Exception):
            msg = str(r)[:300]
        elif not r.get("success") and r.get("error"):
            msg = str(r["error"])[:300]
        else:
            continue
        if msg not in seen:
            seen.add(msg)
            top_errors.append(msg)
        if len(top_errors) >= 10:
            break

    return {
        "error_categories": error_categories,
        "failed_samples": failed_samples,
        "top_errors": top_errors,
        "slow_count": slow_count,
        "request_fail_count": request_fail_count,
    }


async def _execute_single_test(
    adapter,
    questions: List[str],
    test_type: str,
    latency_threshold: float,
    concurrency: int
) -> Dict[str, Any]:
    """执行单次并发测试"""
    # 根据测试类型选择调用方法
    is_first_token = test_type == "first_token"
    query_method = adapter.query_stream if is_first_token else adapter.query

    # 准备测试数据：循环使用问题
    test_questions = questions * (concurrency // len(questions) + 1)
    test_questions = test_questions[:concurrency]

    # 记录所有请求的延迟
    latencies: List[float] = []
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
                    actual_latency = response.first_token_latency or latency
                else:
                    actual_latency = latency

                return {
                    "success": response.success and (latency_threshold is None or actual_latency <= latency_threshold),
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
            continue
        elif result.get("success"):
            success_count += 1
            latencies.append(result["latency"])

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

    # 错误分类统计与失败样本（失败原因可观测）
    error_summary = _summarize_errors(results, is_first_token, latency_threshold)

    return {
        "total_requests": len(test_questions),
        "success_count": success_count,
        "failed_count": len(test_questions) - success_count,
        "qps": qps,
        "overall_time": overall_time,
        "latency_stats": latency_stats,
        "error_summary": error_summary,
    }